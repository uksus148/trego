"""Prove the fixture transport fails closed before attempting an external socket."""

import importlib
import sys
from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_unknown_hosts_and_local_api_ports_never_fall_through(monkeypatch):
    monkeypatch.setenv("E2E_API_PORT", "1")
    monkeypatch.setenv("E2E_VALKEY_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("E2E_FRONTEND_URL", "http://127.0.0.1:1")
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    from gopstop_agent.config import Settings
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    module = importlib.import_module("fixture_agent")
    try:
        async with module.FixtureTransport() as transport:
            for url in ("https://example.org/search", "https://api.groq.com/other", "http://127.0.0.1:2/api/routes"):
                with pytest.raises(AssertionError, match="Blocked unexpected outbound"):
                    await transport.handle_async_request(httpx.Request("GET", url))
    finally:
        await module.provider_http.aclose()
        sys.modules.pop("fixture_agent", None)
