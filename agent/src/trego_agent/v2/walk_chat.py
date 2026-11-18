"""Apply one walking request to a session draft and choose the next reply."""

from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from trego_agent.provider_errors import ProviderError
from trego_agent.v2.diagnostics import log, stage, trace_id
from trego_agent.v2.models import ChatRequest, ChatResponse
from trego_agent.v2.route_intent import MAX_STOPS, OPERATION, PendingQuestion, PlaceMention, WalkIntentExtractor

REPLIES = {
    "en": {
        "start": "Where should the walk start?",
        "end": "Where would you like to finish the walk?",
        "ready": "Captured the start, destination and any stops.",
        "unsupported": "Describe the walk you want to plan.",
        "over_limit": f"Please describe the walk again with at most {MAX_STOPS} intermediate stops.",
    },
    "ru": {
        "start": "Откуда начнём прогулку?",
        "end": "Где хочешь закончить прогулку?",
        "ready": "Записал начало, конец и указанные остановки.",
        "unsupported": "Опиши прогулку, которую хочешь спланировать.",
        "over_limit": f"Опиши прогулку ещё раз, указав максимум {MAX_STOPS} промежуточных остановок.",
    },
    "sk": {
        "start": "Kde má prechádzka začať?",
        "end": "Kde chceš prechádzku ukončiť?",
        "ready": "Zaznamenal som začiatok, cieľ a uvedené zastávky.",
        "unsupported": "Opíš prechádzku, ktorú chceš naplánovať.",
        "over_limit": f"Opíš prechádzku znova s najviac {MAX_STOPS} zastávkami medzi štartom a cieľom.",
    },
    "fi": {
        "start": "Mistä kävelyn pitäisi alkaa?",
        "end": "Mihin haluat päättää kävelyn?",
        "ready": "Kirjasin aloituspaikan, määränpään ja annetut pysähdykset.",
        "unsupported": "Kuvaile kävelyä, jonka haluat suunnitella.",
        "over_limit": f"Kuvaile kävely uudelleen ja valitse enintään {MAX_STOPS} välipysähdystä.",
    },
}


class WalkDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: PlaceMention | None
    end: PlaceMention | None
    stops: tuple[PlaceMention, ...]

    @property
    def pending(self) -> PendingQuestion | None:
        if self.start is None:
            return "start"
        if self.end is None:
            return "end"
        return None


class DraftStore(Protocol):
    def get(self, session_id: str) -> WalkDraft | None: ...

    def save(self, session_id: str, draft: WalkDraft) -> None: ...


def invalid_action() -> ProviderError:
    return ProviderError("Invalid walking intent action.", operation=OPERATION, reason="invalid_intent_action")


class WalkChatService:
    def __init__(
        self, extractor: WalkIntentExtractor, drafts: DraftStore,
        on_draft: Callable[[WalkDraft], None] | None = None,
    ) -> None:
        self.extractor = extractor
        self.drafts = drafts
        self.on_draft = on_draft

    async def respond(self, request: ChatRequest) -> ChatResponse:
        draft = self.drafts.get(request.sessionId)
        pending = draft.pending if draft is not None else None
        intent = await self.extractor.extract(request.message, pending)
        replies = REPLIES[intent.language]

        with stage("conversation"):
            if intent.kind == "unsupported":
                if intent.start or intent.end or intent.stops:
                    raise invalid_action()
                return ChatResponse(reply=replies["unsupported"])
            if intent.kind == "new_route":
                if len(intent.stops) > MAX_STOPS:
                    log.info("trace=%s stage=conversation outcome=over_stop_limit", trace_id.get())
                    return ChatResponse(reply=replies["over_limit"])
                updated = WalkDraft(start=intent.start, end=intent.end, stops=tuple(intent.stops))
            else:
                if draft is None or pending is None or intent.stops:
                    raise invalid_action()
                other = intent.end if pending == "start" else intent.start
                if other is not None:
                    raise invalid_action()
                updated = draft.model_copy(update={pending: getattr(intent, pending)})

            self.drafts.save(request.sessionId, updated)
            if self.on_draft is not None:
                self.on_draft(updated)
            return ChatResponse(reply=replies[updated.pending or "ready"])
