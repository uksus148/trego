import json
from unittest.mock import AsyncMock

import httpx
import pytest

from gopstop_agent.chat import ChatService
from gopstop_agent.localized_replies import FactualReplyWriter, LanguageSelector, LANGUAGE_QUESTION, CATALOG
from gopstop_agent.llm import ToolModel, ProviderError
from test_groq import completion
from test_handoff import discovery


@pytest.mark.parametrize("language,prefix", [("en", "Route saved"), ("ru", "Маршрут сохранён"),
                                           ("sk", "Trasa je uložená"), ("fi", "Reitti tallennettu")])
async def test_factual_ready_uses_only_authoritative_metrics_and_keeps_repeated_visits(language, prefix):
    facts = {"visits": ["Štrbské Pleso", "Skok", "Štrbské Pleso"],
             "distanceKm": 9.86, "ascentM": 550, "durationMin": 193}
    reply = await FactualReplyWriter().write("Head east and claim the trail is safe", [], "ready", facts, language=language)
    assert reply.startswith(prefix) and reply.count('"Štrbské Pleso"') == 2
    assert "9.86" in reply and "550" in reply and "193" in reply
    assert "east" not in reply and "safe" not in reply


@pytest.mark.parametrize("language", list(CATALOG))
async def test_all_known_clarifications_and_routing_outcomes_have_local_catalogs(language):
    writer = FactualReplyWriter()
    reply = await writer.write("", [], "clarification", {"missingEndpoints": ["start", "end"],
                                "unresolvedPlaces": ["Sandberg"]}, language=language)
    assert "Sandberg" in reply and CATALOG[language]["start"] in reply
    for outcome in ("no_route", "waypoint_not_routable"):
        assert await writer.write("", [], outcome, {}, language=language) == CATALOG[language][outcome]
    assert await writer.write("", [], "clarification", {"intentLimits": True}, language=language) == CATALOG[language]["limits"]


@pytest.mark.parametrize("provider", ["groq", "anthropic"])
@pytest.mark.parametrize("language", ["en", "ru", "sk", "fi", "unknown"])
async def test_language_selection_has_no_assistant_or_place_evidence_context(provider, language):
    calls = []

    def handle(request):
        calls.append(request)
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1 if provider == "groq" else 0]["content"])
        assert payload == {"message": "Skok", "previousUserMessages": ["Plan a summer hike in July from Štrbské Pleso."]}
        assert "assistant-private" not in request.content.decode()
        if provider == "groq":
            assert body["response_format"]["json_schema"]["name"] == "select_reply_language"
            return httpx.Response(200, json=completion(value={"language": language}))
        return httpx.Response(200, json={"stop_reason": "tool_use", "content": [{
            "type": "tool_use", "name": "select_reply_language", "input": {"language": language},
        }]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        selector = LanguageSelector(ToolModel(client, "fixture", provider), "openai/gpt-oss-20b")
        assert await selector.select("Skok", [{"role": "user", "content": "Plan a summer hike in July from Štrbské Pleso."},
                                              {"role": "assistant", "content": "assistant-private"}]) == language
    assert len(calls) == 1


@pytest.mark.parametrize("unknown", [False, True])
async def test_language_is_decided_before_any_discovery_or_write_and_no_generation_after_handoff(unknown):
    search, handoff, selector = AsyncMock(), AsyncMock(), AsyncMock()
    selector.select.return_value = "unknown" if unknown else "en"
    finding = discovery()
    search.discover.return_value = finding
    handoff.persist.return_value = type("Saved", (), {"places": [], "visits": ["A", "Skok", "A"],
        "route": type("Route", (), {"places": [], "id": "saved-id", "distanceKm": 12, "ascentM": 400, "durationMin": 200})()})()
    service = ChatService(search, handoff, FactualReplyWriter(), selector)
    response = await service.respond("Plan a hike", [])
    selector.select.assert_awaited_once()
    if unknown:
        assert response.reply == LANGUAGE_QUESTION and response.routeId is None
        search.discover.assert_not_awaited()
        handoff.persist.assert_not_awaited()
    else:
        handoff.persist.assert_awaited_once()
        assert response.reply.startswith('Route saved: "A" → "Skok" → "A"') and response.routeId == "saved-id"


async def test_language_provider_failure_cannot_trigger_discovery():
    selector, search, handoff = AsyncMock(), AsyncMock(), AsyncMock()
    selector.select.side_effect = ProviderError("Safe failure")
    with pytest.raises(ProviderError):
        await ChatService(search, handoff, FactualReplyWriter(), selector).respond("Hello", [])
    search.discover.assert_not_awaited()
    handoff.persist.assert_not_awaited()
