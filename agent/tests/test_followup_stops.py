"""Follow-up stops: stale failed stops are not carried over; exact names near the route resolve via OSM."""

import json

import fakeredis.aioredis
import httpx
import pytest

from gopstop_agent.config import Settings
from gopstop_agent.discovery import create_discovery
from gopstop_agent.geocoding import NominatimGeocoder
from gopstop_agent.geocoding_models import GeocodedPlace
from gopstop_agent.intent import ClaudeIntentExtractor, RouteIntent, drop_stale_stops

DEMO = "Plan a summer hike in July from Štrbské Pleso to Popradské pleso via the Skok waterfall. I love wild scenery."
READY = "Your route is ready: Štrbské Pleso → Skok Waterfall → Popradské pleso. Distance 15.2 km; ascent 746 m; duration 5 h 02 min."
FAILED = [{"role": "user", "content": DEMO}, {"role": "assistant", "content": READY},
          {"role": "user", "content": "add stop at Turisticka ubytovna"},
          {"role": "assistant", "content": "Please provide a more precise name or location for: Turisticka ubytovna."}]
HOSTEL = {"osm_type": "way", "osm_id": 151515296, "category": "tourism", "type": "hostel", "name": "Turistická ubytovňa",
          "display_name": "Turistická ubytovňa, Limbová, Štrbské pleso, Slovakia", "lat": "49.1196", "lon": "20.0678"}
FAR_HOSTEL = {**HOSTEL, "osm_id": 58777443, "display_name": "Turistická ubytovňa, Červený Kláštor, Slovakia",
              "lat": "49.3936", "lon": "20.4117"}
ANCHOR = GeocodedPlace(osm_type="way", osm_id=1, display_name="Štrbské Pleso", lat=49.1191, lon=20.0627)


def intent(stops, **extra):
    return RouteIntent.model_validate({"start": "Štrbské Pleso", "end": "Popradské pleso", "mustSee": stops,
                                       "preferences": ["wild scenery"], **extra})


@pytest.fixture
async def cache():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


def test_complete_new_request_drops_a_stop_named_only_in_an_earlier_failed_follow_up():
    carried = intent(["Skok waterfall", "Turisticka ubytovna"], descriptiveTargets=["stop:2"])
    result = drop_stale_stops(carried, DEMO, FAILED)
    assert result.mustSee == ["Skok waterfall"] and result.descriptiveTargets == []
    assert carried.mustSee == ["Skok waterfall", "Turisticka ubytovna"]


def test_descriptive_roles_follow_their_stops_when_an_earlier_stop_is_dropped():
    carried = intent(["Turisticka ubytovna", "Skok waterfall"], descriptiveTargets=["start", "stop:2"])
    assert drop_stale_stops(carried, DEMO, FAILED).descriptiveTargets == ["start", "stop:1"]


@pytest.mark.parametrize("message, history, stops", [
    # A follow-up without endpoints still builds on the conversation.
    ("add stop at Turisticka ubytovna", FAILED[:2], ["Skok waterfall", "Turisticka ubytovna"]),
    ("it is the hostel on Limbová street", FAILED, ["Skok waterfall", "Turisticka ubytovna"]),
    # A stop of an already built route is retained when endpoints are repeated.
    ("From Štrbské Pleso to Popradské pleso, also add Turisticka ubytovna", FAILED[:2],
     ["Skok waterfall", "Turisticka ubytovna"]),
    ("From Štrbské Pleso to Popradské pleso with a lunch break", FAILED[:2], ["Skok waterfall"]),
    # Names the model normalized, never typed by the user, are not judged stale.
    (DEMO, FAILED, ["Vodopád Skok"]),
])
def test_other_requests_keep_their_stops(message, history, stops):
    assert drop_stale_stops(intent(stops), message, history).mustSee == stops


async def test_extractor_applies_the_stale_stop_guard_to_model_output():
    reply = {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "extract_route_intent", "input": {
        "start": "Štrbské Pleso", "end": "Popradské pleso", "mustSee": ["Skok waterfall", "Turisticka ubytovna"]}}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply))) as client:
        result = await ClaudeIntentExtractor(client, "fixture", "model").extract(DEMO, FAILED)
    assert result.mustSee == ["Skok waterfall"]


