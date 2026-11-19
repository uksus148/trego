"""Local-only inspection of the actual v2 HTTP boundary."""

import asyncio
import json

import httpx
import pytest

from devtools.agent_lab.app import create_app
from devtools.agent_lab.model_probe import GROQ_MODEL
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


@pytest.fixture
async def groq_lab():
    calls = []
    provider = {"response": httpx.Response(200, json={
        "choices": [{"finish_reason": "stop", "message": {
            "content": '{"summary":"Walk to the park."}', "reasoning": "private reasoning",
        }}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
    })}

    async def reply(request):
        calls.append(request)
        result = provider["response"]
        if callable(result):
            return await result()
        if isinstance(result, Exception):
            raise result
        return result

    app = create_app(TOKEN, MemoryVault(), groq_transport=httpx.MockTransport(reply))
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8012", headers={"X-Lab-Token": TOKEN},
    ) as client:
        yield app.state.lab, client, calls, provider


async def test_live_probe_uses_explicit_key_and_records_a_private_view(groq_lab):
    lab, client, calls, _ = groq_lab
    body = {"mode": "groq", "request": {"sessionId": "private session", "message": "Go to the park."}}
    assert (await client.post("/lab/run", json=body)).status_code == 400
    assert not calls

    key = "local-personal-key"
    assert (await client.post("/lab/keys", json={"provider": "groq", "value": key})).status_code == 200
    local = await run(lab, client)
    assert local["options"]["mode"] == "foundation" and not calls
    rejected = {**body, "request": {"sessionId": "s", "message": f"Accidental paste: {key}"}}
    assert (await client.post("/lab/run", json=rejected)).status_code == 400 and not calls
    record = await run(lab, client, **body, inspect=True)
    request, = calls
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {key}"
    payload = json.loads(request.content)
    assert payload["model"] == GROQ_MODEL
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["messages"][-1]["content"] == body["request"]["message"]
    assert b"private session" not in request.content
    assert record["httpStatus"] == 200
    assert record["response"] == {"reply": "Walk to the park.", "places": []}
    response_event = next(e for e in record["events"] if e["stage"] == "model_response")
    assert response_event["data"]["content"] == {"summary": "Walk to the park."}
    assert response_event["data"]["usage"]["total_tokens"] == 60
    exported = (await client.get("/lab/export/" + record["id"])).text
    assert key not in exported and "private reasoning" not in exported and "Authorization" not in exported


@pytest.mark.parametrize("upstream,http_status,reason", [
    (401, 502, "http_status"), (429, 502, "http_status"),
    ("bad_json", 502, "structured_content"), ("blank_summary", 502, "schema_validation"),
    ("refused", 502, "model_refusal"), ("timeout", 504, "timeout"),
])
async def test_live_probe_reports_errors_without_fallback(groq_lab, upstream, http_status, reason):
    lab, client, calls, provider = groq_lab
    await client.post("/lab/keys", json={"provider": "groq", "value": "local-personal-key"})
    if upstream == "timeout":
        provider["response"] = httpx.ReadTimeout("private timeout")
    elif isinstance(upstream, int):
        provider["response"] = httpx.Response(upstream, json={"error": {"message": "private error"}})
    elif upstream == "refused":
        provider["response"] = httpx.Response(200, json={"choices": [{
            "finish_reason": "stop", "message": {"refusal": "private refusal"},
        }]})
    else:
        content = "invalid JSON" if upstream == "bad_json" else '{"summary":"   "}'
        provider["response"] = httpx.Response(200, json={"choices": [{
            "finish_reason": "stop", "message": {"content": content},
        }]})

    record = await run(lab, client, mode="groq")
    assert len(calls) == 1 and record["status"] == "failed" and record["httpStatus"] == http_status
    diagnostic = next(e["diagnostic"] for e in record["events"] if "diagnostic" in e)
    assert diagnostic["reason"] == reason
    if isinstance(upstream, int):
        assert diagnostic["http_status"] == upstream
    assert record["request"] is None and record["response"] is None
    assert not any("data" in e for e in record["events"])
    assert "private " not in json.dumps(record)


async def test_cancelling_live_probe_cancels_provider_call(groq_lab):
    lab, client, calls, provider = groq_lab
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def blocked():
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    provider["response"] = blocked
    await client.post("/lab/keys", json={"provider": "groq", "value": "local-personal-key"})
    response = await client.post("/lab/run", json={
        "mode": "groq", "request": {"sessionId": "s", "message": "Cancel me"},
    })
    assert response.status_code == 202
    await asyncio.wait_for(started.wait(), timeout=2)
    assert (await client.post("/lab/cancel")).status_code == 200
    assert cancelled.is_set() and len(calls) == 1
    assert lab.records.runs[-1]["status"] == "cancelled"


async def test_groq_quota_wait_survives_runs_and_resets_when_key_changes(groq_lab):
    lab, client, calls, provider = groq_lab
    key = "local-personal-key"
    await client.post("/lab/keys", json={"provider": "groq", "value": key})
    provider["response"].headers.update({
        "x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "20s",
    })
    first = await run(lab, client, mode="groq", inspect=True)
    assert first["httpStatus"] == 200 and len(calls) == 1
    assert any(e["stage"] == "model_queue" for e in first["events"])

    second = await run(lab, client, mode="groq", timeout_seconds=0.05)
    assert second["httpStatus"] == 504 and len(calls) == 1
    assert any(e["stage"] == "quota_wait" for e in second["events"])
    assert not any("data" in e for e in second["events"])

    await client.post("/lab/keys", json={"provider": "groq", "value": "different-personal-key"})
    third = await run(lab, client, mode="groq")
    assert third["httpStatus"] == 200 and len(calls) == 2
    assert calls[-1].headers["Authorization"] == "Bearer different-personal-key"
    assert not any("data" in e for e in third["events"])


