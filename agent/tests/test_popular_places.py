"""Popular-places tour: detect the request, bind suggestions to OSM and order west to east."""

import json

import fakeredis.aioredis
import httpx
import pytest

from gopstop_agent.config import Settings
from gopstop_agent.discovery import create_discovery

SIGHTS = {  # name: (osm id, lat, lon)
    "Helsinki Cathedral": (11, 60.1704, 24.9522), "Temppeliaukio Church": (12, 60.1730, 24.9252),
    "Market Square": (13, 60.1675, 24.9536), "Uspenski Cathedral": (14, 60.1684, 24.9601),
    "Sibelius Monument": (15, 60.1821, 24.9133),
}


@pytest.fixture
async def cache():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


def providers(calls, *, area="Helsinki", suggestions=None, intent=None):
    suggestions = list(SIGHTS) if suggestions is None else suggestions

    def tool(name, value):
        return httpx.Response(200, json={"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": name, "input": value}]})

    def handle(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.host == "api.anthropic.com":
            name = body["tool_choice"]["name"]
            calls.append(name)
            if name == "select_reply_language":
                return tool(name, {"language": "en"})
            if name == "extract_route_intent":
                return tool(name, intent or {"start": "Helsinki", "end": None})
            if name == "select_explore_area":
                return tool(name, {"area": area})
            if name == "select_popular_places":
                assert json.loads(body["messages"][0]["content"])["area"] == "Helsinki"
                return tool(name, {"places": [{"name": sight, "sourceIndex": 1} for sight in suggestions]})
            return tool(name, {"place": {"name": "Helsinki", "geocodeQuery": "Helsinki, Finland", "sourceIndex": 0, "tags": ["city"]}})
        if request.url.host == "api.exa.ai":
            calls.append("exa")
            return httpx.Response(200, json={"results": [{"title": "Helsinki", "url": "https://evidence.example/city", "text": "Capital"},
                                                         {"title": "Top sights", "url": "https://evidence.example/top", "text": "Sights"}]})
        if request.url.host == "api.example":
            calls.append("java")
            return httpx.Response(500)
        calls.append("nominatim")
        query = request.url.params["q"]
        if "viewbox" not in request.url.params:
            return httpx.Response(200, json=[{"osm_type": "relation", "osm_id": 1, "category": "boundary", "type": "administrative",
                                              "addresstype": "city", "name": "Helsinki", "display_name": "Helsinki, Suomi", "lat": 60.1699, "lon": 24.9384}])
        if query not in SIGHTS:
            return httpx.Response(200, json=[])
        index, lat, lon = SIGHTS[query]
        return httpx.Response(200, json=[{"osm_type": "way", "osm_id": index, "category": "tourism", "type": "attraction",
                                          "name": query, "display_name": f"{query}, Helsinki, Suomi", "lat": lat, "lon": lon}])
    return handle


async def discover(cache, calls, message="I am in Helsinki, plan a route through the most popular places", **options):
    settings = Settings(_env_file=None, anthropic_api_key="fixture", exa_api_key="fixture", nominatim_user_agent="Trails/1.0")
    async with httpx.AsyncClient(transport=httpx.MockTransport(providers(calls, **options))) as client:
        return await create_discovery(client, cache, settings).discover(message, [])


async def test_tour_runs_from_the_westernmost_to_the_easternmost_sight_with_the_cited_source(cache):
    result = await discover(cache, [], suggestions=[*SIGHTS, "A sight unknown to OSM", "Helsinki Cathedral"])
    assert result.ready_for_handoff
    assert [result.start.place.name, *(stop.place.name for stop in result.stops), result.end.place.name] == [
        "Sibelius Monument", "Temppeliaukio Church", "Helsinki Cathedral", "Market Square", "Uspenski Cathedral"]
    assert result.intent.start == "Sibelius Monument" and result.intent.end == "Uspenski Cathedral"
    assert result.intent.mustSee == ["Temppeliaukio Church", "Helsinki Cathedral", "Market Square"]
    assert {str(finding.place.source.sourceUrl) for finding in [result.start, *result.stops, result.end]} == {"https://evidence.example/top"}


async def test_tour_keeps_at_most_seven_places(cache):
    extra = {f"Sight {index}": (20 + index, 60.17, 24.90 + index / 100) for index in range(5)}
    SIGHTS.update(extra)
    try:
        result = await discover(cache, [])
    finally:
        for name in extra:
            del SIGHTS[name]
    assert result.ready_for_handoff and len(result.stops) == 5


@pytest.mark.parametrize("suggestions", [[], ["Helsinki Cathedral"], ["Unknown one", "Unknown two"]])
async def test_fewer_than_two_located_sights_ask_for_endpoints_instead_of_guessing(cache, suggestions):
    result = await discover(cache, [], suggestions=suggestions)
    assert not result.ready_for_handoff and result.missing_endpoints == ["end"] and result.stops == []


async def test_ordinary_incomplete_request_is_not_a_tour(cache):
    calls = []
    result = await discover(cache, calls, "Hike from Helsinki", area=None)
    assert result.missing_endpoints == ["end"] and calls == ["extract_route_intent", "select_explore_area"]


async def test_complete_route_never_asks_for_tour_detection(cache):
    calls = []
    await discover(cache, calls, "From Helsinki to Turku", intent={"start": "Helsinki", "end": "Turku"})
    assert "select_explore_area" not in calls and "select_popular_places" not in calls


async def test_tour_request_whose_intent_lists_too_many_sights_still_becomes_a_tour(cache):
    calls = []
    many = {"start": None, "end": None, "mustSee": [f"Sight {index}" for index in range(8)]}
    result = await discover(cache, calls, "я сейчас в париже, дай 5-6 мест обязательных для посещения", intent=many)
    assert result.ready_for_handoff and result.start.place.name == "Sibelius Monument"
    assert calls[:2] == ["extract_route_intent", "select_explore_area"]


NAMED = ["Helsinki Cathedral", "Temppeliaukio Church", "Market Square", "Uspenski Cathedral",
         "Sibelius Monument", "Helsinki Cathedral"]


async def test_tour_through_more_sights_than_a_route_allows_keeps_the_ones_the_user_named(cache):
    calls = []
    message = "In Helsinki: Helsinki Cathedral, Temppeliaukio Church, Market Square, Uspenski Cathedral and Sibelius Monument"
    result = await discover(cache, calls, message, intent={"mustSee": NAMED})
    assert result.ready_for_handoff
    assert [result.start.place.name, *(stop.place.name for stop in result.stops), result.end.place.name] == [
        "Sibelius Monument", "Temppeliaukio Church", "Helsinki Cathedral", "Market Square", "Uspenski Cathedral"]
    assert str(result.start.place.source.sourceUrl) == "https://www.openstreetmap.org/way/15"
    assert "select_popular_places" not in calls and calls.count("exa") == 1  # Only the city research.


async def test_a_named_sight_that_cannot_be_found_is_asked_about_instead_of_dropped(cache):
    message = "Helsinki: Helsinki Cathedral, Market Square, Uspenski Cathedral, Sibelius Monument, Kiasma, Temppeliaukio Church"
    named = ["Helsinki Cathedral", "Market Square", "Uspenski Cathedral", "Sibelius Monument", "Kiasma", "Temppeliaukio Church"]
    result = await discover(cache, [], message, intent={"mustSee": named})
    assert not result.ready_for_handoff and result.unresolved == ["Kiasma"]
    assert result.intent.start == "Helsinki Cathedral" and result.intent.end == "Temppeliaukio Church"


async def test_more_named_sights_than_a_tour_holds_still_asks_to_reduce_them(cache):
    from gopstop_agent.intent import IntentClarificationRequired
    named = [f"Sight {index}" for index in range(8)]
    with pytest.raises(IntentClarificationRequired):
        await discover(cache, [], "Helsinki: " + ", ".join(named), intent={"mustSee": named})


async def test_too_many_stops_without_a_tour_still_asks_to_reduce_them(cache):
    from gopstop_agent.intent import IntentClarificationRequired
    many = {"start": "Helsinki", "end": "Turku", "mustSee": [f"Sight {index}" for index in range(8)]}
    with pytest.raises(IntentClarificationRequired):
        await discover(cache, [], "From Helsinki to Turku via eight sights", intent=many, area=None)


async def test_selector_drops_malformed_suggestions_and_asks_again_after_an_empty_list():
    from gopstop_agent.exa import ResearchSource
    from gopstop_agent.popular import PopularPlaceSelector
    replies = [{"places": []}, {"places": [{"name": "The Louvre", "sourceIndex": 0}, {"name": "", "sourceIndex": 0},
                                           {"name": "Bad index", "sourceIndex": 7}, "junk", {"name": "Louvre", "sourceIndex": 0}]}]

    class Model:
        provider = "anthropic"

        async def call(self, body):
            return replies.pop(0)

    source = ResearchSource(title="Paris", sourceUrl="https://evidence.example/p")
    result = await PopularPlaceSelector(Model(), "model").select("Paris", [source])
    assert [place.name for place in result] == ["Louvre"] and not replies


async def test_same_start_and_end_city_is_checked_as_a_tour(cache):
    calls = []
    result = await discover(cache, calls, "я сейчас в Хельсинки, что посмотреть", intent={"start": "Helsinki", "end": "Helsinki"})
    assert result.ready_for_handoff and "select_popular_places" in calls


@pytest.mark.parametrize("intent", [{"start": "Helsinki", "end": "Helsinki"}, {"start": "Helsinki", "end": None}])
@pytest.mark.parametrize("suggestions", [[], ["Helsinki Cathedral"]])
async def test_tour_with_too_few_sights_asks_for_the_destination_over_http_without_writes(intent, suggestions):
    from fastapi.testclient import TestClient
    from gopstop_agent.main import create_app
    calls = []
    settings = Settings(_env_file=None, chat_enabled=True, anthropic_api_key="fixture", exa_api_key="fixture",
                        nominatim_user_agent="Trails/1.0", api_base_url="https://api.example")
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as redis, httpx.AsyncClient(
            transport=httpx.MockTransport(providers(calls, intent=intent, suggestions=suggestions))) as client:
        with TestClient(create_app(settings, redis, client)) as http:
            response = http.post("/api/chat", json={"sessionId": "tour", "message": "I am in Helsinki, show me the sights"})
        assert response.status_code == 200
        assert response.json() == {"reply": "Please specify the destination.", "places": []}
        assert await redis.llen("gopstop:chat-session:tour") == 2
    assert "java" not in calls and "select_popular_places" in calls
