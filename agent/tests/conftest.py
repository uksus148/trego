"""Keep fixture tests independent of a developer's private service settings."""

import asyncio
import os

import pytest

from trego_agent.config import Settings


@pytest.fixture
def expire_cache_key():
    async def expire(cache, key):
        await cache.pexpire(key, 1)
        # Wall-clock expiry can lag a short asyncio sleep on Windows.
        async with asyncio.timeout(2):
            while await cache.exists(key):
                await asyncio.sleep(0.02)

    return expire


@pytest.fixture
def valkey_url():
    url = os.environ.get("TEST_VALKEY_URL")
    if not url:
        pytest.skip("Set TEST_VALKEY_URL to a disposable real Valkey instance.")
    return url


def pytest_configure(config):
    # Run before collection: importing main constructs its default app/settings.
    monkeypatch = pytest.MonkeyPatch()
    config.add_cleanup(monkeypatch.undo)
    for name in list(os.environ):
        if name.startswith("AGENT_") or name in {
            "ANTHROPIC_API_KEY", "GROQ_API_KEY", "EXA_API_KEY", "SPRING_DATA_REDIS_URL",
        }:
            monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
