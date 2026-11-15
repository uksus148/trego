import asyncio
import json
import logging

import fakeredis.aioredis
import httpx
import pytest

from gopstop_agent.diagnostics import stage, trace
from gopstop_agent.exa import ExaSearch
from gopstop_agent.llm import ProviderError, ProviderTimeout, ToolModel
from gopstop_agent.resolution_cache import CachedPlaceResolver
from gopstop_agent.resolver import ClaudePlaceResolver
from test_groq import completion, request_body
from test_resolution_cache import PLACE, SOURCES


@pytest.mark.parametrize("failure,reason,status,code", [
    (400, "http_status", 400, "tool_use_failed"),
    (429, "http_status", 429, "rate_limit_exceeded"),
    (401, "http_status", 401, "invalid_api_key"),
    (503, "http_status", 503, "unknown"),
    ("timeout", "timeout", None, None),
    ("connect", "transport", None, None),
    ("json", "response_json", 200, None),
    ("length", "incomplete_generation", 200, None),
    ("finish", "incomplete_generation", 200, None),
    ("tool", "unexpected_tool", 200, None),
    ("arguments", "structured_content", 200, None),
    ("schema", "schema_validation", 200, None),
    ("source", "invalid_source_index", None, None),
])
async def test_resolution_preserves_safe_cause_without_retry_or_caching(caplog, failure, reason, status, code):
    calls = []
    secret = "LEAK_PRIVATE_CONTENT"

    def handle(request):
        calls.append(request)
        if type(failure) is int:
            return httpx.Response(failure, json={"error": {
                "code": code if code != "unknown" else secret, "message": secret,
                "failed_generation": secret,
            }})
        if failure == "timeout":
            raise httpx.ReadTimeout(secret)
        if failure == "connect":
            raise httpx.ConnectError(secret)
        if failure == "json":
            return httpx.Response(200, text=secret)
        body = completion()
        choice = body["choices"][0]
        message = choice["message"]
        if failure in ("length", "finish"):
            choice["finish_reason"] = "length" if failure == "length" else secret
        elif failure == "tool":
            message["tool_calls"] = [{"name": secret}]
        elif failure == "arguments":
            message["content"] = secret
        elif failure == "schema":
            message["content"] = json.dumps({"place": {**PLACE, "sourceIndex": secret, secret: secret}})
        elif failure == "source":
            message["content"] = json.dumps({"place": {**PLACE, "sourceIndex": 1}})
        return httpx.Response(200, json=body)

    caplog.set_level(logging.INFO, logger="gopstop_agent.diagnostics")
    async with fakeredis.aioredis.FakeRedis() as cache:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            resolver = CachedPlaceResolver(ClaudePlaceResolver(
                client, secret, "openai/gpt-oss-20b", tool_model=ToolModel(client, secret, "groq")), cache)
            with pytest.raises(ProviderError) as caught, trace(secret), stage("resolution"):
                await resolver.resolve(secret, SOURCES)
        assert await cache.keys("*") == []
    assert len(calls) == 1
    assert isinstance(caught.value, ProviderTimeout) == (failure == "timeout")
    diagnostic = caught.value.diagnostic
    assert diagnostic["reason"] == reason and diagnostic["provider"] == "groq"
    assert diagnostic["operation"] == "resolve_place"
    assert diagnostic.get("http_status") == status and diagnostic.get("provider_code") == code
    line, = [record for record in caplog.records if "stage=resolution " in record.message]
    assert line.levelno == logging.WARNING and f"reason={reason}" in line.message
    assert secret not in caplog.text and secret not in str(caught.value)
    assert all(record.exc_info is None for record in caplog.records)
    if failure == "schema":
        assert "reason=schema_validation" in line.message


@pytest.mark.parametrize("provider", ["anthropic", "exa"])
@pytest.mark.parametrize("body", [
    {"error": {"type": "overloaded_error", "message": "LEAK"}},
    {"error": {"code": ["LEAK"]}},
    {"error": "LEAK"},
    ["LEAK"],
    {"error": {"code": "tool_use_failed", "message": "LEAK" * 3000}},
])
async def test_non_groq_http_errors_parse_only_bounded_allowlisted_envelopes(provider, body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(503, json=body),
    )) as client:
        with pytest.raises(ProviderError) as caught:
            if provider == "exa":
                await ExaSearch(client, None, "LEAK").search("LEAK", use_cache=False)
            else:
                await ToolModel(client, "LEAK").call(request_body())
    diagnostic = caught.value.diagnostic
    assert diagnostic["provider"] == provider and diagnostic["http_status"] == 503
    assert diagnostic["provider_code"] == ("overloaded_error" if body == {
        "error": {"type": "overloaded_error", "message": "LEAK"},
    } else "unknown")
    assert "LEAK" not in str(diagnostic)


async def test_queue_deadline_is_cancellation_not_provider_http_failure(caplog):
    caplog.set_level(logging.INFO, logger="gopstop_agent.diagnostics")
    model = ToolModel(None, "LEAK", "groq")
    await model._lock.acquire()
    try:
        with trace("LEAK"), stage("chat"), pytest.raises(TimeoutError):
            async with asyncio.timeout(.01):
                await model.call(request_body())
    finally:
        model._lock.release()
    assert "stage=model_queue" in caplog.text and "reason=cancelled" in caplog.text
    assert "http_status" not in caplog.text and "LEAK" not in caplog.text


@pytest.mark.parametrize("status", [200, 400])
async def test_invalid_quota_headers_cannot_hide_the_primary_http_failure(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        status, json=completion() if status == 200 else {"error": {"code": "tool_use_failed"}},
        headers={"x-ratelimit-remaining-tokens": bytes([178]), "x-ratelimit-reset-tokens": "LEAK"},
    ))) as client:
        model = ToolModel(client, "LEAK", "groq")
        if status == 200:
            assert await model.call(request_body()) == {"place": PLACE}
        else:
            with pytest.raises(ProviderError) as caught:
                await model.call(request_body())
            assert caught.value.diagnostic["http_status"] == 400
            assert caught.value.diagnostic["provider_code"] == "tool_use_failed"