async def test_nearby_lookup_selects_the_only_exact_name_within_route_context(cache):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=[HOSTEL, FAR_HOSTEL, {**HOSTEL, "osm_id": 9, "name": "Turistická ubytovňa Tatry",
                                                               "display_name": "Turistická ubytovňa Tatry, Slovakia"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        geocoder = NominatimGeocoder(client, cache, "Trails/1.0")
        first = await geocoder.geocode_nearby("Turisticka ubytovna", [ANCHOR])
        assert await geocoder.geocode_nearby("Turisticka ubytovna", [ANCHOR]) == first
        assert (await geocoder.geocode_nearby("Turisticka ubytovna", [])).location is None
    assert first.reason == "resolved" and first.location.osm_id == 151515296
    assert len(calls) == 1 and calls[0].url.params["bounded"] == "1"
    west, north, east, south = map(float, calls[0].url.params["viewbox"].split(","))
    assert west < 20.0627 < east and south < 49.1191 < north and north - south < 1


async def test_nearby_lookup_never_picks_between_several_local_matches(cache):
    rows = [HOSTEL, {**HOSTEL, "osm_id": 7, "lat": "49.13"}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as client:
        result = await NominatimGeocoder(client, cache, "Trails/1.0").geocode_nearby("Turisticka ubytovna", [ANCHOR])
    assert result.reason == "ambiguous_candidates" and result.location is None


def square(osm_type, osm_id, category, kind, lat, lon, address="Innere Stadt, Wien, Österreich"):
    return {"osm_type": osm_type, "osm_id": osm_id, "category": category, "type": kind, "name": "Heldenplatz",
            "display_name": f"Heldenplatz, {address}", "lat": lat, "lon": lon}


VIENNA = GeocodedPlace(osm_type="relation", osm_id=109166, display_name="Wien, Österreich", lat=48.2084, lon=16.3725)
HELDENPLATZ = [square("way", 264828970, "amenity", "parking", "48.2057", "16.3645"),
               square("way", 29065206, "highway", "service", "48.2071", "16.3622"),
               square("node", 276645373, "place", "square", "48.2060", "16.3640"),
               square("way", 92840523, "place", "square", "48.1205", "16.2642", "Perchtoldsdorf, Niederösterreich, Österreich")]


async def test_nearby_lookup_skips_road_and_parking_objects_and_prefers_the_address_inside_a_route_place(cache):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=HELDENPLATZ))) as client:
        result = await NominatimGeocoder(client, cache, "Trails/1.0").geocode_nearby("Heldenplatz", [VIENNA])
    assert result.reason == "resolved" and (result.location.osm_type, result.location.osm_id) == ("node", 276645373)


def hostel(osm_id, lat, **extra):
    return {"osm_type": "way", "osm_id": osm_id, "category": "tourism", "type": "hostel", "name": "Tourist Hostel",
            "display_name": "Tourist Hostel, Example City, Slovakia", "lat": lat, "lon": "17.0", **extra}


EXAMPLE_CITY = GeocodedPlace(osm_type="relation", osm_id=1000, display_name="Example City, Slovakia", lat=48.0005, lon=17.0)


async def test_nearby_lookup_keeps_close_same_named_establishments_ambiguous(cache):
    rows = [hostel(1, "48.000"), hostel(2, "48.001")]  # About 110 m apart, same city and type.
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as client:
        result = await NominatimGeocoder(client, cache, "Trails/1.0").geocode_nearby("Tourist Hostel", [EXAMPLE_CITY])
    assert result.reason == "ambiguous_candidates" and result.location is None and result.identityCount == 2


async def test_nearby_lookup_merges_objects_only_when_they_share_a_wikidata_item(cache):
    rows = [hostel(1, "48.000", extratags={"wikidata": "Q42"}), hostel(2, "48.001", extratags={"wikidata": "Q42"})]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as client:
        result = await NominatimGeocoder(client, cache, "Trails/1.0").geocode_nearby("Tourist Hostel", [EXAMPLE_CITY])
    assert result.reason == "resolved" and result.location.osm_id == 1


