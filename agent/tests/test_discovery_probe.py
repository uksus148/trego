import json

import fakeredis.aioredis
import httpx
import pytest

from gopstop_agent.config import Settings
from gopstop_agent.probe_discovery import run_probe
from test_discovery import tool
from test_groq import completion
from test_geocoding_candidates import SKOK, WESTERN_SKOK


@pytest.mark.parametrize("include_identity", [False, True])
async def test_identity_capture_is_explicit_and_keeps_provider_secrets_and_logs_private(include_identity, caplog):
    from test_discovery import provider_fixture, row
    calls = []
    fixture = provider_fixture({"start": "Private target", "end": "Private target"},
        {"Private target": ("Private target", [row(1, "Private target", 49, 20)])}, calls)
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(fixture)) as client:
        settings = Settings(_env_file=None, anthropic_api_key="NEVER_PRINT_KEY", exa_api_key="fixture",
                            nominatim_user_agent="TrailsTest/1.0 team@example.org")
        report = await run_probe(settings, client, cache, "Private target",
                                 cold=True, include_identity=include_identity)
    serialized = json.dumps(report)
    assert report["status"] == "ready" and len(calls) == 4
    assert "NEVER_PRINT_KEY" not in serialized + caplog.text and "Private target" not in caplog.text
    assert "evidence.example" not in serialized
    if include_identity:
        assert report["intentTargets"] == {"start": "Private target", "end": "Private target", "mustSee": [], "descriptiveTargets": []}
        identity = report["findings"][0]["identity"]
        assert identity["requestedTarget"] == identity["resolution"]["name"] == "Private target"
        assert identity["resolution"]["geocodeQuery"] == "Private target, High Tatras, Slovakia"
        assert identity["selectedOsm"] == {"osmType": "node", "osmId": 1}
    else:
        assert "intentTargets" not in report and "identity" not in report["findings"][0]
        assert "Private target" not in serialized


@pytest.mark.parametrize("provider", ["groq", "anthropic"])
@pytest.mark.parametrize("mode,expected", [("resolved", "resolved"), ("ambiguous", "ambiguous_candidates"), ("empty", "no_sources"),
    ("unsupported", "insufficient_evidence"), ("geocoding", "name_mismatch"), ("error", None), ("missing", None)])
async def test_read_only_discovery_probe_uses_real_factories_and_cleans_only_its_cache(provider, mode, expected, caplog):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.host in ("api.groq.com", "api.anthropic.com"):
            body = json.loads(request.content)
            name = body["response_format"]["json_schema"]["name"] if provider == "groq" else body["tool_choice"]["name"]
            if name == "extract_route_intent":
                value = {"start": "Skok", "end": None if mode == "missing" else "Skok", "mustSee": [], "preferences": []}
            elif name == "select_explore_area":
                value = {"area": None}
            else:
                assert name == "resolve_place"
                value = {"place": None if mode == "unsupported" else {"name": "Skok", "geocodeQuery": "Skok, Slovakia", "sourceIndex": 0, "tags": ["waterfall"]}}
            return httpx.Response(200, json=completion(value=value)) if provider == "groq" else tool(name, value)
        if request.url.host == "api.exa.ai":
            return httpx.Response(200, json={"results": [] if mode == "empty" else [{"title": "LEAK", "url": "https://secret.example/", "text": "LEAK"}]})
        assert request.url.host == "nominatim.openstreetmap.org"  # No Java/ORS/session API access.
        if mode == "error":
            return httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "LEAK"}})
        if mode == "ambiguous":
            return httpx.Response(200, json=[SKOK, WESTERN_SKOK])
        return httpx.Response(200, json=[{**SKOK, "name": "Other", "display_name": "Other"}] if mode == "geocoding" else [SKOK])

    settings = Settings(_env_file=None, llm_provider=provider, groq_api_key="LEAK", anthropic_api_key="LEAK", exa_api_key="LEAK")
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await cache.set("team:keep", "private")
        report = await run_probe(settings, client, cache, "LEAK", cold=True)
        assert not await cache.keys("gopstop:probe-discovery:*")
        assert not await cache.keys("gopstop:chat-session:*")
        assert await cache.get("team:keep") == b"private"
    assert "LEAK" not in json.dumps(report) + caplog.text and "secret.example" not in json.dumps(report) + caplog.text
    if expected:
        assert report["findings"][0]["reason"] == expected
        assert report["status"] == ("ready" if mode == "resolved" else "needs_clarification")
        if mode == "ambiguous":
            matches = report["findings"][0]["matches"]
            assert {m["osmId"] for m in matches} == {SKOK["osm_id"], WESTERN_SKOK["osm_id"]}
            assert all(m["osmType"] == "node" and m["distanceKm"] is None for m in matches)
    elif mode == "missing":
        assert report["missingEndpoints"] == ["end"] and len(calls) == 2  # Intent and tour detection.
    else:
        assert report["status"] == "failed" and report["error"]["http_status"] == 429
        assert report["error"]["provider"] == "nominatim"


