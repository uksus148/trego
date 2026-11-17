"""The smallest replaceable chat operation; no interpretation or storage yet."""

from typing import Protocol

from gopstop_agent.v2.models import ChatRequest, ChatResponse


class ChatService(Protocol):
    async def respond(self, request: ChatRequest) -> ChatResponse: ...


class FixtureChatService:
    async def respond(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(reply=(
            "[LOCAL FIXTURE] The v2 request handler is running. "
            "No model, place research, route planning or session storage is connected."
        ))
