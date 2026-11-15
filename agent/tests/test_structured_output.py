import json
from copy import deepcopy

import fakeredis.aioredis
import httpx
import pytest
from jsonschema import Draft202012Validator

from gopstop_agent.availability_models import Assessment
from gopstop_agent.intent import ClaudeIntentExtractor, IntentClarificationRequired, RouteIntent
from gopstop_agent.llm import ProviderError, ToolModel
from gopstop_agent.replies import Reply
from gopstop_agent.resolution_cache import CachedPlaceResolver
from gopstop_agent.resolver import ClaudePlaceResolver, ResolutionResult
from gopstop_agent.structured_output import strict_schema
from test_groq import completion, request_body
from test_resolution_cache import PLACE, SOURCES


@pytest.mark.parametrize("model", [RouteIntent, ResolutionResult, Reply, Assessment])
def test_each_task_has_a_closed_required_wire_schema_without_mutating_business_validation(model):
    original = model.model_json_schema()
    snapshot = deepcopy(original)
    wire = strict_schema(original)
    Draft202012Validator.check_schema(wire)

    def check(node):
        if isinstance(node, dict):
            assert not {"$ref", "$defs", "default", "maxItems"} & node.keys()
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"])
                assert node["additionalProperties"] is False
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(wire)
    assert original == snapshot


@pytest.mark.parametrize("model_id", ["openai/gpt-oss-20b", "openai/gpt-oss-120b"])
@pytest.mark.parametrize("case", ["incomplete", "too_many_stops", "too_many_preferences", "missing_field"])
async def test_intent_nulls_and_limits_are_validated_after_strict_extraction(model_id, case):
    value = {"start": None, "end": None, "mustSee": [], "preferences": []}
    if case == "too_many_stops":
        value["mustSee"] = [f"Stop {i}" for i in range(6)]
    elif case == "too_many_preferences":
        value["preferences"] = [f"Preference {i}" for i in range(13)]
    elif case == "missing_field":
        del value["end"]
    calls = []

    def handle(request):
        calls.append(request)
        schema = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        assert "maxItems" not in schema["properties"]["mustSee"]
        assert schema["properties"]["end"]["anyOf"][-1] == {"type": "null"}
        return httpx.Response(200, json=completion(value=value))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        extractor = ClaudeIntentExtractor(client, "fixture", model_id, tool_model=ToolModel(client, "fixture", "groq"))
        if case.startswith("too_many"):
            with pytest.raises(IntentClarificationRequired):
                await extractor.extract("A long hike", [])
        elif case == "missing_field":
            with pytest.raises(ProviderError) as caught:
                await extractor.extract("Incomplete", [])
            assert caught.value.diagnostic["reason"] == "schema_validation"
        else:
            assert (await extractor.extract("I would like to see a waterfall.", [])).model_dump() == {**value, "descriptiveTargets": []}
    assert len(calls) == 1


@pytest.mark.parametrize("case,reason", [("refusal", "model_refusal"), ("length", "incomplete_generation"),
                                      ("null", "structured_content"), ("fenced", "structured_content"),
                                      ("missing_tags", "schema_validation")])
async def test_strict_failures_never_replay_switch_provider_or_cache(caplog, case, reason):
    body = completion()
    message = body["choices"][0]["message"]
    if case == "refusal":
        message["refusal"] = "LEAK_PRIVATE_REASON"
    elif case == "length":
        body["choices"][0]["finish_reason"] = "length"
    elif case == "null":
        message["content"] = None
    elif case == "fenced":
        message["content"] = '```json\n{"place": null}\n```'
    else:
        message["content"] = json.dumps({"place": {k: v for k, v in PLACE.items() if k != "tags"}})
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        resolver = CachedPlaceResolver(ClaudePlaceResolver(client, "fixture", "openai/gpt-oss-20b",
                                       tool_model=ToolModel(client, "fixture", "groq")), cache)
        with pytest.raises(ProviderError) as caught:
            await resolver.resolve("Skok", SOURCES)
        assert caught.value.diagnostic["reason"] == reason
        assert await cache.keys("*") == []
    assert len(calls) == 1 and "LEAK" not in str(caught.value) + caplog.text


async def test_old_resolution_entries_cannot_mask_new_transport_and_remain_untouched():
    async with fakeredis.aioredis.FakeRedis() as cache, httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=completion()),
    )) as client:
        resolver = ClaudePlaceResolver(client, "fixture", "openai/gpt-oss-20b", tool_model=ToolModel(client, "fixture", "groq"))
        import hashlib
        old = {"provider": "groq", "request": resolver.request_body("Skok", SOURCES)}
        key = "gopstop:place-resolution:v1:" + hashlib.sha256(json.dumps(old, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        await cache.set(key, "null")
        assert await CachedPlaceResolver(resolver, cache).resolve("Skok", SOURCES) is not None
        assert await cache.get(key) == b"null"
        assert len(await cache.keys("gopstop:place-resolution:v3:*")) == 1


async def test_unknown_groq_model_fails_before_network():
    body = request_body()
    body["model"] = "unconfigured-model"
    with pytest.raises(ProviderError) as caught:
        await ToolModel(None, "fixture", "groq").call(body)
    assert caught.value.diagnostic["reason"] == "request_schema"
