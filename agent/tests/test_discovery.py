import asyncio
import json
from unittest.mock import AsyncMock

import fakeredis.aioredis
import httpx
import pytest

from gopstop_agent.config import Settings
from gopstop_agent.chat import ChatService
from gopstop_agent.discovery import DiscoveryResult, PlaceDiscovery, create_discovery
from gopstop_agent.intent import IntentClarificationRequired, ProviderError, RouteIntent
from gopstop_agent.localized_replies import FactualReplyWriter
from gopstop_agent.resolution_cache import ResolutionEntry


def settings(**overrides):
    return Settings(_env_file=None, anthropic_api_key="fixture-claude", exa_api_key="fixture-exa",
                    nominatim_user_agent="TrailsTest/1.0 team@example.org", **overrides)


def tool(name, value):
    return httpx.Response(200, json={"stop_reason": "tool_use", "content": [{
        "type": "tool_use", "name": name, "input": value,
    }]})


def row(index, name, lat, lon):
    return {"osm_type": "node", "osm_id": index, "display_name": name, "lat": lat, "lon": lon}


def provider_fixture(intent, places, calls, region="High Tatras, Slovakia"):
    def handle(request):
        calls.append(request)
        body = json.loads(request.content) if request.content else {}
        if request.url.host == "api.anthropic.com":
            if body["tool_choice"]["name"] == "select_reply_language":
                message = json.loads(body["messages"][0]["content"])["message"]
                return tool("select_reply_language", {"language": "ru" if any(c in message for c in "ХО") else "en"})
            if body["tool_choice"]["name"] == "extract_route_intent":
                return tool("extract_route_intent", intent)
            if body["tool_choice"]["name"] == "select_explore_area":
                return tool("select_explore_area", {"area": None})
            evidence = json.loads(body["messages"][0]["content"])
            name = evidence["sources"][0]["title"]
            return tool("resolve_place", {"place": {
                "name": name, "geocodeQuery": f"{name}, {region}", "sourceIndex": 0, "tags": [],
            }})
        if request.url.host == "api.exa.ai":
            description = body["query"].removeprefix("Find information about this exact place: ").split(". Route context:")[0]
            index = list(places).index(description)
            name, _ = places[description]
            return httpx.Response(200, json={"results": [
                {"url": "ftp://invalid.example/"},
                {"title": name, "url": f"https://evidence.example/{index}", "text": f"Located in {region}"},
            ]})
        assert request.url.host == "nominatim.openstreetmap.org"
        assert request.headers["User-Agent"] == "TrailsTest/1.0 team@example.org"
        name = request.url.params["q"].removesuffix(f", {region}")
        rows = next((rows for title, rows in places.values() if title == name), [])
        return httpx.Response(200, json=rows)
    return handle


@pytest.fixture
async def cache():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


async def test_unbound_description_clarifies_without_handoff_or_positive_cache_acceptance(cache):
    description = "the waterfall from TikTok near Štrbské Pleso"
    intent = {"start": "Štrbské Pleso", "end": "Rysy", "mustSee": [description],
              "preferences": ["wild scenery"], "descriptiveTargets": ["stop:1"]}
    places = {
        "Štrbské Pleso": ("Štrbské Pleso", [row(1, "Štrbské Pleso", 49.1191, 20.0627)]),
        description: ("Skok waterfall", [row(2, "Skok waterfall", 49.1425, 20.0506)]),
        "Rysy": ("Rysy", [row(3, "Rysy", 49.1795, 20.088)]),
    }
    calls = []
    history = [{"role": "user", "content": "Hike from Štrbské Pleso to Rysy"},
               {"role": "assistant", "content": "Any places to see?"}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider_fixture(intent, places, calls))) as client:
        discovery = create_discovery(client, cache, settings())
        for _ in range(2):
            result = await discovery.discover("Via the waterfall, I love wild scenery", history)
            assert not result.ready_for_handoff and result.stops[0].place is None
            assert result.stops[0].reason == "requested_identity_mismatch"
            assert str(result.stops[0].sources[0].sourceUrl) == "https://evidence.example/1"
            assert result.start.place.name == "Štrbské Pleso" and result.end.place.name == "Rysy"
            assert result.intent.preferences == ["wild scenery"]
            assert result.unresolved == [description] and "OpenStreetMap" in result.attribution
        research, handoff, language = AsyncMock(), AsyncMock(), AsyncMock()
        research.discover.return_value, language.select.return_value = result, "en"
        response = await ChatService(research, handoff, FactualReplyWriter(), language).respond("Via the waterfall", history)
        assert not response.places and response.routeId is None
        handoff.persist.assert_not_awaited()
        key = discovery._resolver._key(description, result.stops[0].sources)
        assert not ResolutionEntry.model_validate_json(await cache.get(key)).accepted
        assert 0 < await cache.ttl(key) <= 300
    assert sum(r.url.host == "api.exa.ai" for r in calls) == 3
    assert sum(r.url.host == "nominatim.openstreetmap.org" for r in calls) == 4
    resolution = [r for r in calls if r.url.host == "api.anthropic.com"
                  and json.loads(r.content)["tool_choice"]["name"] == "resolve_place"]
    assert len(resolution) == 3  # Three cold resolutions, none on the repeated discovery.
    extraction = [json.loads(r.content) for r in calls if r.url.host == "api.anthropic.com"
                  and json.loads(r.content)["tool_choice"]["name"] == "extract_route_intent"]
    assert all(body["messages"][:-1] == history for body in extraction)


