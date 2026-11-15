"""Select evidenced OSM candidates without relying on result order or importance."""

import math
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

from gopstop_agent.geocoding_models import GeocodedPlace


class GeocodingCandidate(GeocodedPlace):
    name: str = ""
    namedetails: dict[str, str] = Field(default_factory=dict)
    category: str = ""
    type: str = ""


FEATURE_TYPES = {
    "waterfall": {"waterfall"}, "peak": {"peak"}, "lake": {"lake"},
    "castle": {"castle"}, "village": {"village", "hamlet"},
    "town": {"town"}, "city": {"city"}, "resort": {"winter_sports", "resort"},
}
GENERIC_WORDS = {"waterfall", "peak", "mount", "mountain", "lake", "castle"}
CONTEXT_RADIUS_KM = 25

SelectionReason = Literal["resolved", "no_geocoding_candidates", "name_mismatch", "type_mismatch",
                          "ambiguous_candidates", "conflicting_identity", "outside_context"]


class CandidateSelection(BaseModel):
    reason: SelectionReason
    location: GeocodedPlace | None = None
    candidateCount: int
    nameMatchCount: int = 0
    identityCount: int = 0


def words(value: str) -> set[str]:
    plain = "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                    if not unicodedata.combining(c))
    return set(re.findall(r"[^\W_]+", plain))


def distance_km(left: GeocodedPlace, right: GeocodedPlace) -> float:
    lat1, lat2 = math.radians(left.lat), math.radians(right.lat)
    dlat, dlon = lat2 - lat1, math.radians(right.lon - left.lon)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


def select_candidate(candidates: list[GeocodingCandidate], name: str,
                     tags: list[str], anchors: list[GeocodedPlace]) -> GeocodedPlace | None:
    return select_candidate_result(candidates, name, tags, anchors).location


def select_candidate_result(candidates: list[GeocodingCandidate], name: str,
                            tags: list[str], anchors: list[GeocodedPlace]) -> CandidateSelection:
    counts = {"candidateCount": len(candidates), "nameMatchCount": 0, "identityCount": 0}
    if not candidates:
        return CandidateSelection(reason="no_geocoding_candidates", **counts)
    expected = words(name)
    expected = expected - GENERIC_WORDS or expected
    if not expected:
        return CandidateSelection(reason="name_mismatch", **counts)
    types = set().union(*(FEATURE_TYPES.get(tag.casefold(), set()) for tag in tags))
    matched = {}
    for candidate in candidates:
        aliases = [candidate.name, candidate.display_name.split(",")[0]]
        aliases.extend(value for key, value in candidate.namedetails.items()
                       if "name" in key)
        if expected and not any(expected <= words(alias) for item in aliases for alias in item.split(";")):
            continue
        counts["nameMatchCount"] += 1
        if types and candidate.type not in types:
            continue
        identity = candidate.osm_type, candidate.osm_id
        previous = matched.get(identity)
        if previous and (previous.lat, previous.lon) != (candidate.lat, candidate.lon):
            counts["identityCount"] = len(matched)
            return CandidateSelection(reason="conflicting_identity", **counts)
        matched[identity] = candidate
    # Only use independently resolved route points to disambiguate multiple matches.
    # Never choose the nearest/first hit when several remain within the local area.
    if len(matched) > 1 and anchors:
        matched = {identity: candidate for identity, candidate in matched.items()
                   if any(distance_km(candidate, anchor) <= CONTEXT_RADIUS_KM for anchor in anchors)}
        if not matched:
            return CandidateSelection(reason="outside_context", **counts)
    counts["identityCount"] = len(matched)
    if len(matched) != 1:
        reason = "ambiguous_candidates" if matched else "type_mismatch" if counts["nameMatchCount"] else "name_mismatch"
        return CandidateSelection(reason=reason, **counts)
    return CandidateSelection(reason="resolved", location=GeocodedPlace.model_validate(next(iter(matched.values())).model_dump()), **counts)
