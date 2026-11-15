"""Issue #76: a source-led attraction must not replace a requested settlement."""

import json
from unittest.mock import AsyncMock

import fakeredis.aioredis
import httpx
import pytest

from gopstop_agent.chat import ChatService
from gopstop_agent.config import Settings
from gopstop_agent.discovery import create_discovery
from gopstop_agent.exa import ResearchSource
from gopstop_agent.geocoding import NominatimGeocoder
from gopstop_agent.localized_replies import FactualReplyWriter
from gopstop_agent.resolution_cache import ResolutionEntry
from gopstop_agent.resolver import SourceResolution
from test_discovery import tool
from test_groq import completion
from test_osm_feature_evidence import CASTLE
from test_settlement_boundaries import BRATISLAVA, VIENNA


# Reduced public Nominatim observations, 2026-11-15. Data © OpenStreetMap
# contributors / ODbL: https://www.openstreetmap.org/copyright.
KAHLENBERG = {"osm_type": "node", "osm_id": 195763017, "name": "Kahlenberg", "type": "peak",
              "lat": 48.2763418, "lon": 16.3330680, "display_name": "Kahlenberg, Wien, 1190, Österreich"}
OTHER_KAHLENBERG = {**KAHLENBERG, "osm_id": 12962364097, "lat": 48.2282682, "lon": 15.4749161,
                   "display_name": "Kahlenberg, Hafnerbach, Bezirk St. Pölten, Österreich"}
STEPHANSDOM = {"osm_type": "way", "osm_id": 212496461, "name": "Stephansdom", "type": "place_of_worship",
               "lat": 48.2084923, "lon": 16.3731269, "display_name": "Stephansdom, Wien, Österreich",
               "extratags": {"building": "cathedral"}}


@pytest.mark.parametrize("provider,model", [("groq", "openai/gpt-oss-20b"), ("groq", "openai/gpt-oss-120b"), ("anthropic", "fixture")])
@pytest.mark.parametrize("substitute,verification", [(None, "city"), ("peak", "city"), ("cathedral", "city"),
    ("cathedral", "empty"), ("cathedral", "unrelated"), ("cathedral", "attraction")])
async def test_actual_discovery_checks_requested_cities_before_acceptance_or_writes(provider, model, substitute, verification):
    calls = []
    names = ["Bratislava", "Vienna"]
    resolved = ["Bratislava Castle", "Kahlenberg"] if substitute == "peak" else ["Bratislava", "Stephansdom"] if substitute else names
    kinds = ["castle", "peak"] if substitute == "peak" else ["city", "cathedral"] if substitute else ["city", "city"]

    def handle(request):
        calls.append(request)
        body = json.loads(request.content) if request.content else {}
        if request.url.host in {"api.groq.com", "api.anthropic.com"}:
            operation = body["response_format"]["json_schema"]["name"] if provider == "groq" else body["tool_choice"]["name"]
            if operation == "extract_route_intent":
                value = {"start": names[0], "end": names[1], "mustSee": [], "preferences": []}
            else:
                payload = json.loads(body["messages"][1 if provider == "groq" else 0]["content"])
                # The resolution input is ONLY this requested target, not the
                # route-wide search string or the other endpoint's name.
                index = names.index(payload["description"])
                assert payload["sources"][0]["title"] == names[index]
                value = {"place": {"name": resolved[index], "geocodeQuery": f"{resolved[index]}, {'Slovakia' if index == 0 else 'Austria'}",
                                   "tags": [kinds[index]], "sourceIndex": 0}}
            return httpx.Response(200, json=completion(value=value)) if provider == "groq" else tool(operation, value)
        if request.url.host == "api.exa.ai":
            target = body["query"].removeprefix("Find information about this exact place: ").split(". Route context:")[0]
            return httpx.Response(200, json={"results": [{"title": target, "url": f"https://evidence.example/{names.index(target)}"}]})
        assert request.url.host == "nominatim.openstreetmap.org"  # No API/ORS/session writes.
        query = request.url.params["q"].split(",")[0]
        if request.url.params["q"] == "Vienna" and verification != "city":
            # Synthetic unusable verification responses: even a matching label
            # on a cathedral is not city evidence.
            values = {"empty": [], "unrelated": [BRATISLAVA],
                      "attraction": [{**STEPHANSDOM, "name": "Vienna", "display_name": "Vienna"}]}
            return httpx.Response(200, json=values[verification])
        rows = {"Bratislava": [BRATISLAVA], "Vienna": [VIENNA], "Bratislava Castle": [CASTLE],
                "Kahlenberg": [KAHLENBERG, OTHER_KAHLENBERG], "Stephansdom": [STEPHANSDOM]}
        return httpx.Response(200, json=rows[query])

    settings = Settings(_env_file=None, llm_provider=provider, groq_model=model if provider == "groq" else "openai/gpt-oss-20b",
                        anthropic_model=model, groq_api_key="fixture", anthropic_api_key="fixture", exa_api_key="fixture")
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        discovery_service = create_discovery(client, cache, settings)
        stale_key = None
        if verification == "attraction":
            # A previously accepted substitute must be demoted, not reused for a day.
            evidence = [ResearchSource(title="Vienna", sourceUrl="https://evidence.example/1")]
            stale_key = discovery_service._resolver._key("Vienna", evidence)
            stale = SourceResolution(name="Stephansdom", geocodeQuery="Stephansdom, Austria", sourceIndex=0, tags=["cathedral"])
            await cache.set(stale_key, ResolutionEntry(place=stale, accepted=True).model_dump_json(), ex=86400)
        finding = await discovery_service.discover("Hike from Bratislava to Vienna.", [])
        assert finding.ready_for_handoff == (substitute is None)
        assert finding.intent.start == "Bratislava" and finding.intent.end == "Vienna"
        if substitute:
            assert finding.start.reason == ("requested_identity_mismatch" if substitute == "peak" else "resolved")
            assert finding.end.reason == "requested_identity_mismatch"
            assert {m.osmId for m in finding.end.selection.requestedMatches} == ({109166} if verification == "city" else set())
            assert {m.osmId for m in finding.end.selection.matches} == ({195763017, 12962364097} if substitute == "peak" else {212496461})
            discovery, handoff, language = AsyncMock(), AsyncMock(), AsyncMock()
            discovery.discover.return_value = finding
            language.select.return_value = "en"
            response = await ChatService(discovery, handoff, FactualReplyWriter(), language).respond(
                "Hike from Bratislava to Vienna.", [])
            assert not response.places and response.routeId is None
            handoff.persist.assert_not_awaited()
        else:
            for index, point in enumerate([finding.start, finding.end]):
                assert point.place.location.osm_id == [1702499, 109166][index]
                assert str(point.place.source.sourceUrl) == f"https://evidence.example/{index}"
        entries = [ResolutionEntry.model_validate_json(await cache.get(k)) for k in await cache.keys("gopstop:place-resolution:v3:*")]
        assert len(entries) == 2
        assert sum(entry.accepted for entry in entries) == (0 if substitute == "peak" else 1 if substitute else 2)
        if stale_key:
            assert 0 < await cache.ttl(stale_key) <= 300
        assert sum(r.url.host in {"api.groq.com", "api.anthropic.com"} for r in calls) == (2 if stale_key else 3)
        assert sum(r.url.host == "nominatim.openstreetmap.org" for r in calls) == (4 if substitute == "peak" else 3 if substitute else 2)


