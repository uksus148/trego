import json
from types import SimpleNamespace

import fakeredis.aioredis
import httpx
import pytest

from trego_agent import smoke
from trego_agent.config import Settings
from trego_agent.exa import ExaSearch
from trego_agent.llm import ProviderError
from trego_agent.provider_errors import http_failure
from trego_agent.sessions import ValkeySessionStore
from trego_agent.trails_api import HandoffError
from test_discovery import row
from test_groq import completion
from test_resolution_cache import PLACE
from test_trails_api import place, route


async def test_preflight_checks_real_adapters_with_fixtures_and_only_deletes_its_session():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.host == "api.groq.com":
            name = json.loads(request.content)["response_format"]["json_schema"]["name"]
            value = {"extract_route_intent": {"start": "A", "end": "B", "mustSee": [], "preferences": []}, "resolve_place": {"place": PLACE},
                     "select_reply_language": {"language": "en"}}[name]
            return httpx.Response(200, json=completion(name, value))
        if request.url.host == "api.exa.ai":
            return httpx.Response(200, json={"results": [{"title": "Skok", "url": "https://evidence.example/", "text": "Tatras"}]})
        if request.url.host == "nominatim.openstreetmap.org":
            assert "contact:" in request.headers["User-Agent"]
            return httpx.Response(200, json=[row(1, "Skok", 49.14, 20.05)])
        assert request.method == "GET" and request.url.path == "/api/places"
        return httpx.Response(200, json=[])

    settings = Settings(_env_file=None, llm_provider="groq", groq_api_key="fixture", exa_api_key="fixture")
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as cache, httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
    ) as http:
        await cache.set("keep", "team data")
        await ExaSearch(http, cache, "old-key").search("Skok waterfall High Tatras Slovakia hiking")
        calls.clear()  # The real preflight must still authenticate Exa, despite this warm shared cache.
        report = {"checks": []}
        await smoke.preflight(http, cache, settings, report)
        assert len(report["checks"]) == 7 and report["geocoding"] == "resolved"
        assert not await cache.keys("gopstop:preflight:exa:*")
        assert len(await cache.keys("gopstop:exa-text:v1:*")) == 1
        assert not await cache.keys("gopstop:chat-session:preflight-*") and await cache.get("keep") == "team data"
    assert len(calls) == 6  # Three model tasks, Exa, Nominatim and read-only API.


@pytest.mark.parametrize("failure", [None, "clarification", "session", "route", "cors", "cors_method", "cors_header"])
async def test_chat_smoke_requires_fetchable_route_sources_cors_and_saved_exchange(failure):
    settings = Settings(_env_file=None, chat_enabled=True)
    posts = []
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as cache:
        async def handle(request):
            headers = {"access-control-allow-origin": "http://localhost:5173"} if failure != "cors" else {}
            headers["access-control-allow-methods"] = "GET" if failure == "cors_method" else "GET, POST"
            headers["access-control-allow-headers"] = "Accept" if failure == "cors_header" else "Content-Type"
            if request.method == "OPTIONS":
                return httpx.Response(200, headers=headers)
            if request.method == "POST":
                posts.append(request)
                body = json.loads(request.content)
                if failure != "session":
                    await ValkeySessionStore(cache, 60, 12).record_exchange(body["sessionId"], body["message"], "Ready")
                return httpx.Response(200, headers=headers, json={"reply": "Ready", "places": [place(1), place(2)],
                    **({} if failure == "clarification" else {"routeId": route()["id"]})})
            return httpx.Response(404 if failure == "route" else 200, json=route([place(2)]))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            report = {"checks": []}
            if failure:
                with pytest.raises((ValueError, HandoffError)):
                    await smoke.chat_smoke(http, cache, settings, "https://agent.example", "Hike", report)
            else:
                await smoke.chat_smoke(http, cache, settings, "https://agent.example", "Hike", report)
                assert report["routeId"] == route()["id"] and len(report["checks"]) == 4
                assert len(await cache.keys("gopstop:chat-session:e2e-*")) == 1
        assert len(posts) == (0 if failure in ("cors", "cors_method", "cors_header") else 1)


async def test_cli_reports_missing_keys_without_secrets_or_network(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "Settings", lambda: Settings(_env_file=None, llm_provider="groq", groq_api_key="private"))
    assert await smoke.run(SimpleNamespace(chat=False)) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["stage"] == "configuration" and report["error"] == "ValueError"
    assert "private" not in json.dumps(report)


@pytest.mark.parametrize("status", [401, 429])
async def test_cli_reports_provider_http_status_without_upstream_body(monkeypatch, capsys, status):
    async def fail(http, cache, settings, report):
        report["stage"] = "llm_intent"
        response = httpx.Response(status, json={"error": {"code": "invalid_api_key", "message": "private provider body"}})
        raise http_failure(response, provider="groq", operation="extract_route_intent")

    monkeypatch.setattr(smoke, "Settings", lambda: Settings(_env_file=None, llm_provider="groq", groq_api_key="fixture", exa_api_key="fixture"))
    monkeypatch.setattr(smoke, "from_url", lambda *a, **k: fakeredis.aioredis.FakeRedis())
    monkeypatch.setattr(smoke, "preflight", fail)
    assert await smoke.run(SimpleNamespace(chat=False)) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["httpStatus"] == status and report["stage"] == "llm_intent"
    assert report["diagnostic"]["provider_code"] == "invalid_api_key"
    assert "private" not in json.dumps(report)
