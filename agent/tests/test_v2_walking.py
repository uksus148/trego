"""Exercise the real walking workflow through its replaceable model boundary."""

import pytest

from trego_agent.provider_errors import ProviderError
from trego_agent.structured_output import StructuredRequest
from trego_agent.v2.models import ChatRequest
from trego_agent.v2.route_intent import WalkIntentExtractor
from trego_agent.v2.walk_chat import WalkChatService, WalkDraft


class ScriptedModel:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = iter(responses)

    async def complete(self, request: StructuredRequest) -> dict:
        return next(self.responses)


class MemoryStore:
    def __init__(self) -> None:
        self.drafts: dict[str, WalkDraft] = {}

    def get(self, session_id: str) -> WalkDraft | None:
        return self.drafts.get(session_id)

    def save(self, session_id: str, draft: WalkDraft) -> None:
        self.drafts[session_id] = draft


@pytest.mark.parametrize(("stop_fields", "reason"), [
    ({"stops": "Market Square"}, "schema_validation"),
    ({"stops": [{"original": "Market Square", "proposed_name": "Market Square"}]}, "invalid_intent_action"),
])
async def test_invalid_model_output_cannot_overwrite_pending_draft(stop_fields, reason):
    model = ScriptedModel([
        {"kind": "new_route", "language": "en", "start": {
            "original": "Turku Airport", "proposed_name": "Turku",
        }, "end": None, "stops": []},
        {"kind": "clarification", "language": "en", "start": None, "end": {
            "original": "Market Square", "proposed_name": "Market Square",
        }, **stop_fields},
    ])
    store = MemoryStore()
    service = WalkChatService(WalkIntentExtractor(model, "test-model"), store)
    reply = await service.respond(ChatRequest(sessionId="walk", message="I want to walk from Turku Airport."))
    original = store.drafts["walk"]
    assert reply.reply == "Where would you like to finish the walk?"
    assert original.start.original == "Turku Airport"
    assert original.start.proposed_name == "Turku"

    with pytest.raises(ProviderError) as rejected:
        await service.respond(ChatRequest(sessionId="walk", message="Market Square"))
    assert rejected.value.diagnostic["reason"] == reason
    assert store.drafts["walk"] == original