async def test_warm_probe_reuses_only_nominatim_candidates_and_keeps_shared_gate():
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "api.anthropic.com":
            name = json.loads(request.content)["tool_choice"]["name"]
            return tool(name, {"start": "Skok", "end": "Skok"} if name == "extract_route_intent" else {
                "place": {"name": "Skok", "geocodeQuery": "Skok, Slovakia", "sourceIndex": 0, "tags": []}})
        if request.url.host == "api.exa.ai":
            return httpx.Response(200, json={"results": [{"title": "Skok", "url": "https://evidence.example/"}]})
        assert request.url.host == "nominatim.openstreetmap.org"
        return httpx.Response(200, json=[SKOK])

    settings = Settings(_env_file=None, anthropic_api_key="fixture", exa_api_key="fixture")
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        for _ in range(2):
            assert (await run_probe(settings, client, cache, "Skok"))["status"] == "ready"
        assert len(await cache.keys("gopstop:nominatim:search:v3:*")) == 1
        assert not await cache.keys("gopstop:probe-discovery:*")
    assert sum(r.url.host == "nominatim.openstreetmap.org" for r in requests) == 1
    assert sum(r.url.host == "api.exa.ai" for r in requests) == 2
    assert sum(r.url.host == "api.anthropic.com" for r in requests) == 4


async def test_shared_research_probe_reproduces_chat_cache_while_isolated_probe_can_differ():
    from gopstop_agent.discovery import create_discovery
    from gopstop_agent.resolution_cache import ResolutionEntry
    generations = []

    def handle(request):
        if request.url.host == "api.anthropic.com":
            name = json.loads(request.content)["tool_choice"]["name"]
            if name == "extract_route_intent":
                return tool(name, {"start": "Skok", "end": "Skok"})
            generations.append(request)
            return tool(name, {"place": {"name": "Wrong" if len(generations) == 1 else "Skok",
                "geocodeQuery": "Skok, Slovakia", "sourceIndex": 0, "tags": []}})
        if request.url.host == "api.exa.ai":
            return httpx.Response(200, json={"results": [{"title": "Skok", "url": "https://evidence.example/"}]})
        assert request.url.host == "nominatim.openstreetmap.org"
        return httpx.Response(200, json=[SKOK])

    settings = Settings(_env_file=None, anthropic_api_key="fixture", exa_api_key="fixture")
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert not (await create_discovery(client, cache, settings).discover("Skok", [])).ready_for_handoff
        key, = await cache.keys("gopstop:place-resolution:v3:*")
        await cache.expire(key, 50)
        shared = await run_probe(settings, client, cache, "Skok", shared_research=True)
        assert shared["researchCache"] == "shared" and shared["findings"][0]["reason"] == "requested_identity_mismatch"
        assert len(generations) == 1 and await cache.ttl(key) <= 50
        isolated = await run_probe(settings, client, cache, "Skok")
        assert isolated["status"] == "ready" and len(generations) == 2
        assert not ResolutionEntry.model_validate_json(await cache.get(key)).accepted
        assert not await cache.keys("gopstop:probe-discovery:*")
        with pytest.raises(ValueError):
            await run_probe(settings, client, cache, "Skok", cold=True, shared_research=True)
