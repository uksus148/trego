"""Exercise the new HTTP boundary without live providers or storage."""

import asyncio
import logging
import socket

import httpx
import pytest

from gopstop_agent.v2.config import AppSettings
from gopstop_agent.v2.main import create_app, create_fixture_app
from gopstop_agent.v2.models import ChatResponse


@pytest.fixture(autouse=True)
async def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Foundation tests must not open network connections.")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)


async def post(app, payload=None, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://fixture"
    ) as client:
        return await client.post(
            "/api/chat", json=payload or {"sessionId": "private-session", "message": "private-message"},
            **kwargs,
        )


async def test_fixture_starts_without_environment_or_services(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("AGENT_CHAT_TIMEOUT_SECONDS=invalid\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_CHAT_TIMEOUT_SECONDS", "invalid")
    monkeypatch.setenv("AGENT_CHAT_ENABLED", "true")
    app = create_fixture_app()
    with caplog.at_level(logging.INFO, logger="gopstop_agent.v2"):
        async with app.router.lifespan_context(app):
            response = await post(app, headers={"X-Trace-Id": "private-client-trace"})
    assert response.status_code == 200
    assert set(response.json()) == {"reply", "places"}
    assert "[LOCAL FIXTURE]" in response.json()["reply"]
    assert response.json()["places"] == []
    trace_id = response.headers["X-Trace-Id"]
    assert len(trace_id) == 32 and int(trace_id, 16) >= 0
    assert trace_id in caplog.text
    assert "stage=chat" in caplog.text and "stage=http" in caplog.text
    assert "event=started" in caplog.text and "event=stopped" in caplog.text
    assert not any(value in caplog.text for value in (
        "private-session", "private-message", "private-client-trace",
    ))


@pytest.mark.parametrize("changes", [
    {"sessionId": " "}, {"message": "\t"}, {"sessionId": "s" * 129},
    {"message": "m" * 4001}, {"message": 123}, {"message": None},
    {"private-extra-field": "private-extra-value"},
])
async def test_invalid_input_never_calls_core_or_echoes_payload(changes, caplog):
    class Unreachable:
        async def respond(self, request):
            pytest.fail("Invalid input reached the core.")

    app = create_app(AppSettings(), Unreachable())
    response = await post(app, {"sessionId": "private-session", "message": "private-message", **changes})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert "private-" not in response.text + caplog.text
    assert "stage=validation" in caplog.text


async def test_malformed_json_does_not_echo_input():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_fixture_app()), base_url="http://fixture"
    ) as client:
        response = await client.post("/api/chat", content='{"private-secret":',
                                     headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and "private-secret" not in response.text


async def test_handler_delegates_exact_values_and_accepts_contract_limits():
    received = []

    class Recorder:
        async def respond(self, request):
            received.append(request)
            return ChatResponse(reply="A question from the supplied service.")

    app = create_app(AppSettings(), Recorder())
    payload = {"sessionId": "s" * 128, "message": " " + "m" * 3998 + " "}
    response = await post(app, payload)
    assert response.status_code == 200
    assert received[0].model_dump() == payload
    assert response.json() == {"reply": "A question from the supplied service.", "places": []}


async def test_deadline_cancels_core_and_returns_safe_504(caplog):
    cancelled = asyncio.Event()

    class Blocked:
        async def respond(self, request):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    response = await post(create_app(AppSettings(chat_timeout_seconds=0.01), Blocked()))
    assert response.status_code == 504 and cancelled.is_set()
    assert "private-" not in response.text + caplog.text
    assert any(record.levelno == logging.ERROR for record in caplog.records)


@pytest.mark.parametrize("invalid_response", [False, True])
async def test_unexpected_failure_and_invalid_response_are_sanitized(invalid_response, caplog):
    class Broken:
        async def respond(self, request):
            if invalid_response:
                return {"reply": "private-response", "places": "private-invalid"}
            raise RuntimeError("private-exception")

    response = await post(create_app(AppSettings(), Broken()))
    assert response.status_code == 500
    assert response.json() == {"detail": "Unexpected agent failure."}
    assert "private-" not in response.text + caplog.text
    assert any(record.levelno == logging.ERROR for record in caplog.records)


async def test_external_cancellation_propagates(caplog):
    started, cancelled = asyncio.Event(), asyncio.Event()

    class Blocked:
        async def respond(self, request):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    with caplog.at_level(logging.INFO, logger="gopstop_agent.v2"):
        task = asyncio.create_task(post(create_app(AppSettings(), Blocked())))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert cancelled.is_set() and "outcome=cancelled" in caplog.text
    assert not any(record.levelno == logging.ERROR for record in caplog.records)


async def test_concurrent_requests_have_independent_traces(caplog):
    app = create_fixture_app()
    with caplog.at_level(logging.INFO, logger="gopstop_agent.v2"):
        responses = await asyncio.gather(post(app), post(app))
    traces = {r.headers["X-Trace-Id"] for r in responses}
    assert len(traces) == 2
    for trace in traces:
        assert any(f"trace={trace} stage=chat" in r.message for r in caplog.records)
