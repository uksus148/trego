import asyncio
import json
import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from gopstop_agent.config import Settings
from gopstop_agent.probe_resolution import main, run_probe
from test_groq import completion
from test_resolution_cache import PLACE


@pytest.mark.parametrize("outcome", ["resolved", "unresolved", "empty", "exa_http", "groq_http", "schema", "deadline"])
async def test_probe_is_uncached_read_only_and_reports_redacted_failure(caplog, outcome):
    requests = []
    secret = "LEAK_PRIVATE_QUERY_AND_KEY"

    async def handle(request):
        requests.append(request)
        assert request.method == "POST"
        if request.url.host == "api.exa.ai":
            assert json.loads(request.content)["query"] == secret
            if outcome == "exa_http":
                return httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": secret}})
            if outcome == "deadline":
                await asyncio.sleep(5)
            return httpx.Response(200, json={"results": [] if outcome == "empty" else [
                {"url": "https://private.example/evidence", "title": secret, "text": secret},
            ]})
        assert request.url.host == "api.groq.com"  # Java/ORS/Nominatim are forbidden.
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["name"] == "resolve_place"
        if outcome == "groq_http":
            return httpx.Response(400, json={"error": {"code": "tool_use_failed", "failed_generation": secret}})
        return httpx.Response(200, json=completion(value={
            "place": None if outcome == "unresolved" else {secret: secret} if outcome == "schema" else PLACE,
        }))

    settings = Settings(_env_file=None, llm_provider="groq", groq_api_key=secret, exa_api_key=secret,
                        discovery_timeout_seconds=.02 if outcome == "deadline" else 5)
    caplog.set_level(logging.INFO, logger="gopstop_agent.diagnostics")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        # Repeated probes still make fresh Exa + model calls. Nothing populates a shared cache.
        reports = [await run_probe(settings, client, secret) for _ in range(2)]
    failure = outcome in ("exa_http", "groq_http", "schema", "deadline")
    assert all(report["status"] == ("failed" if failure else "resolved" if outcome == "resolved" else "unresolved")
               for report in reports)
    assert len({report["traceId"] for report in reports}) == 2
    assert len(requests) == (2 if outcome in ("empty", "exa_http", "deadline") else 4)
    assert secret not in json.dumps(reports) and secret not in caplog.text
    assert "private.example" not in json.dumps(reports) + caplog.text
    assert all(isinstance(report["elapsedMs"], int) for report in reports)
    if outcome == "groq_http":
        assert reports[0]["error"]["provider_code"] == "tool_use_failed"
        assert reports[0]["error"]["http_status"] == 400
    if outcome == "deadline":
        assert reports[0]["error"]["reason"] == "discovery_deadline"


@pytest.mark.parametrize("status,exit_code", [("resolved", 0), ("unresolved", 0), ("failed", 1)])
def test_probe_cli_exit_status_and_json(monkeypatch, capsys, status, exit_code):
    monkeypatch.setattr("sys.argv", ["probe", "--query", "LEAK"])
    monkeypatch.setattr("gopstop_agent.probe_resolution._main", AsyncMock(return_value={"status": status}))
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == exit_code
    assert json.loads(capsys.readouterr().out) == {"status": status}


def test_probe_cli_does_not_print_configuration_validation_secrets(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["probe", "--query", "LEAK"])
    monkeypatch.setattr("gopstop_agent.probe_resolution._main", AsyncMock(side_effect=ValueError("LEAK")))
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 1
    output = capsys.readouterr()
    assert "invalid_configuration" in output.out and "LEAK" not in output.out + output.err


@pytest.mark.parametrize("model_id", ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"])
@pytest.mark.parametrize("failure", [False, True])
async def test_intent_probe_makes_exactly_one_model_call_without_research_or_writes(model_id, failure):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "api.groq.com"
        body = json.loads(request.content)
        assert body["model"] == model_id
        assert body["response_format"]["json_schema"]["name"] == "extract_route_intent"
        if failure:
            return httpx.Response(400, json={"error": {"code": "tool_use_failed", "message": "LEAK"}})
        return httpx.Response(200, json=completion(value={"start": None, "end": None, "mustSee": [], "preferences": []}))

    settings = Settings(_env_file=None, llm_provider="groq", groq_model=model_id, groq_api_key="LEAK", exa_api_key="LEAK")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        report = await run_probe(settings, client, "I would like to see a waterfall.", intent_only=True)
    assert report["stage"] == "intent" and len(requests) == 1
    assert report["status"] == ("failed" if failure else "needs_clarification")
    assert "LEAK" not in json.dumps(report)
    if not failure:
        assert report["missingEndpoints"] == ["start", "end"]
