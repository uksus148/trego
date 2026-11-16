"""Discover sourced route candidates; API persistence is a separate boundary."""

import asyncio
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from gopstop_agent.config import Settings
from gopstop_agent.diagnostics import candidate_scope, stage, finding_event
from gopstop_agent.exa import ExaSearch, ResearchSource
from gopstop_agent.geocoding_candidates import CandidateSelection
from gopstop_agent.geocoding import GeocodedPlace, NominatimGeocoder, OSM_ATTRIBUTION
from gopstop_agent.intent import ClaudeIntentExtractor, IntentClarificationRequired, Message, ProviderTimeout, RouteIntent
from gopstop_agent.llm import ToolModel, create_tool_model
from gopstop_agent.popular import PopularPlaceSelector
from gopstop_agent.resolution_cache import CachedPlaceResolver
from gopstop_agent.resolver import ClaudePlaceResolver, SourceResolution


# Identity guards (requested_identity_mismatch, conflicting_identity, outside_context) are final.
NEARBY_LOOKUP_REASONS = frozenset({"no_sources", "insufficient_evidence", "no_geocoding_candidates",
                                   "name_mismatch", "type_mismatch", "ambiguous_candidates"})


# Start, end and the five intermediate stops a route accepts.
MAX_EXPLORE_PLACES = 7


class DiscoveredPlace(BaseModel):
    name: str
    tags: list[str]
    source: ResearchSource
    location: GeocodedPlace


class PlaceFinding(BaseModel):
    description: str
    sources: list[ResearchSource]
    place: DiscoveredPlace | None = None
    outcome: Literal["not_attempted", "no_sources", "insufficient_evidence", "geocoding"] = "not_attempted"
    selection: CandidateSelection | None = None
    resolution: SourceResolution | None = Field(default=None, exclude=True)

    @property
    def reason(self) -> str:
        return "resolved" if self.place is not None else self.selection.reason if self.selection else self.outcome


class DiscoveryResult(BaseModel):
    intent: RouteIntent
    start: PlaceFinding | None = None
    stops: list[PlaceFinding] = Field(default_factory=list)
    end: PlaceFinding | None = None
    attribution: str = OSM_ATTRIBUTION

    @property
    def unresolved(self) -> list[str]:
        return list(dict.fromkeys(finding.description for finding in [self.start, *self.stops, self.end]
                                  if finding is not None and finding.place is None))

    @property
    def missing_endpoints(self) -> list[str]:
        return [name for name in ("start", "end") if getattr(self.intent, name) is None]

    @property
    def unresolved_targets(self) -> list[dict]:
        targets = [("start", None, self.start), *(("stop", i + 1, finding) for i, finding in enumerate(self.stops)),
                   ("end", None, self.end)]
        return [{"role": role, "number": number, "description": finding.description}
                for role, number, finding in targets if finding is not None and finding.place is None]

    @property
    def ready_for_handoff(self) -> bool:
        return not self.missing_endpoints and bool(self.start and self.start.place and self.end and self.end.place
                    and all(finding.place is not None for finding in self.stops))


