"""One validated tool result over Anthropic or Groq, without automatic retries."""

import asyncio
import json
import re
import time

import httpx

from gopstop_agent.config import Settings
from gopstop_agent.diagnostics import stage
from gopstop_agent.provider_errors import ProviderError, ProviderTimeout, http_failure


def inline_tool_schema(schema: dict) -> dict:
    """Expand acyclic Pydantic definitions for Groq's function parameters."""
    definitions = schema.get("$defs", {})

    def expand(value, active=()):
        if isinstance(value, list):
            return [expand(item, active) for item in value]
        if not isinstance(value, dict):
            return value
        siblings = {key: expand(item, active) for key, item in value.items()
                    if key not in ("$defs", "$ref")}
        if "$ref" not in value:
            return siblings
        ref = value["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref in active:
            raise ValueError("Unsupported or recursive tool schema reference.")
        definition = definitions[ref.removeprefix("#/$defs/")]
        resolved = expand(definition, (*active, ref))
        # A $ref and its sibling constraints both apply; do not overwrite either.
        return {"allOf": [resolved, siblings]} if siblings else resolved

    return expand(schema)


class ToolModel:
    def __init__(self, client: httpx.AsyncClient, key: str, provider: str = "anthropic",
                 timeout_seconds: float = 20) -> None:
        if provider not in ("anthropic", "groq"):
            raise ValueError("Unknown LLM provider.")
        self.provider, self._client, self._key = provider, client, key
        self._timeout = httpx.Timeout(timeout_seconds)
        self._lock = asyncio.Lock()
        self._remaining, self._reset = None, 0.0

    def _record_quota(self, response: httpx.Response) -> None:
        # Advisory headers must never hide the primary HTTP/model result.
        remaining = response.headers.get("x-ratelimit-remaining-tokens", "")[:128]
        reset = response.headers.get("x-ratelimit-reset-tokens", "")[:128]
        try:
            self._remaining = int(remaining) if remaining.isdigit() else None
            seconds = sum(float(n) * {"ms": .001, "s": 1, "m": 60, "h": 3600}[unit]
                          for n, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", reset))
            self._reset = time.monotonic() + seconds
        except ValueError:
            self._remaining, self._reset = None, 0.0

    async def call(self, body: dict) -> dict:
        with stage("model"):
            return await self._call(body)

    async def _call(self, body: dict) -> dict:
        name = body.get("tool_choice", {}).get("name")
        diagnostic = {"provider": self.provider, "operation": name}
        reason = "request_schema"
        try:
            if self.provider == "groq":
                payload = {
                    "model": body["model"], "max_completion_tokens": max(2048, body["max_tokens"]),
                    "messages": [{"role": "system", "content": body["system"]}, *body["messages"]],
                    "tools": [{"type": "function", "function": {
                        "name": tool["name"], "description": tool["description"],
                        "parameters": inline_tool_schema(tool["input_schema"]),
                    }} for tool in body["tools"]],
                    "tool_choice": {"type": "function", "function": {"name": name}},
                    "parallel_tool_calls": False,
                }
                if body["model"].startswith("openai/gpt-oss-"):
                    payload["reasoning_effort"] = "low"
                # Shared by intent/resolution/reply in one worker. Outer chat/discovery
                # deadlines include waiting; 429 responses are never replayed.
                with stage("model_queue"):
                    await self._lock.acquire()
                try:
                    encoded = json.dumps(payload, ensure_ascii=False)
                    estimate = max(len(encoded) // 2, len(encoded.encode()) // 3) + payload["max_completion_tokens"]
                    if self._remaining is not None and self._remaining < estimate:
                        with stage("quota_wait"):
                            await asyncio.sleep(max(0, self._reset - time.monotonic()))
                    response = await self._client.post(
                        "https://api.groq.com/openai/v1/chat/completions", json=payload,
                        headers={"Authorization": f"Bearer {self._key}"},
                        timeout=self._timeout, follow_redirects=False,
                    )
                    self._record_quota(response)
                    if response.is_error or response.is_redirect:
                        raise http_failure(response, **diagnostic)
                finally:
                    self._lock.release()
                diagnostic["status"] = response.status_code
                reason = "response_json"
                choices = response.json()["choices"]
                if len(choices) != 1:
                    raise ProviderError("Model returned an unexpected tool.", reason="unexpected_tool", **diagnostic)
                diagnostic["finish"] = choices[0]["finish_reason"]
                if diagnostic["finish"] not in ("tool_calls", "stop"):
                    raise ProviderError("Model tool generation did not complete.", reason="incomplete_generation", **diagnostic)
                calls = choices[0]["message"]["tool_calls"]
                if len(calls) != 1 or calls[0]["type"] != "function" or calls[0]["function"]["name"] != name:
                    raise ProviderError("Model returned an unexpected tool.", reason="unexpected_tool", **diagnostic)
                reason = "tool_arguments"
                result = json.loads(calls[0]["function"]["arguments"])
            else:
                response = await self._client.post(
                    "https://api.anthropic.com/v1/messages", json=body,
                    headers={"x-api-key": self._key, "anthropic-version": "2023-06-01"},
                    timeout=self._timeout, follow_redirects=False,
                )
                if response.is_error or response.is_redirect:
                    raise http_failure(response, **diagnostic)
                diagnostic["status"] = response.status_code
                reason = "response_json"
                data = response.json()
                diagnostic["finish"] = data.get("stop_reason")
                calls = [item for item in data["content"] if item.get("type") == "tool_use"]
                if data.get("stop_reason") != "tool_use":
                    raise ProviderError("Model tool generation did not complete.", reason="incomplete_generation", **diagnostic)
                if len(calls) != 1 or calls[0]["name"] != name:
                    raise ProviderError("Model returned an unexpected tool.", reason="unexpected_tool", **diagnostic)
                result = calls[0]["input"]
            if not isinstance(result, dict):
                raise ProviderError("Model tool input must be an object.", reason="tool_arguments", **diagnostic)
            return result
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("Model request is temporarily unavailable (timeout).",
                                  reason="timeout", timeout=type(exc).__name__, **diagnostic) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Model request is temporarily unavailable.", reason="transport", **diagnostic) from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderError("Model request is temporarily unavailable.", reason=reason, **diagnostic) from exc


def create_tool_model(client: httpx.AsyncClient, settings: Settings) -> ToolModel:
    return ToolModel(client, settings.llm_key.get_secret_value(), settings.llm_provider,
                     settings.provider_timeout_seconds)