@pytest.mark.parametrize("name,query", [("Bratislava Castle", "Bratislava Castle, Slovakia"),
                                        ("Bratislava", "Bratislava Castle, Slovakia")])
@pytest.mark.parametrize("shared_alias", [False, True])
async def test_preserving_only_the_city_label_cannot_hide_an_attraction_query(name, query, shared_alias):
    castle = {**CASTLE, "namedetails": {**CASTLE["namedetails"], **({"alt_name": "Bratislava"} if shared_alias else {})}}
    def handle(request):
        return httpx.Response(200, json=[BRATISLAVA] if request.url.params["q"] == "Bratislava" else [castle])
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await NominatimGeocoder(client, cache, "trego fixture").geocode_result(
            query, name=name, tags=["castle"], requested_name="Bratislava")
    assert result.reason == "requested_identity_mismatch" and result.location is None


async def test_translated_city_alias_reuses_candidates_without_verification_request():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=[VIENNA])
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await NominatimGeocoder(client, cache, "trego fixture").geocode_result(
            "Wien, Austria", name="Wien", tags=["city"], requested_name="Vienna, Austria")
    assert result.location.osm_id == 109166 and len(calls) == 1


@pytest.mark.parametrize("requested,resolved,row,tags", [("Bratislava Castle", "Bratislavský hrad", CASTLE, ["castle"]),
    ("Skok waterfall", "Vodopád Skok", {"osm_type": "node", "osm_id": 383862401, "name": "Vodopád Skok",
       "display_name": "Vodopád Skok, Slovakia", "lat": 49.153124, "lon": 20.0452686, "type": "waterfall"}, ["waterfall"])])
async def test_explicit_requested_feature_binds_translated_name_to_the_same_osm_identity(requested, resolved, row, tags):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=[row])
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await NominatimGeocoder(client, cache, "trego fixture").geocode_result(
            resolved + ", Slovakia", name=resolved, tags=tags, requested_name=requested)
    assert result.location.osm_id == row["osm_id"] and len(calls) == 1


async def test_verification_provider_failure_remains_an_error_without_retry():
    from gopstop_agent.intent import ProviderError
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(503) if request.url.params["q"] == "Bratislava" else httpx.Response(200, json=[CASTLE])
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError):
            await NominatimGeocoder(client, cache, "trego fixture").geocode_result(
                "Bratislava Castle, Slovakia", name="Bratislava Castle", tags=["castle"], requested_name="Bratislava")
    assert len(calls) == 2


async def test_review_blocker_empty_bratislava_verification_does_not_authorize_the_castle():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=[] if request.url.params["q"] == "Bratislava" else [CASTLE])
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await NominatimGeocoder(client, cache, "trego fixture").geocode_result(
            "Bratislava Castle, Slovakia", name="Bratislava Castle", tags=["castle"], requested_name="Bratislava")
    assert result.reason == "requested_identity_mismatch" and result.location is None
    assert not result.requestedMatches and len(calls) == 2
