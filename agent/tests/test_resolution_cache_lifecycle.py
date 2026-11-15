import json

import fakeredis.aioredis
import httpx
import pytest
from redis.exceptions import ConnectionError

from gopstop_agent.config import Settings
from gopstop_agent.discovery import create_discovery
from gopstop_agent.resolution_cache import CachedPlaceResolver, ResolutionEntry
from gopstop_agent.resolver import ClaudePlaceResolver
from test_discovery import provider_fixture, row
from test_resolution_cache import PLACE, SOURCES
from test_resolver import tool


async def test_geocoding_rejection_is_short_lived_and_a_later_run_can_recover_without_flush():
    calls, generation = [], [0]
    providers = provider_fixture({"start": "Skok", "end": "Skok"}, {"Skok": ("Skok", [{**row(1, "Skok", 49, 20), "type": "waterfall"}])}, calls)

    def handle(request):
        if request.url.host == "api.anthropic.com" and json.loads(request.content)["tool_choice"]["name"] == "resolve_place":
            generation[0] += 1
            return httpx.Response(200, json=tool({**PLACE, "name": "Wrong" if generation[0] == 1 else "Skok",
                                                "geocodeQuery": "Skok, High Tatras, Slovakia"}))
        return providers(request)

    settings = Settings(_env_file=None, anthropic_api_key="fixture", exa_api_key="fixture", nominatim_user_agent="TrailsTest/1.0 team@example.org")
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await cache.set("team:keep", "keep")
        discovery = create_discovery(client, cache, settings)
        first = await discovery.discover("Skok", [])
        assert first.start.reason == "name_mismatch"
        key, = await cache.keys("gopstop:place-resolution:v3:*")
        assert 0 < await cache.ttl(key) <= 300
        assert not ResolutionEntry.model_validate_json(await cache.get(key)).accepted
        assert not (await discovery.discover("Skok", [])).ready_for_handoff
        assert generation[0] == 1  # No paid retry, even after downstream failure.
        # Simulate natural TTL expiry for this one key, never flush the shared cache.
        await cache.pexpire(key, 1)
        import asyncio
        await asyncio.sleep(.01)
        assert (await discovery.discover("Skok", [])).ready_for_handoff
        assert generation[0] == 2 and 300 < await cache.ttl(key) <= 86400
        assert ResolutionEntry.model_validate_json(await cache.get(key)).accepted
        await cache.expire(key, 1000)
        assert (await discovery.discover("Skok", [])).ready_for_handoff
        assert await cache.ttl(key) <= 1000 and generation[0] == 2
        assert await cache.get("team:keep") == "keep"


async def test_selection_feedback_is_atomic_does_not_refresh_hits_or_touch_a_different_result():
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as cache:
        resolver = CachedPlaceResolver(ClaudePlaceResolver(None, "fixture", "model"), cache)
        from gopstop_agent.resolver import SourceResolution
        place = SourceResolution.model_validate(PLACE)
        key = resolver._key("Skok", SOURCES)
        await cache.set(key, ResolutionEntry(place=place).model_dump_json(), ex=100)
        await resolver.record_selection("Skok", SOURCES, place, accepted=False)
        assert await cache.ttl(key) <= 100
        await resolver.record_selection("Skok", SOURCES, place, accepted=True)
        assert ResolutionEntry.model_validate_json(await cache.get(key)).accepted
        await cache.expire(key, 50)
        await resolver.record_selection("Skok", SOURCES, place, accepted=True)
        assert await cache.ttl(key) <= 50
        await resolver.record_selection("Skok", SOURCES, place, accepted=False)
        assert not ResolutionEntry.model_validate_json(await cache.get(key)).accepted and await cache.ttl(key) <= 50
        await cache.set(key, "different concurrent result", ex=70)
        await resolver.record_selection("Skok", SOURCES, place, accepted=True)
        await resolver.record_selection("Skok", SOURCES, place, accepted=False)
        assert await cache.get(key) == "different concurrent result"
        await cache.delete(key)
        await resolver.record_selection("Skok", SOURCES, place, accepted=True)
        assert not await cache.exists(key)


async def test_null_resolution_gets_only_provisional_ttl():
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=tool(None)),
    )) as client:
        resolver = CachedPlaceResolver(ClaudePlaceResolver(client, "fixture", "model"), cache)
        assert await resolver.resolve("Skok", SOURCES) is None
        key, = await cache.keys("gopstop:place-resolution:v3:*")
        assert 0 < await cache.ttl(key) <= 300


async def test_legacy_day_long_failure_is_ignored_without_deleting_team_data():
    async with fakeredis.aioredis.FakeRedis(decode_responses=True) as cache, httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=tool(PLACE)),
    )) as client:
        underlying = ClaudePlaceResolver(client, "fixture", "model")
        old = CachedPlaceResolver(underlying, cache, cache_namespace="gopstop:place-resolution:v2")
        legacy_key = old._key("Skok", SOURCES)
        await cache.set(legacy_key, "null", ex=86400)
        assert await CachedPlaceResolver(underlying, cache).resolve("Skok", SOURCES) is not None
        assert await cache.get(legacy_key) == "null"


async def test_feedback_storage_failure_propagates_without_replaying_paid_work(monkeypatch):
    from unittest.mock import AsyncMock
    cache = AsyncMock()
    cache.eval.side_effect = ConnectionError("private")
    from gopstop_agent.resolver import SourceResolution
    resolver = CachedPlaceResolver(ClaudePlaceResolver(None, "fixture", "model"), cache)
    with pytest.raises(ConnectionError):
        await resolver.record_selection("Skok", SOURCES, SourceResolution.model_validate(PLACE), accepted=True)
    cache.eval.assert_awaited_once()


async def test_contextually_resolved_candidate_is_promoted_after_final_anchor_selection():
    from test_geocoding_candidates import RYSY, SKOK, WESTERN_SKOK
    settings = Settings(_env_file=None, anthropic_api_key="fixture", exa_api_key="fixture",
                        nominatim_user_agent="TrailsTest/1.0 team@example.org")
    provider = provider_fixture({"start": "Rysy", "end": "Skok"},
                                {"Rysy": ("Rysy", [RYSY]), "Skok": ("Skok", [WESTERN_SKOK, SKOK])}, [])
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        finding = await create_discovery(client, cache, settings).discover("Rysy to Skok", [])
        assert finding.ready_for_handoff and finding.end.place.location.osm_id == SKOK["osm_id"]
        keys = await cache.keys("gopstop:place-resolution:v3:*")
        assert len(keys) == 2
        for key in keys:
            assert ResolutionEntry.model_validate_json(await cache.get(key)).accepted
            assert await cache.ttl(key) > 300
