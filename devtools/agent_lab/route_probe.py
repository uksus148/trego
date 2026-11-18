"""Compose one walking intent flow with temporary per-session drafts."""

from collections import OrderedDict
from collections.abc import Callable

from trego_agent.provider_errors import ProviderError
from trego_agent.v2.models import ChatRequest, ChatResponse
from trego_agent.v2.route_intent import WalkDraft, WalkIntentExtractor

REPLIES = {
    "en": ("Where should the walk start?", "Where would you like to finish the walk?",
           "Captured the start, destination and any stops.", "Describe the walk you want to plan."),
    "ru": ("Откуда начнём прогулку?", "Где хочешь закончить прогулку?",
           "Записал начало, конец и указанные остановки.", "Опиши прогулку, которую хочешь спланировать."),
    "sk": ("Kde má prechádzka začať?", "Kde chceš prechádzku ukončiť?",
           "Zaznamenal som začiatok, cieľ a uvedené zastávky.", "Opíš prechádzku, ktorú chceš naplánovať."),
    "fi": ("Mistä kävelyn pitäisi alkaa?", "Mihin haluat päättää kävelyn?",
           "Kirjasin aloituspaikan, määränpään ja annetut pysähdykset.", "Kuvaile kävelyä, jonka haluat suunnitella."),
}
MAX_DRAFTS = 20


class RouteProbe:
    def __init__(self, extractor: WalkIntentExtractor, drafts: OrderedDict[str, WalkDraft],
                 emit: Callable[[dict], None], inspect: bool) -> None:
        self.extractor = extractor
        self.drafts = drafts
        self.emit = emit
        self.inspect = inspect

    async def respond(self, request: ChatRequest) -> ChatResponse:
        try:
            intent, draft = await self.extractor.extract(request.message, self.drafts.get(request.sessionId))
        except ProviderError as exc:
            self.emit({"level": "ERROR", "stage": "intent", "message": "Walking intent extraction failed.",
                       "diagnostic": exc.diagnostic})
            raise
        ask_start, ask_end, complete, unsupported = REPLIES[intent.language]
        if intent.kind == "unsupported":
            return ChatResponse(reply=unsupported)
        assert draft is not None
        pending = draft.pending
        response = ChatResponse(reply={"start": ask_start, "end": ask_end, None: complete}[pending])
        event = {"stage": "route_draft", "message": "Walking draft updated.", "pending": pending}
        if self.inspect:
            event["data"] = draft.model_dump(mode="json")
        self.emit(event)
        self.drafts[request.sessionId] = draft
        self.drafts.move_to_end(request.sessionId)
        if len(self.drafts) > MAX_DRAFTS:
            self.drafts.popitem(last=False)
        return response
