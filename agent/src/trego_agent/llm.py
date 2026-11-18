"""One structured result over Groq JSON Schema or Anthropic tool use; no retries."""

import asyncio
import json
import re
import time
from collections.abc import Callable
from contextlib import AbstractContextManager

import httpx
from jsonschema import Draft202012Validator, SchemaError, ValidationError as SchemaValidationError

from trego_agent.config import Settings
from trego_agent.structured_output import StructuredRequest
from trego_agent.diagnostics import stage
from trego_agent.provider_errors import ProviderError, ProviderTimeout, http_failure


RATE_LIMIT_REPLAYS = 2
MAX_RETRY_AFTER_SECONDS = 60.0


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Per-minute input/output limits are not all visible in the advisory quota headers."""
    if response.status_code != 429:
        return None
    try:
        seconds = float(response.headers.get("retry-after", "")[:32])
    except ValueError:
        return None
    return seconds if 0 <= seconds <= MAX_RETRY_AFTER_SECONDS else None


class StructuredModel:
    def __init__(self, client: httpx.AsyncClient, key: str, provider: str = "anthropic",
                 timeout_seconds: float = 20, *,
                 stage_context: Callable[[str], AbstractContextManager[None]] = stage) -> None:
        if provider not in ("anthropic", "groq"):
            raise ValueError("Unknown LLM provider.")
        self.provider, self._client, self._key = provider, client, key
        self._timeout = httpx.Timeout(timeout_seconds)
        self._stage = stage_context
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
        with self._stage("model"):
            return await self._call(body)

    def prepare(self, body: dict) -> dict:
        """The exact credential-free payload used by both transport and cache identity."""
        try:
            return StructuredRequest.from_tool_request(body).groq_payload() if self.provider == "groq" else body
        except (ValueError, KeyError, TypeError, AttributeError, SchemaError) as exc:
            raise ProviderError("Model request is temporarily unavailable.", provider=self.provider,
                                operation=body.get("tool_choice", {}).get("name"), reason="request_schema") from exc

    async def _call(self, body: dict) -> dict:
        name = body.get("tool_choice", {}).get("name")
        diagnostic = {"provider": self.provider, "operation": name}
        reason = "request_schema"
        try:
            if self.provider == "groq":
                payload = self.prepare(body)
                validator = Draft202012Validator(payload["response_format"]["json_schema"]["schema"])
                # Shared by intent/resolution/reply in one worker. Outer chat/discovery
                # deadlines include waiting. A rejected 429 generated nothing, so it is replayed
                # only when the provider states a short Retry-After; other failures never are.
                with self._stage("model_queue"):
                    await self._lock.acquire()
                try:
                    encoded = json.dumps(payload, ensure_ascii=False)
                    estimate = max(len(encoded) // 2, len(encoded.encode()) // 3) + payload["max_completion_tokens"]
                    if self._remaining is not None and self._remaining < estimate:
                        with self._stage("quota_wait"):
                            await asyncio.sleep(max(0, self._reset - time.monotonic()))
                    for replay in range(RATE_LIMIT_REPLAYS + 1):
                        response = await self._client.post(
                            "https://api.groq.com/openai/v1/chat/completions", json=payload,
                            headers={"Authorization": f"Bearer {self._key}"},
                            timeout=self._timeout, follow_redirects=False,
                        )
                        self._record_quota(response)
                        wait = retry_after_seconds(response)
                        if wait is None or replay == RATE_LIMIT_REPLAYS:
                            break
                        with self._stage("quota_wait"):
                            await asyncio.sleep(wait)
                    if response.is_error or response.is_redirect:
                        raise http_failure(response, **diagnostic)
                finally:
                    self._lock.release()
                diagnostic["status"] = response.status_code
                reason = "response_json"
                choices = response.json()["choices"]
                if len(choices) != 1:
                    raise ProviderError("Model returned an unexpected response.", reason="response_json", **diagnostic)
                diagnostic["finish"] = choices[0]["finish_reason"]
                message = choices[0]["message"]
                if message.get("refusal") or diagnostic["finish"] in ("refusal", "content_filter"):
                    raise ProviderError("Model declined structured extraction.", reason="model_refusal", **diagnostic)
                if diagnostic["finish"] != "stop":
                    raise ProviderError("Model generation did not complete.", reason="incomplete_generation", **diagnostic)
                if message.get("tool_calls"):
                    raise ProviderError("Model returned an unexpected tool.", reason="unexpected_tool", **diagnostic)
                reason = "structured_content"
                result = json.loads(message["content"])
                try:
                    validator.validate(result)
                except SchemaValidationError as exc:
                    raise ProviderError("Model returned invalid structured data.",
                                        reason="schema_validation", **diagnostic) from exc
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
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, SchemaError) as exc:
            raise ProviderError("Model request is temporarily unavailable.", reason=reason, **diagnostic) from exc


# Existing task constructors share this exact implementation and quota gate.
ToolModel = StructuredModel


def create_tool_model(client: httpx.AsyncClient, settings: Settings) -> ToolModel:
    return ToolModel(client, settings.llm_key.get_secret_value(), settings.llm_provider,
                     settings.provider_timeout_seconds)
