"""Reduced public Nominatim records observed 2026-11-15, OSM/ODbL attribution."""

import hashlib
import json
from unittest.mock import AsyncMock

import fakeredis.aioredis
import httpx
import pytest

from gopstop_agent.chat import ChatService
from gopstop_agent.discovery import DiscoveryResult, PlaceFinding
from gopstop_agent.geocoding import NominatimGeocoder, SEARCH_OPTIONS
from gopstop_agent.geocoding_candidates import GeocodingCandidate, select_candidate_result
from gopstop_agent.intent import RouteIntent
from gopstop_agent.localized_replies import FactualReplyWriter


# https://www.openstreetmap.org/copyright — Data © OpenStreetMap contributors.
# Metadata reduced from fresh public searches; IDs/coordinates are fixtures only.
BRATISLAVA = {"osm_type": "relation", "osm_id": 1702499, "lat": "48.1435026", "lon": "17.1082867",
    "category": "boundary", "type": "administrative", "addresstype": "city", "name": "Bratislava",
    "display_name": "Bratislava, Slovensko", "namedetails": {"name:ru": "Братислава"}, "extratags": {"place": "city"}}
VIENNA = {"osm_type": "relation", "osm_id": 109166, "lat": "48.2083537", "lon": "16.3725042",
    "category": "boundary", "type": "administrative", "addresstype": "city", "name": "Wien",
    "display_name": "Wien, Österreich", "namedetails": {"name:en": "Vienna", "name:ru": "Вена"}, "extratags": {}}


def select(rows, name, tags):
    return select_candidate_result([GeocodingCandidate.model_validate(row) for row in rows], name, tags, [])


@pytest.mark.parametrize("row,name", [(BRATISLAVA, "Bratislava"), (BRATISLAVA, "Братислава"), (VIENNA, "Vienna"), (VIENNA, "Вена")])
def test_observed_city_boundaries_pass_name_and_exact_settlement_evidence(row, name):
    assert select([row], name, ["city"]).location.osm_id == row["osm_id"]


@pytest.mark.parametrize("feature", ["city", "town", "village", "hamlet"])
@pytest.mark.parametrize("field", ["addresstype", "place"])
def test_settlement_attribute_sources_are_sufficient_without_accepting_generic_boundaries(feature, field):
    row = {**BRATISLAVA, "addresstype": "", "extratags": {}}
    if field == "place":
        row["extratags"] = {"place": feature}
    else:
        row["addresstype"] = feature
    assert select([row], "Bratislava", [feature]).reason == "resolved"


@pytest.mark.parametrize("changes", [
    {"addresstype": "state", "extratags": {"admin_level": "4"}},
    {"addresstype": "city", "category": "tourism", "type": "attraction", "extratags": {}},
    {"addresstype": "town", "extratags": {}},
    {"addresstype": "city", "extratags": {"place": "village"}},
])
def test_unrelated_or_conflicting_metadata_does_not_become_city_evidence(changes):
    assert select([{**BRATISLAVA, **changes}], "Bratislava", ["city"]).reason == "type_mismatch"


def test_city_rules_preserve_alias_joint_type_and_identity_constraints():
    assert select([BRATISLAVA], "Vienna", ["city"]).reason == "name_mismatch"
    assert select([BRATISLAVA], "Bratislava", ["city", "lake"]).reason == "type_mismatch"
    for rows in ([BRATISLAVA, {**BRATISLAVA, "osm_id": 2}], [{**BRATISLAVA, "osm_id": 2}, BRATISLAVA]):
        assert select(rows, "Bratislava", ["city"]).reason == "ambiguous_candidates"
    assert select([BRATISLAVA, {**BRATISLAVA, "lat": 49}], "Bratislava", ["city"]).reason == "conflicting_identity"


async def test_old_cache_without_address_type_cannot_mask_fresh_city_metadata():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=[VIENNA])

    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        query = "Vienna, Austria"
        digest = hashlib.sha256(json.dumps(["https://nominatim.openstreetmap.org", query, SEARCH_OPTIONS], sort_keys=True).encode()).hexdigest()
        old_key = "gopstop:nominatim:search:v2:" + digest
        await cache.set(old_key, json.dumps([{key: value for key, value in VIENNA.items() if key != "addresstype"}]))
        geo = NominatimGeocoder(client, cache, "trego fixture")
        for _ in range(2):
            assert (await geo.geocode_result(query, name="Vienna", tags=["city"])).reason == "resolved"
        assert len(requests) == 1 and await cache.exists(old_key)
        assert len(await cache.keys("gopstop:nominatim:search:v3:*")) == 1


