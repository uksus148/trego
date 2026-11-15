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
from gopstop_agent.intent import ClaudeIntentExtractor, Message, ProviderTimeout, RouteIntent
from gopstop_agent.llm import ToolModel, create_tool_model
from gopstop_agent.resolution_cache import CachedPlaceResolver
from gopstop_agent.resolver import ClaudePlaceResolver, SourceResolution


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
                 timeout_seconds: float = 60) -> None:
        self._intent, self._search, self._resolver, self._geocoder = intent, search, resolver, geocoder
        self._timeout_seconds = timeout_seconds

    async def discover(self, message: str, history: list[Message]) -> DiscoveryResult:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                with stage("intent"):
                    intent = await self._intent.extract(message, history)

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
                start = tasks[intent.start].result() if intent.start is not None else None
                stops = [tasks[name].result() for name in intent.mustSee]
                end = tasks[intent.end].result() if intent.end is not None else None
                return DiscoveryResult(intent=intent, start=start, stops=stops, end=end)
        except TimeoutError as exc:
            raise ProviderTimeout("Place discovery exceeded its time limit.", reason="discovery_deadline") from exc


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
        settings.discovery_timeout_seconds,
    )
