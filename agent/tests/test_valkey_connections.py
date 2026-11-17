"""Fault-injection loopback proxy forwarding storage to disposable real Valkey."""

import asyncio
import ssl
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.asyncio import Redis
from redis.asyncio.connection import SSLConnection
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import AuthenticationError

from trego_agent.chat import ChatResponse
from trego_agent.config import Settings
from trego_agent.main import create_app
from trego_agent.valkey import HealthyConnectionPool, from_url


def resp(value):
    if value is None:
        return b"$-1\r\n"
    if isinstance(value, list):
        return b"*%d\r\n" % len(value) + b"".join(resp(item) for item in value)
    if isinstance(value, bytes):
        return b"$%d\r\n" % len(value) + value + b"\r\n"
    if isinstance(value, int):
        return b":%d\r\n" % value
    return b"+" + value.encode() + b"\r\n"


class ValkeyWire:
    def __init__(self):
        self.keys, self.commands = set(), []
        self.clients, self.tasks, self.stale = set(), set(), set()
        self.stale_failures, self.execs = 0, 0
        self.down, self.lose_exec_reply, self.auth_error = False, False, False
        self.blackhole, self.history_gate, self.history_reads = False, None, 0

    async def handle(self, reader, writer):
        self.clients.add(writer)
        task = asyncio.current_task()
        self.tasks.add(task)
        backend = Redis.from_url(self.backend_url, single_connection_client=True)
        backend.response_callbacks = {}
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                assert line.startswith(b"*")
                args = []
                for _ in range(int(line[1:])):
                    length = int((await reader.readline())[1:])
                    args.append(await reader.readexactly(length))
                    assert await reader.readexactly(2) == b"\r\n"
                cmd = args[0].upper()
                self.commands.append(cmd)
                if cmd in (b"SET", b"GET", b"WATCH", b"RPUSH", b"LRANGE"):
                    self.keys.add(args[1])
                # Simulate a silently dropped idle socket: it looks connected
                # until the next write/read, rather than exposing EOF at checkout.
                if self.down or writer in self.stale:
                    self.stale.discard(writer)
                    self.stale_failures += 1
                    if self.blackhole:
                        await reader.read()  # No reply until the client times out/cancels.
                    return
                if cmd == b"LRANGE" and self.history_gate is not None:
                    self.history_reads += 1
                    if self.history_reads == 3:
                        self.history_gate.set()
                    await self.history_gate.wait()
                if cmd == b"AUTH" and self.auth_error:
                    writer.write(b"-WRONGPASS fixture credentials rejected\r\n")
                else:
                    result = await backend.execute_command(*args)
                    if cmd == b"EXEC":
                        self.execs += 1
                        if self.lose_exec_reply:
                            return  # Actual Valkey committed; its response was lost.
                    writer.write(resp(result))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            await backend.aclose()
            writer.close()
            await writer.wait_closed()
            self.clients.discard(writer)
            self.tasks.discard(task)


@pytest.fixture
async def wire(valkey_url):
    server = ValkeyWire()
    server.backend_url = valkey_url
    server.backend = Redis.from_url(valkey_url)
    listener = await asyncio.start_server(server.handle, "127.0.0.1", 0)
    server.url = f"redis://127.0.0.1:{listener.sockets[0].getsockname()[1]}/0"
    yield server
    listener.close()
    await listener.wait_closed()
    for writer in list(server.clients):
        writer.close()
    for task in list(server.tasks):
        task.cancel()
    await asyncio.gather(*list(server.tasks), return_exceptions=True)
    if server.keys:
        await server.backend.delete(*server.keys)
    await server.backend.aclose()


def app_for(wire, **overrides):
    service = AsyncMock()
    service.respond.return_value = ChatResponse(reply="Fixture reply.", places=[])
    settings = Settings(_env_file=None, **{"chat_enabled": True, "valkey_url": wire.url,
                        "valkey_connect_timeout_seconds": .2, "valkey_socket_timeout_seconds": .2, **overrides})
    return create_app(settings, chat_service=service), service


