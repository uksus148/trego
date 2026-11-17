"""Pure selection/schema checks; no provider, cache or model doubles."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from trego_agent.geocoding import preserve_query_name
from trego_agent.geocoding_candidates import GeocodingCandidate, select_candidate_result
from trego_agent.intent import RouteIntent
from trego_agent.provider_errors import ProviderError
from trego_agent.structured_output import strict_schema


# Reduced Nominatim observations, 2026-11-15, q=Stupava, Slovakia.
# Data © OpenStreetMap contributors / ODbL: https://www.openstreetmap.org/copyright.
STUPAVA = [
    {"osm_type": "relation", "osm_id": 2206975, "name": "Stupava", "display_name": "Stupava, Slovensko",
     "lat": 48.273044, "lon": 17.0329528, "category": "boundary", "type": "administrative", "addresstype": "town",
     "extratags": {"place": "town", "linked_place": "town", "wikidata": "Q782928"}},
    {"osm_type": "node", "osm_id": 26036885, "name": "Stupava", "display_name": "Stupava, Slovensko",
     "lat": 48.273044, "lon": 17.0329528, "category": "place", "type": "town", "addresstype": "town",
     "extratags": {"wikidata": "Q782928"}},
]


@pytest.mark.parametrize("reverse", [False, True])
def test_linked_town_representation_keeps_both_identities_and_selects_boundary_independent_of_order(reverse):
    result = select_candidate_result([GeocodingCandidate.model_validate(r) for r in STUPAVA[::(-1 if reverse else 1)]],
                                     "Stupava", ["town"], [])
    assert (result.location.osm_type, result.location.osm_id) == ("relation", 2206975)
    assert result.identityCount == 2 and len(result.matches) == 2


@pytest.mark.parametrize("conflict", ["missing_qid", "different_qid", "invalid_qid", "missing_link",
                                    "different_link", "coordinates", "extra_node", "extra_boundary", "no_type"])
def test_incomplete_or_conflicting_linkage_stays_ambiguous(conflict):
    rows = deepcopy(STUPAVA)
    if conflict in {"missing_qid", "different_qid", "invalid_qid"}:
        rows[1]["extratags"]["wikidata"] = {"missing_qid": "", "different_qid": "Q1780", "invalid_qid": "Q0"}[conflict]
        if conflict == "invalid_qid":
            rows[0]["extratags"]["wikidata"] = "Q0"
    elif conflict in {"missing_link", "different_link"}:
        rows[0]["extratags"]["linked_place"] = "" if conflict == "missing_link" else "city"
    elif conflict == "coordinates":
        rows[1]["lat"] += .00001
    elif conflict in {"extra_node", "extra_boundary"}:
        rows.append({**rows[1 if conflict == "extra_node" else 0], "osm_id": 1})
    result = select_candidate_result([GeocodingCandidate.model_validate(r) for r in rows],
                                     "Stupava", [] if conflict == "no_type" else ["town"], [])
    assert result.reason == "ambiguous_candidates" and result.location is None


@pytest.mark.parametrize("query,name,expected", [
    ("Bratislava, Slovakia", "Bratislava Castle", "Bratislava Castle, Slovakia"),
    ("Devín, Bratislava, Slovakia", "Devín Castle", "Devín Castle, Bratislava, Slovakia"),
    ("Bratislavský hrad, Slovakia", "Bratislava Castle", "Bratislavský hrad, Slovakia"),
    ("Wien, Austria", "Vienna", "Wien, Austria"),
    ("Bratislava Castle, Slovakia", "Bratislava", "Bratislava Castle, Slovakia"),
])
def test_query_preserves_full_sourced_name_without_replacing_aliases_or_trimming_other_identities(query, name, expected):
    assert preserve_query_name(query, name) == expected


def test_strict_intent_schema_excludes_interest_strings_from_target_references():
    validator = Draft202012Validator(strict_schema(RouteIntent.model_json_schema()))
    value = {"start": "Bratislava", "end": "Vienna", "mustSee": [],
             "preferences": ["historical sights", "photography"], "descriptiveTargets": []}
    validator.validate(value)
    assert not validator.is_valid({**value, "descriptiveTargets": ["historical sights"]})
    with pytest.raises(ValidationError) as caught:
        RouteIntent.model_validate({**value, "descriptiveTargets": ["stop:1"]})
    diagnostic = ProviderError("Invalid intent", validation=caught.value).diagnostic
    assert diagnostic["validation_types"] == "invalid_target_reference"
    assert diagnostic["validation_fields"] == "root" and "historical" not in str(diagnostic)


def test_repeated_target_with_a_named_role_cannot_bypass_identity_binding():
    intent = RouteIntent(start="Bratislava", end="Vienna", mustSee=["Bratislava"], descriptiveTargets=["stop:1"])
    assert intent.descriptive_names == set()
