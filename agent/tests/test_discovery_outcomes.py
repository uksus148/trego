import json
import logging
from unittest.mock import AsyncMock

import pytest

from trego_agent.discovery import PlaceDiscovery
from trego_agent.diagnostics import trace
from trego_agent.exa import ResearchSource
from trego_agent.geocoding_candidates import GeocodingCandidate, select_candidate_result, CandidateSelection
from trego_agent.intent import RouteIntent, ProviderError
from trego_agent.localized_replies import FactualReplyWriter
from trego_agent.resolver import SourceResolution
from test_geocoding_candidates import SKOK, WESTERN_SKOK, RYSY


@pytest.mark.parametrize("rows,name,tags,anchors,reason", [
    ([], "Skok", [], [], "no_geocoding_candidates"),
    ([RYSY], "Skok", [], [], "name_mismatch"),
    ([SKOK], "Skok", ["peak"], [], "type_mismatch"),
    ([SKOK, WESTERN_SKOK], "Skok", ["waterfall"], [], "ambiguous_candidates"),
    ([SKOK, {**SKOK, "lat": 40}], "Skok", [], [], "conflicting_identity"),
    ([SKOK, WESTERN_SKOK], "Skok", [], [GeocodingCandidate.model_validate({**RYSY, "lat": 0, "lon": 0})], "outside_context"),
    ([SKOK], "Skok", [], [], "resolved"),
])
def test_candidate_outcomes_explain_existing_acceptance_rules(rows, name, tags, anchors, reason):
    result = select_candidate_result([GeocodingCandidate.model_validate(row) for row in rows], name, tags, anchors)
    assert result.reason == reason and result.candidateCount == len(rows)
    assert bool(result.location) == (reason == "resolved")


@pytest.mark.parametrize("mode", ["missing", "no_sources", "insufficient_evidence", "name_mismatch", "failure"])
async def test_discovery_gates_stop_at_the_reported_step_without_hiding_provider_failure(caplog, mode):
    intent, search, resolver, geo = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    intent.extract.return_value = RouteIntent(start="LEAK", end=None if mode == "missing" else "LEAK", mustSee=["LEAK"])
    search.search.return_value = [] if mode == "no_sources" else [ResearchSource(title="LEAK", sourceUrl="https://secret.example/")]
    resolver.resolve.return_value = None if mode == "insufficient_evidence" else SourceResolution(name="LEAK", geocodeQuery="LEAK", sourceIndex=0)
    geo.geocode_result.return_value = CandidateSelection(reason="name_mismatch", candidateCount=2)
    if mode == "failure":
        resolver.resolve.side_effect = ProviderError("Safe fixture error")
    caplog.set_level(logging.INFO, logger="trego_agent.diagnostics")
    with trace("LEAK"):
        if mode == "failure":
            with pytest.raises(ProviderError):
                await PlaceDiscovery(intent, search, resolver, geo).discover("LEAK", [])
            return
        result = await PlaceDiscovery(intent, search, resolver, geo).discover("LEAK", [])
    assert not result.ready_for_handoff
    assert "LEAK" not in caplog.text and "secret.example" not in caplog.text
    if mode == "missing":
        search.search.assert_not_awaited()
        assert result.missing_endpoints == ["end"]
    else:
        assert result.start.reason == mode and result.unresolved == ["LEAK"]
        assert f"finding={mode}" in caplog.text
    if mode in ("missing", "no_sources"):
        resolver.resolve.assert_not_awaited()
    if mode != "name_mismatch":
        geo.geocode_result.assert_not_awaited()


@pytest.mark.parametrize("language,expected", [("en", "5 h 02 min"), ("ru", "5 ч 02 мин"),
                                             ("sk", "5 h 02 min"), ("fi", "5 t 02 min")])
async def test_reply_numbers_match_panel_and_names_are_not_json(language, expected):
    reply = await FactualReplyWriter().write("", [], "ready", {"visits": ["A", "Skok", "A"],
        "distanceKm": 15.1786, "ascentM": 746, "durationMin": 302.015}, language=language)
    assert "15.2" in reply and expected in reply and "A → Skok → A" in reply and '"' not in reply


async def test_minutes_roll_over_and_clarifications_deduplicate_only_user_grounded_names():
    writer = FactualReplyWriter()
    reply = await writer.write("", [], "ready", {"visits": ["A"], "distanceKm": 1, "ascentM": 10, "durationMin": 59.6})
    assert "1 h 00 min" in reply
    reply = await writer.write("Find Sandberg", [], "clarification", {"missingEndpoints": ["start", "end"],
        "unresolvedPlaces": ["Sandberg", "Sandberg", "водапад near Štrbské Pleso", "водапад near Štrbské Pleso"]})
    assert "the start and the destination" in reply and reply.count("Sandberg") == 1
    assert "водапад" not in reply and "unclear waypoint" in reply
