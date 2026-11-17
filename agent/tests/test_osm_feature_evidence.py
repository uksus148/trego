"""Reduced public Nominatim observations, 2026-11-15; OSM/ODbL attribution below."""

from copy import deepcopy

import fakeredis.aioredis
import httpx
import pytest

from trego_agent.geocoding import NominatimGeocoder
from trego_agent.geocoding_candidates import GeocodingCandidate, select_candidate_result
from test_geocoding_candidates import LAKE, RESORT, MUNICIPALITY, SKOK, WESTERN_SKOK


# https://www.openstreetmap.org/copyright — Data © OpenStreetMap contributors.
# Fresh public search responses, not the team's private historical model payloads.
CASTLE = {"osm_type": "way", "osm_id": 1128350263, "lat": "48.1425867", "lon": "17.1004695",
          "category": "tourism", "type": "attraction", "name": "Bratislavský hrad",
          "display_name": "Bratislavský hrad, Bratislava, Slovensko",
          "namedetails": {"name:en": "Bratislava Castle"}, "extratags": {"historic": "castle"}}
CATHEDRAL = {"osm_type": "relation", "osm_id": 16609274, "lat": "48.1419772", "lon": "17.1048845",
             "category": "amenity", "type": "place_of_worship", "name": "Katedrála svätého Martina",
             "display_name": "Katedrála svätého Martina, Bratislava, Slovensko",
             "namedetails": {"name:en": "Saint Martin's Cathedral"}, "extratags": {"building": "cathedral", "historic": "church"}}


def select(rows, name, tags):
    return select_candidate_result([GeocodingCandidate.model_validate(row) for row in rows], name, tags, [])


@pytest.mark.parametrize("name", ["Bratislava Castle", "Bratislavský hrad"])
def test_castle_secondary_historic_attribute_passes_without_accepting_generic_attractions(name):
    assert select([CASTLE], name, ["castle"]).location.osm_id == CASTLE["osm_id"]
    assert select([{**CASTLE, "extratags": {}}], name, ["castle"]).reason == "type_mismatch"
    assert select([{**CASTLE, "extratags": {"description": "historic=castle", "historic": "ruins"}}], name, ["castle"]).reason == "type_mismatch"


@pytest.mark.parametrize("name", ["St. Martin's Cathedral", "Saint Martin's Cathedral", "St Martin’s Cathedral", "Katedrála svätého Martina"])
def test_attested_cathedral_alias_accepts_saint_abbreviation_and_apostrophe_variants(name):
    assert select([CATHEDRAL], name, ["cathedral"]).location.osm_id == CATHEDRAL["osm_id"]


def test_religious_type_does_not_accept_other_buildings_or_erase_name_constraints():
    assert select([{**CATHEDRAL, "extratags": {"building": "church"}}], "St. Martin's Cathedral", ["cathedral"]).reason == "type_mismatch"
    assert select([CATHEDRAL], "Saint Peter's Cathedral", ["cathedral"]).reason == "name_mismatch"
    assert select([CATHEDRAL], "St. Martin's Cathedral", ["church"]).reason == "resolved"
    street = {**CATHEDRAL, "name": "Saint Martin", "display_name": "Saint Martin", "namedetails": {}}
    assert select([street], "St Martin", []).reason == "name_mismatch"


def test_conflicting_entity_tags_are_constraints_not_a_broader_union():
    assert select([LAKE, RESORT, MUNICIPALITY], "Štrbské Pleso", []).reason == "ambiguous_candidates"
    assert select([LAKE, RESORT, MUNICIPALITY], "Štrbské Pleso", ["lake"]).location.osm_id == LAKE["osm_id"]
    assert select([LAKE, RESORT, MUNICIPALITY], "Štrbské Pleso", ["resort"]).location.osm_id == RESORT["osm_id"]
    assert select([LAKE, RESORT, MUNICIPALITY], "Štrbské Pleso", ["lake", "resort"]).reason == "type_mismatch"
    assert select([SKOK, WESTERN_SKOK], "Skok", ["waterfall"]).reason == "ambiguous_candidates"