async def test_first_chats_recover_all_idle_sockets_before_history_and_store_each_exchange_once(wire):
    app, service = app_for(wire)
    async with app.router.lifespan_context(app):
        cache = app.state.session_store._client
        connections = [await cache.connection_pool.get_connection() for _ in range(3)]
        for connection in connections:
            await cache.connection_pool.release(connection)
        assert len(wire.clients) == 3
        wire.stale.update(wire.clients)
        wire.history_gate = asyncio.Event()  # Keep all three checkouts active concurrently.
        for connection in cache.connection_pool._available_connections:
            connection.next_health_check = 0  # Simulate expiry, without a real idle wait.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://agent") as http:
            responses = await asyncio.gather(*(http.post("/api/chat", json={
                "sessionId": f"idle-{i}", "message": "Plan a hike",
            }) for i in range(3)))
        assert [r.status_code for r in responses] == [200, 200, 200]
        assert wire.stale_failures == 3 and service.respond.await_count == 3
        assert wire.execs == 3
        assert [await wire.backend.llen(f"gopstop:chat-session:idle-{i}") for i in range(3)] == [2, 2, 2]
        assert cache.connection_pool.connection_kwargs["retry"].get_retries() == 0
    assert not cache.connection_pool._in_use_connections
    assert all(not connection.is_connected for connection in connections)


@pytest.mark.parametrize("cancel", [False, True])
async def test_silent_idle_socket_recovers_within_socket_budget_or_propagates_chat_cancellation(wire, cancel):
    app, service = app_for(wire, **({"chat_timeout_seconds": .02} if cancel else {}))
    async with app.router.lifespan_context(app):
        cache = app.state.session_store._client
        await cache.ping()
        for connection in cache.connection_pool._available_connections:
            connection.next_health_check = 0
        wire.stale.update(wire.clients)
        wire.blackhole = True
        wire.commands.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://agent") as http:
            response = await asyncio.wait_for(http.post("/api/chat", json={
                "sessionId": "silent", "message": "Plan a hike",
            }), 1)
        assert response.status_code == (504 if cancel else 200)
        assert service.respond.await_count == (0 if cancel else 1)
        assert wire.stale_failures == 1 and wire.execs == (0 if cancel else 1)
        if cancel:
            assert wire.commands == [b"PING"]


async def test_lost_exec_response_returns_503_without_replaying_committed_session_writes(wire):
    app, service = app_for(wire)
    wire.lose_exec_reply = True
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://agent") as http:
            response = await http.post("/api/chat", json={"sessionId": "lost", "message": "Plan a hike"})
        assert response.status_code == 503
        assert wire.execs == 1 and await wire.backend.llen("gopstop:chat-session:lost") == 2
        assert service.respond.await_count == 1


async def test_real_outage_stays_a_bounded_503_before_any_provider_work(wire):
    app, service = app_for(wire)
    wire.down = True
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://agent") as http:
            response = await asyncio.wait_for(http.post("/api/chat", json={
                "sessionId": "down", "message": "Plan a hike",
            }), 1)
        assert response.status_code == 503 and service.respond.await_count == 0
        assert wire.execs == 0


async def test_authentication_failure_is_not_retried(wire):
    wire.auth_error = True
    client = from_url(wire.url.replace("redis://", "redis://fixture:wrong@"), retry=Retry(NoBackoff(), 0))
    try:
        with pytest.raises(AuthenticationError):
            await client.ping()
        assert wire.commands.count(b"AUTH") == 1
    finally:
        await client.aclose()


async def test_pool_retains_tls_verification_and_owned_client_cleanup():
    client = from_url("rediss://localhost:6380/2", health_check_interval=15,
                      socket_keepalive=True, retry=Retry(NoBackoff(), 0))
    try:
        assert isinstance(client.connection_pool, HealthyConnectionPool)
        assert client.connection_pool.connection_class is SSLConnection
        connection = client.connection_pool.make_connection()
        context = connection.ssl_context.get()
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert connection.retry.get_retries() == 0 and client.auto_close_connection_pool
    finally:
        await client.aclose()
