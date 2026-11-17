"""Named-city/stop-order integration fixtures for the #76/#77 acceptance cases."""

import json

import fakeredis.aioredis
import httpx
import pytest

from trego_agent.discovery import create_discovery
from trego_agent.handoff import create_handoff
from test_discovery import settings, tool, row
from test_handoff import ApiFixture
from test_osm_feature_evidence import CASTLE
from test_settlement_boundaries import BRATISLAVA, VIENNA
from test_trails_api import identifier, place


@pytest.mark.parametrize("stops,end", [(["Bratislava Castle", "Devín Castle"], "Vienna"),
    (["Bratislava Castle", "Devín Castle", "Devínska Kobyla"], "Stupava"),
    (["Bratislava Castle", "Devín Castle", "Bratislava Castle"], "Vienna")])
@pytest.mark.parametrize("misflagged", [False, True])
async def test_actual_discovery_and_handoff_preserve_cities_explicit_stops_and_repeated_visits(stops, end, misflagged):
    names = list(dict.fromkeys(["Bratislava", *stops, end]))
    # Devín/Kobyla/Stupava below are synthetic transport fixtures, not captured
    # historical provider results or production coordinate overrides.
    rows = {"Bratislava": BRATISLAVA, "Vienna": VIENNA, "Bratislava Castle": CASTLE,
            "Devín Castle": {**row(900000003, "Devín Castle", 48.17, 16.98), "type": "castle"},
            "Devínska Kobyla": {**row(900000004, "Devínska Kobyla", 48.25, 17.0), "type": "peak"},
            "Stupava": {**row(900000005, "Stupava", 48.27, 17.03), "type": "town"}}
    kinds = {"Bratislava": "city", "Vienna": "city", "Bratislava Castle": "castle",
             "Devín Castle": "castle", "Devínska Kobyla": "peak", "Stupava": "town"}
    api, resolutions = ApiFixture(), []
    for index, name in enumerate(names):
        value = rows[name]
        api.rows[value["osm_type"], value["osm_id"]] = place(index + 1, name=name,
            lat=float(value["lat"]), lon=float(value["lon"]), tags=[kinds[name]], source=f"https://evidence.example/{index}")

    def handle(request):
        if request.url.host == "api.example":
            return api(request)
        body = json.loads(request.content) if request.content else {}
        if request.url.host == "api.anthropic.com":
            operation = body["tool_choice"]["name"]
            if operation == "extract_route_intent":
                return tool(operation, {"start": "Bratislava", "end": end, "mustSee": stops,
                    "descriptiveTargets": ["start", *[f"stop:{i}" for i in range(1, len(stops) + 1)], "end"] if misflagged else []})
            target = json.loads(body["messages"][0]["content"])["description"]
            resolutions.append(target)
            return tool(operation, {"place": {"name": target, "sourceIndex": 0, "tags": [kinds[target]],
                "geocodeQuery": target + (", Austria" if target == "Vienna" else ", Slovakia")}})
        if request.url.host == "api.exa.ai":
            target = body["query"].removeprefix("Find information about this exact place: ").split(". Route context:")[0]
            return httpx.Response(200, json={"results": [{"title": target, "url": f"https://evidence.example/{names.index(target)}"}]})
        assert request.url.host == "nominatim.openstreetmap.org"
        return httpx.Response(200, json=[rows[request.url.params["q"].split(",")[0]]])

    config = settings(api_base_url="https://api.example")
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await create_discovery(client, cache, config).discover("fixture named-stop request", [])
        assert result.ready_for_handoff and sorted(resolutions) == sorted(names)
        saved = await create_handoff(client, config).persist(result)
    assert saved.visits == ["Bratislava", *stops, end]
    assert [str(value.id) for value in saved.route.places] == [identifier(names.index(name) + 1) for name in stops]
    assert [value.source for value in saved.places] == [f"https://evidence.example/{i}" for i in range(len(names))]
