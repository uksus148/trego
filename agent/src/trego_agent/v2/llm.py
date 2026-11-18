"""Provider boundary for tasks that expect structured output."""

from contextlib import contextmanager
from typing import Protocol

import httpx

from trego_agent.llm import StructuredModel as ExistingModelClient
from trego_agent.structured_output import StructuredRequest
from trego_agent.v2.diagnostics import log, stage, trace_id


class StructuredModel(Protocol):
    async def complete(self, request: StructuredRequest) -> dict: ...


@contextmanager
def model_stage(name: str):
    if name == "quota_wait":
        log.info("trace=%s stage=quota_wait outcome=started", trace_id.get())
    with stage(name):
        yield


class GroqModel:
    def __init__(self, client: httpx.AsyncClient, key: str, timeout_seconds: float) -> None:
        self._client = ExistingModelClient(client, key, provider="groq", timeout_seconds=timeout_seconds,
                                           stage_context=model_stage)

    async def complete(self, request: StructuredRequest) -> dict:
        # The existing transport accepts the original task envelope and converts it
        # to Groq's strict JSON Schema request. V2 tasks speak only StructuredRequest.
        return await self._client.call({
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": request.messages,
            "tools": [{"name": request.operation, "input_schema": request.schema}],
            "tool_choice": {"name": request.operation},
        })