def walk_reply(**fields):
    content = {"kind": "new_route", "language": "en", "start": None, "end": None, "stops": [], **fields}
    return httpx.Response(200, json={"choices": [{
        "finish_reason": "stop", "message": {"content": json.dumps(content)},
    }]})


async def test_walking_draft_survives_clarification_and_blocks_invented_mutations(groq_lab):
    lab, client, calls, provider = groq_lab
    await client.post("/lab/keys", json={"provider": "groq", "value": "local-personal-key"})
    # Groq incorrectly suggests the city. The qualified user target must survive.
    airport = {"original": "аэропорта Милана", "proposed_name": "Милан"}
    stop = {"original": "площадь Гарибальди", "proposed_name": "площадь Гарибальди"}
    museum = {"original": "Музей науки", "proposed_name": "Музей науки"}
    provider["response"] = walk_reply(start=airport, stops=[stop, stop], language="ru")
    first = await run(lab, client, mode="route_intent", inspect=True, request={
        "sessionId": "walk", "message": "Из аэропорта Милана в центр через площадь Гарибальди, затем снова площадь Гарибальди",
    })
    assert first["httpStatus"] == 200 and first["response"]["reply"] == "Где хочешь закончить прогулку?"
    schema = json.loads(calls[-1].content)["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["kind"]["enum"] == ["new_route", "clarification", "unsupported"]
    assert {"start", "end", "stops"} <= set(schema["required"])
    assert first["response"]["places"] == [] and "routeId" not in first["response"]

    provider["response"] = walk_reply(kind="clarification", start=museum, end=museum, language="ru")
    second = await run(lab, client, mode="route_intent", request={"sessionId": "walk", "message": "Музей науки"})
    assert second["httpStatus"] == 502 and lab.drafts.get("walk").pending == "end"

    provider["response"] = walk_reply(kind="clarification", end=museum, language="ru")
    isolated = await run(lab, client, mode="route_intent", request={"sessionId": "other", "message": "Музей науки"})
    assert isolated["httpStatus"] == 502
    completed = await run(lab, client, mode="route_intent", inspect=True, request={
        "sessionId": "walk", "message": "Музей науки",
    })
    assert completed["httpStatus"] == 200 and "routeId" not in completed["response"]
    draft = next(e["data"] for e in completed["events"] if e["stage"] == "route_draft")
    assert draft == {"start": airport, "end": museum, "stops": [stop, stop]}
    data = json.loads(json.loads(calls[-1].content)["messages"][-1]["content"])
    assert data == {"pending_endpoint": "end", "text": "Музей науки"}

    provider["response"] = walk_reply(start=airport)
    invented = await run(lab, client, mode="route_intent", request={"sessionId": "walk", "message": "Somewhere else"})
    assert invented["httpStatus"] == 502 and lab.drafts.get("walk").start.original == airport["original"]
    assert (await client.post("/lab/reset", json={})).status_code == 200
    assert lab.drafts.get("walk") is None


async def test_stop_limit_asks_for_a_shorter_route_without_saving_a_partial_draft(groq_lab):
    lab, client, _, provider = groq_lab
    await client.post("/lab/keys", json={"provider": "groq", "value": "local-personal-key"})

    def place(text):
        return {"original": text, "proposed_name": text}

    def message(text):
        return {"sessionId": "walk", "message": text}

    start = place("Letiska Košice")
    provider["response"] = walk_reply(start=start, language="sk")
    first = await run(lab, client, mode="route_intent", request=message("Pôjdem pešo z Letiska Košice."))
    assert first["httpStatus"] == 200

    old_draft = lab.drafts.get("walk")
    names = ["torilla", "puistossa", "kirjastossa", "kirkolla", "museossa", "satamassa"]
    provider["response"] = walk_reply(
        start=place("asemalta"), end=place("rantaan"), stops=[place(name) for name in names], language="fi",
    )
    turn = await run(lab, client, mode="route_intent", inspect=True, request=message(
        "Kävellään asemalta rantaan ja käydään torilla, puistossa, kirjastossa, kirkolla, museossa ja satamassa.",
    ))
    assert turn["httpStatus"] == 200
    assert turn["response"] == {
        "reply": "Kuvaile kävely uudelleen ja valitse enintään 5 välipysähdystä.", "places": [],
    }
    assert lab.drafts.get("walk") == old_draft
    assert not any(event["stage"] == "route_draft" for event in turn["events"])
    assert any("over_stop_limit" in event["message"] for event in turn["events"])

    provider["response"] = walk_reply(
        start=place("asemalta"), end=place("rantaan"), stops=[place(name) for name in names[:-1]], language="fi",
    )
    shorter = await run(lab, client, mode="route_intent", request=message(
        "Kävellään asemalta rantaan ja käydään torilla, puistossa, kirjastossa, kirkolla ja museossa.",
    ))
    assert shorter["httpStatus"] == 200
    assert [stop.original for stop in lab.drafts.get("walk").stops] == names[:-1]


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
    assert not any(c["available"] for c in status["capabilities"] if c["id"] in {"java", "research"})


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