class PlaceDiscovery:
    def __init__(self, intent: ClaudeIntentExtractor, search: ExaSearch,
                 resolver: ClaudePlaceResolver | CachedPlaceResolver, geocoder: NominatimGeocoder,
                 timeout_seconds: float = 60, popular: PopularPlaceSelector | None = None) -> None:
        self._intent, self._search, self._resolver, self._geocoder = intent, search, resolver, geocoder
        self._timeout_seconds, self._popular = timeout_seconds, popular

    async def discover(self, message: str, history: list[Message]) -> DiscoveryResult:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                try:
                    with stage("intent"):
                        intent = await self._intent.extract(message, history)
                except IntentClarificationRequired:
                    # A tour request can make the extractor list many sights as stops.
                    area = await self._tour_area(message)
                    if area is None:
                        raise
                    return await self._explore(RouteIntent(), area)

                # Only a request without a route between two different places can be a tour;
                # the extractor may render "I am in Paris" as Paris -> Paris.
                if intent.start is None or intent.end is None or (intent.start.casefold() == intent.end.casefold() and not intent.mustSee):
                    area = await self._tour_area(message)
                    if area is not None:
                        return await self._explore(intent, area)
                return await self._resolve(intent)
        except TimeoutError as exc:
            raise ProviderTimeout("Place discovery exceeded its time limit.", reason="discovery_deadline") from exc

    async def _resolve(self, intent: RouteIntent) -> DiscoveryResult:
        if intent.start is None or intent.end is None:
            return DiscoveryResult(intent=intent)
        resolutions: dict[str, SourceResolution] = {}

        async def locate(finding: PlaceFinding, resolution: SourceResolution,
                         anchors: list[GeocodedPlace]) -> None:
            finding.resolution = resolution
            with stage("geocoding"):
                selection = await self._geocoder.geocode_result(
                    resolution.geocodeQuery, name=resolution.name,
                    tags=resolution.tags, anchors=anchors,
                    # Model classification cannot authorize an identity change.
                    requested_name=finding.description,
                )
            finding.outcome, finding.selection = "geocoding", selection
            finding_event(finding.reason, len(finding.sources), selection)
            location = selection.location
            if location is not None:
                finding.place = DiscoveredPlace(
                    name=resolution.name, tags=resolution.tags,
                    source=finding.sources[resolution.sourceIndex], location=location,
                )

        async def locate_nearby(finding: PlaceFinding, anchors: list[GeocodedPlace]) -> None:
            with stage("geocoding"):
                selection = await self._geocoder.geocode_nearby(finding.description, anchors)
            location = selection.location
            if location is None:
                return
            name = location.display_name.split(",")[0].strip()
            finding.outcome, finding.selection = "geocoding", selection
            finding.place = DiscoveredPlace(
                name=name, tags=[], location=location,
                source=ResearchSource(title=name, sourceUrl=location.osm_url),
            )
            finding_event(finding.reason, len(finding.sources), selection)

        async def find(description: str) -> PlaceFinding:
            query = (f"Find information about this exact place: {description}. Route context: "
                     f"{intent.start or 'unspecified'} to {intent.end or 'unspecified'}.")
            with stage("research"):
                sources = await self._search.search(query)
            finding = PlaceFinding(description=description, sources=sources)
            if not sources:
                finding.outcome = "no_sources"
                finding_event(finding.reason, 0)
                return finding
            with stage("resolution"):
                # The route-scoped search query is not the target identity.
                resolution = await self._resolver.resolve(description, sources)
            if resolution is not None:
                resolutions[description] = resolution
                await locate(finding, resolution, [])
            else:
                finding.outcome = "insufficient_evidence"
                finding_event(finding.reason, len(sources))
            return finding

        limit = asyncio.Semaphore(3)

        async def bounded(index: int, description: str) -> PlaceFinding:
            with candidate_scope(index):
                async with limit:
                    return await find(description)

        targets = [intent.start, *intent.mustSee, intent.end]
        tasks = {name: asyncio.create_task(bounded(index, name))
                 for index, name in enumerate(dict.fromkeys(targets)) if name is not None}
        try:
            await asyncio.gather(*tasks.values())
        finally:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
        # Reconsider ambiguous candidate sets using only independently
        # resolved route points. Reuse search results without another model
        # call; do not cascade a contextual choice into new anchors.
        anchors = [task.result().place.location for task in tasks.values() if task.result().place]
        if anchors:
            for index, (name, task) in enumerate(tasks.items()):
                if task.result().place is None and name in resolutions:
                    with candidate_scope(index):
                        await locate(task.result(), resolutions[name], anchors)
        if isinstance(self._resolver, CachedPlaceResolver):
            with stage("resolution_cache_validation"):
                for name, resolution in resolutions.items():
                    finding = tasks[name].result()
                    await self._resolver.record_selection(name, finding.sources, resolution,
                                                          accepted=finding.place is not None)
        # An explicit name that research could not identify may still be one exactly
        # named OSM place beside the route; OSM is then its recorded source. This runs
        # after cache feedback so a rejected model resolution is never promoted.
        for index, task in enumerate(tasks.values()):
            finding = task.result()
            if anchors and finding.place is None and finding.reason in NEARBY_LOOKUP_REASONS:
                with candidate_scope(index):
                    await locate_nearby(finding, anchors)
        start = tasks[intent.start].result() if intent.start is not None else None
        stops = [tasks[name].result() for name in intent.mustSee]
        end = tasks[intent.end].result() if intent.end is not None else None
        return DiscoveryResult(intent=intent, start=start, stops=stops, end=end)

    async def _tour_area(self, message: str) -> str | None:
        if self._popular is None:
            return None
        with stage("intent"):
            return await self._popular.area(message)

    async def _explore(self, intent: RouteIntent, area: str) -> DiscoveryResult:
        """Tour an area's popular sights from its westernmost to its easternmost one."""
        located = await self._resolve(RouteIntent(start=area, end=area))
        if located.start is None or located.start.place is None:
            return DiscoveryResult(intent=intent.model_copy(update={"start": area, "end": area}),
                                   start=located.start, end=located.start)
        anchor = located.start.place.location
        with stage("research"):
            sources = await self._search.search(f"Most popular must-see sights and landmarks to visit on foot in {area}")
        with stage("resolution"):
            suggestions = await self._popular.select(area, sources)
        found: dict[tuple[str, int], PlaceFinding] = {}
        for index, suggestion in enumerate(suggestions):
            if len(found) == MAX_EXPLORE_PLACES:
                break
            # Suggestions are optional: one without a single exact OSM match is skipped.
            with candidate_scope(index), stage("geocoding"):
                selection = await self._geocoder.geocode_nearby(suggestion.name, [anchor])
            finding_event(selection.reason, len(sources), selection)
            if selection.location is None:
                continue
            identity = selection.location.osm_type, selection.location.osm_id
            found.setdefault(identity, PlaceFinding(
                description=suggestion.name, sources=sources, outcome="geocoding", selection=selection,
                place=DiscoveredPlace(name=suggestion.name, tags=[], source=sources[suggestion.sourceIndex],
                                      location=selection.location)))
        if len(found) < 2:
            return DiscoveryResult(intent=intent)
        ordered = sorted(found.values(), key=lambda finding: finding.place.location.lon)
        names = [finding.description for finding in ordered]
        route = intent.model_copy(update={"start": names[0], "end": names[-1], "mustSee": names[1:-1],
                                          "descriptiveTargets": []})
        return DiscoveryResult(intent=route, start=ordered[0], stops=ordered[1:-1], end=ordered[-1])


