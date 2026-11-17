"""Discover sourced route candidates; API persistence is a separate boundary."""

import asyncio
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from trego_agent.config import Settings
from trego_agent.diagnostics import candidate_scope, stage, finding_event
from trego_agent.exa import ExaSearch, ResearchSource
from trego_agent.geocoding_candidates import CandidateSelection
from trego_agent.geocoding import GeocodedPlace, NominatimGeocoder, OSM_ATTRIBUTION
from trego_agent.intent import (ClaudeIntentExtractor, IntentClarificationRequired, Message, ProviderTimeout,
                                  RouteIntent, named_in_message)
from trego_agent.llm import ToolModel, create_tool_model
from trego_agent.popular import PopularPlaceSelector
from trego_agent.resolution_cache import CachedPlaceResolver
from trego_agent.resolver import ClaudePlaceResolver, SourceResolution


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
                except IntentClarificationRequired as exc:
                    # A tour request can list more sights than a route allows stops. Sights the
                    # user wrote are kept; ones the extractor suggested itself give way to research.
                    area = await self._tour_area(message)
                    named = exc.places if named_in_message(exc.places, message) else []
                    if area is None or len(named) > MAX_EXPLORE_PLACES:
                        raise
                    return await self._explore(RouteIntent(), area, named)

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

    async def _explore(self, intent: RouteIntent, area: str, named: list[str] | None = None) -> DiscoveryResult:
        """Tour an area's sights from the westernmost to the easternmost one.

        Named sights are the user's own and must all be found; otherwise popular sights
        from research are optional candidates."""
        located = await self._resolve(RouteIntent(start=area, end=area))
        if located.start is None or located.start.place is None:
            return DiscoveryResult(intent=intent.model_copy(update={"start": area, "end": area}),
                                   start=located.start, end=located.start)
        anchor = located.start.place.location
        if named:
            findings = [await self._locate_sight(index, name, anchor) for index, name in enumerate(named)]
            if any(finding.place is None for finding in findings):
                return DiscoveryResult(intent=intent.model_copy(update={
                    "start": named[0], "end": named[-1], "mustSee": named[1:-1], "descriptiveTargets": []}),
                    start=findings[0], stops=findings[1:-1], end=findings[-1])
        else:
            findings = await self._popular_sights(area, anchor)
        found: dict[tuple[str, int], PlaceFinding] = {}
        for finding in findings:
            location = finding.place.location
            found.setdefault((location.osm_type, location.osm_id), finding)
        if len(found) < 2:
            # No tour: ask for endpoints. A same-city loop names no destination of its own.
            loop = intent.start is not None and intent.end is not None and intent.start.casefold() == intent.end.casefold()
            return DiscoveryResult(intent=intent.model_copy(update={"end": None}) if loop else intent)
        ordered = sorted(found.values(), key=lambda finding: finding.place.location.lon)
        names = [finding.description for finding in ordered]
        route = intent.model_copy(update={"start": names[0], "end": names[-1], "mustSee": names[1:-1],
                                          "descriptiveTargets": []})
        return DiscoveryResult(intent=route, start=ordered[0], stops=ordered[1:-1], end=ordered[-1])

    async def _popular_sights(self, area: str, anchor: GeocodedPlace) -> list[PlaceFinding]:
        with stage("research"):
            sources = await self._search.search(f"Most popular must-see sights and landmarks to visit on foot in {area}")
        with stage("resolution"):
            suggestions = await self._popular.select(area, sources)
        found: dict[tuple[str, int], PlaceFinding] = {}
        for index, suggestion in enumerate(suggestions):
            if len(found) == MAX_EXPLORE_PLACES:
                break
            # Suggestions are optional: one without a single exact OSM match is skipped.
            finding = await self._locate_sight(index, suggestion.name, anchor, sources, sources[suggestion.sourceIndex])
            if finding.place is not None:
                found.setdefault((finding.place.location.osm_type, finding.place.location.osm_id), finding)
        return list(found.values())

    async def _locate_sight(self, index: int, name: str, anchor: GeocodedPlace,
                            sources: list[ResearchSource] | None = None,
                            source: ResearchSource | None = None) -> PlaceFinding:
        """Bind a sight to the single exactly named OSM object near the area."""
        with candidate_scope(index), stage("geocoding"):
            selection = await self._geocoder.geocode_nearby(name, [anchor])
        finding_event(selection.reason, len(sources or []), selection)
        finding = PlaceFinding(description=name, sources=sources or [], outcome="geocoding", selection=selection)
        location = selection.location
        if location is None:
            return finding
        # A sight the user named has no research source; its OSM object is the evidence.
        evidence = source or ResearchSource(title=name, sourceUrl=location.osm_url)
        return finding.model_copy(update={"place": DiscoveredPlace(name=name, tags=[], source=evidence, location=location)})

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
