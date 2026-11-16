"""Prove the fixture transport fails closed before attempting an external socket."""

import importlib
import sys
from pathlib import Path

import httpx
import pytest
import fakeredis.aioredis


def load_fixture(monkeypatch):
    monkeypatch.setenv("E2E_API_PORT", "1")
    monkeypatch.setenv("E2E_VALKEY_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("E2E_FRONTEND_URL", "http://127.0.0.1:1")
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    from gopstop_agent.config import Settings
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    module = importlib.import_module("fixture_agent")
    module.CALLS.clear()
    return module


@pytest.mark.asyncio
async def test_unknown_hosts_and_local_api_ports_never_fall_through(monkeypatch):
    module = load_fixture(monkeypatch)
    try:
        async with module.FixtureTransport() as transport:
            for url in ("https://example.org/search", "https://api.groq.com/other", "http://127.0.0.1:2/api/routes"):
                with pytest.raises(AssertionError, match="Blocked unexpected outbound"):
                    await transport.handle_async_request(httpx.Request("GET", url))
    finally:
        await module.provider_http.aclose()
        sys.modules.pop("fixture_agent", None)


@pytest.mark.asyncio
@pytest.mark.parametrize("incomplete", [False, True])
async def test_current_discovery_factory_accepts_fixture_protocol_without_live_requests(monkeypatch, incomplete):
    from gopstop_agent.discovery import create_discovery

    module = load_fixture(monkeypatch)
    try:
        async with fakeredis.aioredis.FakeRedis(decode_responses=True) as cache, \
                httpx.AsyncClient(transport=module.FixtureTransport()) as client:
            message = module.CORPUS["incompleteMessage" if incomplete else "message"]
            result = await create_discovery(client, cache, module.settings).discover(message, [])
            assert result.intent.descriptiveTargets == []
            assert result.ready_for_handoff == (not incomplete)
            assert not any(call.startswith("api:") for call in module.CALLS)
            if incomplete:
                assert module.CALLS == ["extract_route_intent", "select_explore_area"]
            else:
                findings = [result.start, *result.stops, result.end]
                by_name = {p["name"]: (module.CORPUS["osmIds"][i], p["source"])
                           for i, p in enumerate(module.CORPUS["places"])}
                for finding in findings:
                    osm_id, source = by_name[finding.description]
                    assert finding.place.location.osm_id == osm_id
                    assert str(finding.place.source.sourceUrl) == source
                assert module.CALLS.count("exa") == module.CALLS.count("nominatim") == 3
    finally:
        await module.provider_http.aclose()
        sys.modules.pop("fixture_agent", None)
