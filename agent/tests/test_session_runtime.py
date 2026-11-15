"""Issue #84 / audit #81: actual app instances and disposable Valkey, no provider calls."""

import asyncio
from contextlib import AsyncExitStack
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from gopstop_agent.chat import ChatResponse
from gopstop_agent.config import Settings
from gopstop_agent.main import create_app
from gopstop_agent.sessions import SessionBusy, ValkeySessionStore


class PausedService:
    def __init__(self):
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.calls = []

    async def respond(self, message, history):
        self.calls.append((message, history))
        if message == "first":
            self.entered.set()
            await self.release.wait()
        return ChatResponse(reply="x" * 4001 if message == "oversized" else message, places=[])


async def test_two_apps_reject_overlap_then_read_committed_history_and_release_after_cancel(valkey_url):
    session = uuid4().hex
    service = PausedService()
    async with AsyncExitStack() as stack:
        caches = [await stack.enter_async_context(Redis.from_url(valkey_url, decode_responses=True)) for _ in range(2)]
        apps = [create_app(Settings(chat_enabled=True), redis_client=c, chat_service=service) for c in caches]
        for app in apps:
            await stack.enter_async_context(app.router.lifespan_context(app))
        clients = [await stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app),
                   base_url="http://agent")) for app in apps]
        async def post(index, message, sid=session):
            return await clients[index].post("/api/chat", json={"sessionId": sid, "message": message})
        first = asyncio.create_task(post(0, "first"))
        try:
            await asyncio.wait_for(service.entered.wait(), 2)
            assert (await post(1, "overlap")).status_code == 409
            assert (await post(1, "independent", session + "other")).status_code == 200
            assert [c[0] for c in service.calls] == ["first", "independent"]
            service.release.set()
            assert (await first).status_code == 200
            assert (await post(1, "dependent")).status_code == 200
            assert service.calls[-1][1] == [{"role": "user", "content": "first"},
                                          {"role": "assistant", "content": "first"}]
            before = await caches[0].lrange(f"gopstop:chat-session:{session}", 0, -1)
            assert (await post(1, "oversized")).status_code == 503
            assert await caches[0].lrange(f"gopstop:chat-session:{session}", 0, -1) == before
            service.release.clear()
            service.entered.clear()
            first = asyncio.create_task(post(0, "first"))
            await asyncio.wait_for(service.entered.wait(), 2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert (await post(1, "after cancellation")).status_code == 200
        finally:
            service.release.set()
            await asyncio.gather(first, return_exceptions=True)
            await caches[0].delete(f"gopstop:chat-session:{session}", f"gopstop:chat-session:{session}other")


async def test_expired_owner_cannot_append_or_release_successor_and_crash_lease_expires(valkey_url):
    session = uuid4().hex
    async with Redis.from_url(valkey_url, decode_responses=True) as cache:
        a, b = [ValkeySessionStore(cache, 600, 2) for _ in range(2)]
        key = f"gopstop:chat-session:{session}"
        lease_key = a._lease_key(session)
        await a.record_exchange(session, "x" * 4000, "y" * 4000)
        before = await cache.lrange(key, 0, -1)
        async with a.turn(session, 2):
            async with b.turn(session + "other", 2):
                for user, reply in [("valid", "x" * 4001), ("x" * 4001, "valid"), (None, "valid"), ("", "reply"), ("valid", " ")]:
                    with pytest.raises(RedisError):
                        await a.record_exchange(session, user, reply)
            await cache.pexpire(lease_key, 1)
            await asyncio.sleep(.02)
            successor = b.turn(session, 2)
            await successor.__aenter__()
            with pytest.raises(RedisError):
                await a.record_exchange(session, "stale", "reply")
            assert await cache.lrange(key, 0, -1) == before
        assert await cache.exists(lease_key)  # A's release cannot delete B's lease.
        await b.record_exchange(session, "new", "reply")
        await successor.__aexit__(None, None, None)
        assert len(await a.history(session)) == 2 and 0 < await cache.ttl(key) <= 600
        await cache.set(lease_key, "crashed", px=10)
        with pytest.raises(SessionBusy):
            async with a.turn(session, 2):
                pytest.fail("A live abandoned lease must block work")
        await asyncio.sleep(.02)
        async with a.turn(session, 2):
            pass
        await cache.delete(key)
