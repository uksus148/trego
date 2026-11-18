"""Provider boundary for tasks that expect structured output."""

from typing import Protocol

import httpx

from trego_agent.llm import StructuredModel as ExistingModelClient
from trego_agent.structured_output import StructuredRequest


class StructuredModel(Protocol):
    async def complete(self, request: StructuredRequest) -> dict: ...


class GroqModel:
    def __init__(self, client: httpx.AsyncClient, key: str, timeout_seconds: float) -> None:
        self._client = ExistingModelClient(client, key, provider="groq", timeout_seconds=timeout_seconds)

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