def test_candidate_order_and_duplicate_identity_still_cannot_force_success():
    other = {**CASTLE, "osm_id": 2}
    for rows in ([CASTLE, other], [other, CASTLE]):
        assert select(rows, "Bratislava Castle", ["castle"]).reason == "ambiguous_candidates"
    assert select([CASTLE, {**CASTLE, "lat": 49}], "Bratislava Castle", ["castle"]).reason == "conflicting_identity"


async def test_extra_attributes_are_requested_cached_and_old_options_cannot_mask_them():
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.params["extratags"] == "1" and request.url.params["namedetails"] == "1"
        return httpx.Response(200, json=[CASTLE])

    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        import hashlib, json
        query = "Bratislava Castle, Slovakia"
        old_key = "gopstop:nominatim:search:v2:" + hashlib.sha256(json.dumps([
            "https://nominatim.openstreetmap.org", query, {"format": "jsonv2", "limit": 8, "namedetails": 1}
        ], sort_keys=True).encode()).hexdigest()
        await cache.set(old_key, json.dumps([{**CASTLE, "extratags": {}}]))
        geo = NominatimGeocoder(client, cache, "trego fixture")
        for _ in range(2):
            result = await geo.geocode_result(query, name="Bratislava Castle", tags=["castle"])
            assert result.reason == "resolved"
        assert len(calls) == 1 and await cache.exists(old_key)


def test_null_extra_tags_are_a_valid_empty_osm_attribute_set():
    row = deepcopy(MUNICIPALITY)
    row["extratags"] = None
    assert GeocodingCandidate.model_validate(row).extratags == {}


@pytest.mark.parametrize("provider", ["groq", "anthropic"])
async def test_observed_landmarks_reach_source_bound_handoff_through_actual_factories(provider):
    import json
    from trego_agent.config import Settings
    from trego_agent.discovery import create_discovery
    from trego_agent.handoff import create_handoff
    from test_discovery import tool
    from test_groq import completion
    from test_handoff import ApiFixture
    from test_trails_api import place

    names = ["Bratislava Castle", "St. Martin's Cathedral"]
    rows = [CASTLE, CATHEDRAL]
    kinds = ["castle", "cathedral"]
    sources = [f"https://evidence.example/{index}" for index in range(2)]
    api = ApiFixture()
    for index, row in enumerate(rows):
        api.rows[row["osm_type"], row["osm_id"]] = place(index + 1, name=names[index],
            lat=float(row["lat"]), lon=float(row["lon"]), source=sources[index], tags=[kinds[index]])

    def handle(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.host == "api.example":
            return api(request)
        if request.url.host in ("api.groq.com", "api.anthropic.com"):
            operation = body["response_format"]["json_schema"]["name"] if provider == "groq" else body["tool_choice"]["name"]
            if operation == "extract_route_intent":
                value = {"start": names[0], "end": names[1], "mustSee": [], "preferences": []}
            else:
                payload = json.loads(body["messages"][1 if provider == "groq" else 0]["content"])
                index = names.index(payload["sources"][0]["title"])
                value = {"place": {"name": names[index], "geocodeQuery": names[index] + ", Slovakia",
                                   "sourceIndex": 0, "tags": [kinds[index]]}}
            return httpx.Response(200, json=completion(value=value)) if provider == "groq" else tool(operation, value)
        if request.url.host == "api.exa.ai":
            index = next(i for i, name in enumerate(names) if body["query"].startswith("Find information about this exact place: " + name + "."))
            return httpx.Response(200, json={"results": [{"title": names[index], "url": sources[index]}]})
        assert request.url.host == "nominatim.openstreetmap.org"
        index = names.index(request.url.params["q"].removesuffix(", Slovakia"))
        return httpx.Response(200, json=[rows[index]])

    settings = Settings(_env_file=None, llm_provider=provider, groq_api_key="fixture", anthropic_api_key="fixture",
                        exa_api_key="fixture", api_base_url="https://api.example")
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        finding = await create_discovery(client, cache, settings).discover("Castle to cathedral", [])
        assert finding.ready_for_handoff
        assert [finding.start.place.location.osm_id, finding.end.place.location.osm_id] == [row["osm_id"] for row in rows]
        saved = await create_handoff(client, settings).persist(finding)
        assert saved.visits == names and [p.source for p in saved.places] == sources
    assert [r.method for r in api.calls] == ["POST", "POST", "POST", "GET"]