@pytest.mark.parametrize("language", ["en", "ru", "sk", "fi"])
async def test_inflected_or_translated_unresolved_names_identify_start_and_destination(language):
    search, handoff, selector = AsyncMock(), AsyncMock(), AsyncMock()
    selector.select.return_value = language
    search.discover.return_value = DiscoveryResult(intent=RouteIntent(start="Bratislava", end="Vienna"),
        start=PlaceFinding(description="Bratislava", sources=[]), end=PlaceFinding(description="Vienna", sources=[]))
    reply = await ChatService(search, handoff, FactualReplyWriter(), selector).respond("от братиславы до вены", [])
    expected = {"en": ("the start", "the destination"), "ru": ("начальную точку", "конечную точку"),
                "sk": ("začiatočný bod", "cieľový bod"), "fi": ("lähtöpiste", "määränpää")}[language]
    assert all(label in reply.reply for label in expected)
    assert "Bratislava" not in reply.reply and "Vienna" not in reply.reply and not reply.places and reply.routeId is None
    handoff.persist.assert_not_awaited()


async def test_repeated_unresolved_stops_keep_their_positions_without_echoing_synthetic_names():
    result = DiscoveryResult(intent=RouteIntent(start="A", end="B"), stops=[PlaceFinding(description="synthetic", sources=[])] * 2)
    reply = await FactualReplyWriter().write("a Russian user sentence", [], "clarification", {
        "unresolvedPlaces": result.unresolved, "unresolvedTargets": result.unresolved_targets}, language="ru")
    assert "№1" in reply and "№2" in reply and "synthetic" not in reply


@pytest.mark.parametrize("provider,model", [("groq", "openai/gpt-oss-20b"), ("groq", "openai/gpt-oss-120b"), ("anthropic", "fixture")])
async def test_city_endpoints_reach_complete_discovery_without_relaxing_source_binding(provider, model):
    from gopstop_agent.config import Settings
    from gopstop_agent.discovery import create_discovery
    from gopstop_agent.resolution_cache import ResolutionEntry
    from test_discovery import tool
    from test_groq import completion

    rows, names, countries = [BRATISLAVA, VIENNA], ["Bratislava", "Vienna"], ["Slovakia", "Austria"]

    def handle(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.host in ("api.groq.com", "api.anthropic.com"):
            operation = body["response_format"]["json_schema"]["name"] if provider == "groq" else body["tool_choice"]["name"]
            if operation == "extract_route_intent":
                value = {"start": names[0], "end": names[1], "mustSee": [], "preferences": []}
            else:
                payload = json.loads(body["messages"][1 if provider == "groq" else 0]["content"])
                index = names.index(payload["sources"][0]["title"])
                value = {"place": {"name": names[index], "geocodeQuery": f"{names[index]}, {countries[index]}", "sourceIndex": 0, "tags": ["city"]}}
            return httpx.Response(200, json=completion(value=value)) if provider == "groq" else tool(operation, value)
        if request.url.host == "api.exa.ai":
            index = next(i for i, name in enumerate(names) if body["query"].startswith(f"Find information about this exact place: {name}."))
            return httpx.Response(200, json={"results": [{"title": names[index], "url": f"https://evidence.example/{index}"}]})
        assert request.url.host == "nominatim.openstreetmap.org"
        index = next(i for i, name in enumerate(names) if request.url.params["q"].startswith(name + ","))
        return httpx.Response(200, json=[rows[index]])

    settings = Settings(_env_file=None, llm_provider=provider, groq_model=model if provider == "groq" else "openai/gpt-oss-20b",
                        anthropic_model=model, groq_api_key="fixture", anthropic_api_key="fixture", exa_api_key="fixture")
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        finding = await create_discovery(client, cache, settings).discover("от братиславы до вены", [])
        assert finding.ready_for_handoff
        for index, target in enumerate([finding.start, finding.end]):
            assert target.place.location.osm_id == rows[index]["osm_id"]
            assert str(target.place.source.sourceUrl) == f"https://evidence.example/{index}"
        keys = await cache.keys("gopstop:place-resolution:v3:*")
        assert len(keys) == 2
        for key in keys:
            assert ResolutionEntry.model_validate_json(await cache.get(key)).accepted
