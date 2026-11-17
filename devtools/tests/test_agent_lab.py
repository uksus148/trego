"""Local-only inspection of the actual v2 HTTP boundary."""

import asyncio
import json

import httpx
import pytest

from devtools.agent_lab.app import create_app
from devtools.agent_lab.records import Records


TOKEN = "test-launch-token-" + "x" * 32


class MemoryVault:
    api = True

    def __init__(self):
        self.values = {}

    def read(self, provider):
        return self.values.get(provider)

    def write(self, provider, value):
        self.values[provider] = value

    def delete(self, provider):
        self.values.pop(provider, None)


@pytest.fixture
async def lab(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A diagnostic run constructed an external transport.")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    monkeypatch.setenv("AGENT_API_BASE_URL", "https://team.invalid")
    app = create_app(TOKEN, MemoryVault())
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8012",
        headers={"X-Lab-Token": TOKEN},
    ) as client:
        yield app.state.lab, client


async def run(lab, client, **options):
    response = await client.post("/lab/run", json={
        "request": {"sessionId": "own-session", "message": "An arbitrary request"},
        **options,
    })
    assert response.status_code == 202, response.text
    await lab.task
    return (await client.get("/lab/runs/" + response.json()["runId"])).json()


async def test_host_origin_auth_and_body_limits(lab):
    _, client = lab
    assert (await client.get("/lab/status", headers={"X-Lab-Token": "bad"})).status_code == 403
    assert (await client.get("/lab/status", headers={"Host": "evil.example"})).status_code == 403
    assert (await client.post("/lab/reset", headers={"Origin": "https://evil.example"})).status_code == 403
    assert (await client.post("/lab/run", content="x" * 40000)).status_code == 413
    invalid = await client.post("/lab/keys", json={"provider": "unknown-private", "value": "private-key"})
    assert invalid.status_code == 422 and "private" not in invalid.text
    page = await client.get("/")
    assert page.status_code == 200
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "no-store" in page.headers["cache-control"]


async def test_real_foundation_is_called_and_payload_capture_is_opt_in(lab):
    state, client = lab
    metadata = await run(state, client)
    assert metadata["status"] == "completed" and metadata["httpStatus"] == 200
    assert metadata["request"] is None and metadata["response"] is None
    assert "An arbitrary request" not in json.dumps(metadata)
    assert any(e.get("stage") == "chat" for e in metadata["events"])
    assert metadata["traceId"]
    detailed = await run(state, client, inspect=True)
    assert detailed["request"]["message"] == "An arbitrary request"
    assert detailed["response"]["reply"].startswith("[LOCAL FIXTURE]")
    assert detailed["response"]["places"] == [] and "routeId" not in detailed["response"]
    status = (await client.get("/lab/status")).json()
    assert status["application"] == "trego-v2-lab"
    assert not any(c["available"] for c in status["capabilities"] if c["id"] in {"llm", "java", "research"})


@pytest.mark.parametrize("body", [{}, {"sessionId": "s", "message": " "}])
async def test_invalid_input_reaches_actual_core_validation(lab, body):
    state, client = lab
    record = await run(state, client, request=body, inspect=True)
    assert record["httpStatus"] == 422 and record["status"] == "failed"
    assert any(e["level"] == "WARNING" for e in record["events"])


@pytest.mark.parametrize("mode,expected", [("failure", 500), ("wait", 504)])
async def test_failure_and_timeout_are_visible_without_network(lab, mode, expected):
    state, client = lab
    record = await run(state, client, mode=mode, timeout_seconds=0.03, inspect=True)
    assert record["status"] == "failed" and record["httpStatus"] == expected
    assert any(e["level"] == "ERROR" for e in record["events"])


async def test_cancel_overlap_and_reset(lab):
    state, client = lab
    payload = {"request": {"sessionId": "s", "message": "anything"}, "mode": "wait"}
    assert (await client.post("/lab/run", json=payload)).status_code == 202
    await asyncio.sleep(0)
    assert (await client.post("/lab/run", json=payload)).status_code == 409
    assert (await client.post("/lab/reset")).status_code == 409
    assert (await client.post("/lab/cancel")).status_code == 200
    assert state.records.runs[-1]["status"] == "cancelled"
    assert (await client.post("/lab/reset")).status_code == 200
    assert not (await client.get("/lab/status")).json()["runs"]


async def test_keys_are_write_only_redacted_and_persistence_is_explicit(lab):
    state, client = lab
    key = "gsk_personal_dummy_key_123456789"
    assert (await client.post("/lab/keys", json={"provider": "groq", "value": key})).status_code == 200
    assert not state.vault.values
    status = await client.get("/lab/status")
    assert key not in status.text and status.json()["keys"]["groq"] == {"present": True, "saved": False}
    record = await run(state, client, inspect=True, request={"sessionId": "s", "message": key})
    exported = await client.get("/lab/export/" + record["id"])
    assert exported.status_code == 200 and key not in exported.text
    assert "[REDACTED]" in exported.text
    assert (await client.post("/lab/keys", json={"provider": "groq", "value": key, "remember": True})).status_code == 200
    assert state.vault.values["groq"] == key
    await client.delete("/lab/keys/groq")
    assert not state.vault.values and not state.keys


async def test_unavailable_vault_does_not_fall_back_to_plaintext(lab):
    state, client = lab
    def unavailable(*args):
        raise OSError("private-vault-error")
    state.vault.write = unavailable
    response = await client.post("/lab/keys", json={"provider": "exa", "value": "personal", "remember": True})
    assert response.status_code == 503
    assert "personal" not in response.text and "private-vault-error" not in response.text
    assert "exa" not in state.keys


async def test_stop_cancels_work_and_requests_server_shutdown(lab):
    from types import SimpleNamespace

    state, client = lab
    state.server = SimpleNamespace(should_exit=False)
    await client.post("/lab/run", json={"request": {"sessionId": "s", "message": "wait"}, "mode": "wait"})
    assert (await client.post("/lab/stop")).status_code == 200
    assert state.server.should_exit and not state.busy
    assert state.records.runs[-1]["status"] == "cancelled"


def test_records_are_bounded_and_remove_secrets_from_keys_and_nested_values():
    records = Records(lambda: ["personal-secret"])
    cleaned = records.clean({"personal-secret": {"authorization": "secret", "reasoning_content": "hidden"}})
    assert "personal-secret" not in json.dumps(cleaned) and "hidden" not in json.dumps(cleaned)
    for _ in range(25):
        item = records.start({"inspect": True})
    for _ in range(200):
        records.event(item, {"message": "x" * 40000})
    assert len(records.runs) == 20 and len(item["events"]) <= 128
    assert item["truncated"]
    assert len(json.dumps(item).encode()) < 1200000