def create_discovery(client: httpx.AsyncClient, cache: Redis, settings: Settings,
                     tool_model: ToolModel | None = None, *, diagnostic_namespace: str | None = None,
                     cold_geocoding: bool = False) -> PlaceDiscovery:
    """Compose discovery during opt-in chat startup or explicit fixture use."""
    settings.require_chat_configuration()
    key = settings.llm_key.get_secret_value()
    exa_key = settings.exa_api_key.get_secret_value()
    model = tool_model or create_tool_model(client, settings)
    timeout = settings.provider_timeout_seconds
    return PlaceDiscovery(
        ClaudeIntentExtractor(client, key, settings.llm_model, timeout, tool_model=model),
        ExaSearch(client, cache, exa_key, timeout, cache_namespace=f"{diagnostic_namespace}:exa" if diagnostic_namespace else "gopstop:exa-text:v1"),
        CachedPlaceResolver(ClaudePlaceResolver(client, key, settings.llm_model, timeout, tool_model=model), cache,
                            cache_namespace=f"{diagnostic_namespace}:resolution" if diagnostic_namespace else "gopstop:place-resolution:v3"),
        NominatimGeocoder(client, cache, settings.nominatim_user_agent,
                          str(settings.nominatim_base_url), timeout,
                          cache_namespace=f"{diagnostic_namespace}:nominatim" if diagnostic_namespace and cold_geocoding else "gopstop:nominatim:search:v3"),
        settings.discovery_timeout_seconds, PopularPlaceSelector(model, settings.llm_model),
    )