async def test_nearby_lookup_stays_ambiguous_when_no_address_names_a_route_place(cache):
    rows = [{**row, "display_name": "Heldenplatz, Somewhere"} for row in HELDENPLATZ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as client:
        result = await NominatimGeocoder(client, cache, "Trails/1.0").geocode_nearby("Heldenplatz", [VIENNA])
    assert result.reason == "ambiguous_candidates" and result.identityCount == 2


def providers(nearby_rows, calls):
    names = {"Štrbské Pleso": (1, 49.1191, 20.0627), "Popradské pleso": (3, 49.1533, 20.0797)}

    def tool(name, value):
        return httpx.Response(200, json={"stop_reason": "tool_use", "content": [
            {"type": "tool_use", "name": name, "input": value}]})

    def handle(request):
        calls.append(request)
        body = json.loads(request.content) if request.content else {}
        if request.url.host == "api.anthropic.com":
            if body["tool_choice"]["name"] == "extract_route_intent":
                return tool("extract_route_intent", {"start": "Štrbské Pleso", "end": "Popradské pleso",
                                                     "mustSee": ["Turisticka ubytovna"]})
            description = json.loads(body["messages"][0]["content"])["description"]
            return tool("resolve_place", {"place": {"name": description, "geocodeQuery": f"{description}, Slovakia",
                                                    "sourceIndex": 0, "tags": []} if description in names else None})
        if request.url.host == "api.exa.ai":
            return httpx.Response(200, json={"results": [{"title": "Hostels", "url": "https://evidence.example/h", "text": "Many"}]})
        if "viewbox" in request.url.params:
            return httpx.Response(200, json=nearby_rows)
        name = request.url.params["q"].removesuffix(", Slovakia")
        index, lat, lon = names[name]
        return httpx.Response(200, json=[{"osm_type": "node", "osm_id": index, "display_name": name, "lat": lat, "lon": lon}])
    return handle


async def test_discovery_resolves_an_unevidenced_exact_name_near_the_route_with_osm_as_source(cache):
    calls = []
    settings = Settings(_env_file=None, anthropic_api_key="fixture", exa_api_key="fixture", nominatim_user_agent="Trails/1.0")
    async with httpx.AsyncClient(transport=httpx.MockTransport(providers([HOSTEL, FAR_HOSTEL], calls))) as client:
        result = await create_discovery(client, cache, settings).discover("add stop at Turisticka ubytovna", FAILED[:2])
    place = result.stops[0].place
    assert result.ready_for_handoff and place.name == "Turistická ubytovňa"
    assert str(place.source.sourceUrl) == "https://www.openstreetmap.org/way/151515296"
    assert (place.location.osm_type, place.location.osm_id) == ("way", 151515296)


async def test_discovery_still_clarifies_when_the_nearby_name_is_ambiguous(cache):
    calls = []
    settings = Settings(_env_file=None, anthropic_api_key="fixture", exa_api_key="fixture", nominatim_user_agent="Trails/1.0")
    rows = [HOSTEL, {**HOSTEL, "osm_id": 7, "lat": "49.13"}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(providers(rows, calls))) as client:
        result = await create_discovery(client, cache, settings).discover("add stop at Turisticka ubytovna", FAILED[:2])
    assert not result.ready_for_handoff and result.unresolved == ["Turisticka ubytovna"]
    assert result.stops[0].reason == "insufficient_evidence"


async def test_discovery_uses_the_nearby_lookup_after_a_type_mismatch_without_promoting_the_resolution(cache):
    calls = []
    names = {"Bratislava": (1702499, 48.1435, 17.1090, "Bratislava, Slovensko"), "Vienna": (109166, 48.2084, 16.3725, "Wien, Österreich")}

    def tool(name, value):
        return httpx.Response(200, json={"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": name, "input": value}]})

    def handle(request):
        calls.append(request)
        body = json.loads(request.content) if request.content else {}
        if request.url.host == "api.anthropic.com":
            if body["tool_choice"]["name"] == "extract_route_intent":
                return tool("extract_route_intent", {"start": "Bratislava", "end": "Vienna", "mustSee": ["Heldenplatz"]})
            description = json.loads(body["messages"][0]["content"])["description"]
            return tool("resolve_place", {"place": {"name": description, "geocodeQuery": f"{description}, Europe", "sourceIndex": 0,
                                                    "tags": [] if description in names else ["resort"]}})
        if request.url.host == "api.exa.ai":
            return httpx.Response(200, json={"results": [{"title": "Evidence", "url": "https://evidence.example/e", "text": "Text"}]})
        name = request.url.params["q"].removesuffix(", Europe")
        if name in names:
            index, lat, lon, display = names[name]
            return httpx.Response(200, json=[{"osm_type": "relation", "osm_id": index, "name": name, "display_name": display, "lat": lat, "lon": lon}])
        return httpx.Response(200, json=HELDENPLATZ)

    settings = Settings(_env_file=None, anthropic_api_key="fixture", exa_api_key="fixture", nominatim_user_agent="Trails/1.0")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await create_discovery(client, cache, settings).discover("From Bratislava to Vienna via Heldenplatz", [])
    place = result.stops[0].place
    assert result.ready_for_handoff and (place.location.osm_type, place.location.osm_id) == ("node", 276645373)
    assert str(place.source.sourceUrl) == "https://www.openstreetmap.org/node/276645373"
    ttls = [await cache.ttl(key) for key in await cache.keys("gopstop:place-resolution:v3:*")]
    assert sorted(ttl > 300 for ttl in ttls) == [False, True, True]