@pytest.mark.parametrize("repeats", [1, 2])
async def test_misclassified_named_stops_cannot_accept_a_city_substitute(cache, repeats):
    target = "Bratislava Castle"
    intent = {"start": "Fixture Start", "end": "Fixture End", "mustSee": [target] * repeats,
              "descriptiveTargets": ["start", "end", *[f"stop:{i}" for i in range(1, repeats + 1)]]}
    places = {"Fixture Start": ("Fixture Start", [row(1, "Fixture Start", 49, 20)]),
              target: ("Bratislava", [row(2, "Bratislava", 48.14, 17.11)]),
              "Fixture End": ("Fixture End", [row(3, "Fixture End", 49.2, 20.2)])}
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider_fixture(intent, places, []))) as client:
        discovery = create_discovery(client, cache, settings())
        result = await discovery.discover("Visit Bratislava Castle", [])
        assert not result.ready_for_handoff and len(result.stops) == repeats
        assert all(stop.place is None and stop.reason == "requested_identity_mismatch" for stop in result.stops)
        key = discovery._resolver._key(target, result.stops[0].sources)
        assert not ResolutionEntry.model_validate_json(await cache.get(key)).accepted
        assert 0 < await cache.ttl(key) <= 300
        research, handoff, language = AsyncMock(), AsyncMock(), AsyncMock()
        research.discover.return_value, language.select.return_value = result, "en"
        response = await ChatService(research, handoff, FactualReplyWriter(), language).respond("Visit Bratislava Castle", [])
        assert response.routeId is None and not response.places
        handoff.persist.assert_not_awaited()


async def test_other_regions_ambiguity_and_missing_endpoints_keep_evidence_for_clarification(cache):
    intent = {"start": "Tromsø", "mustSee": ["a nearby castle"], "end": None}
    places = {
        "Tromsø": ("Tromsø", [row(1, "Tromsø", 69.65, 18.96)]),
        "a nearby castle": ("Castle", [row(2, "Castle", 69.66, 18.97), row(3, "Castle", 69.67, 18.98)]),
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider_fixture(intent, places, [], "Norway"))) as client:
        result = await create_discovery(client, cache, settings()).discover("Hike near Tromsø", [])
    assert not result.ready_for_handoff
    assert result.unresolved == [] and result.missing_endpoints == ["end"]
    assert result.stops == []  # No research before endpoint clarification.


async def test_duplicate_targets_reuse_research_without_losing_requested_visit_order(cache):
    intent = {"start": "Skok", "end": "Skok", "mustSee": ["Skok", "Skok"]}
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider_fixture(
        intent, {"Skok": ("Skok", [row(2, "Skok", 49.1425, 20.0506)])}, calls,
    ))) as client:
        result = await create_discovery(client, cache, settings()).discover("Return to Skok", [])
    assert result.ready_for_handoff and len(result.stops) == 2
    assert result.start.place == result.end.place == result.stops[0].place
    assert len(calls) == 4  # Intent, Exa, source resolution, geocoding.


async def test_excess_stops_propagate_clarification_before_research(cache):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "api.anthropic.com"
        return tool("extract_route_intent", {"mustSee": [f"stop {i}" for i in range(6)]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(IntentClarificationRequired):
            await create_discovery(client, cache, settings()).discover("Six stops, please", [])
    assert len(calls) == 1


async def test_whole_discovery_deadline_cancels_work_before_any_research():
    stopped = asyncio.Event()

    async def stall(*_):
        try:
            await asyncio.sleep(10)
        finally:
            stopped.set()

    intent, search = AsyncMock(), AsyncMock()
    intent.extract.side_effect = stall
    discovery = PlaceDiscovery(intent, search, AsyncMock(), AsyncMock(), timeout_seconds=0.01)
    with pytest.raises(ProviderError, match="time limit"):
        await discovery.discover("Find a waterfall", [])
    assert stopped.is_set()
    search.search.assert_not_awaited()


async def test_factory_requires_live_keys_and_empty_results_are_not_ready(cache):
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="requires the selected LLM key"):
            create_discovery(client, cache, Settings(_env_file=None, anthropic_api_key="", exa_api_key=""))
    assert not DiscoveryResult(intent=RouteIntent(start="A", end="B")).ready_for_handoff
