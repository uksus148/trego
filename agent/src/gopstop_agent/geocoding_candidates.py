"""Select evidenced OSM candidates without relying on result order or importance."""

import math
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from gopstop_agent.geocoding_models import GeocodedPlace


class GeocodingCandidate(GeocodedPlace):
    name: str = ""
    namedetails: dict[str, str] = Field(default_factory=dict)
    category: str = ""
    type: str = ""
    addresstype: str = ""
    extratags: dict[str, str] = Field(default_factory=dict)

    @field_validator("extratags", mode="before")
    @classmethod
    def empty_extra_tags(cls, value):
        return {} if value is None else value


FEATURE_TYPES = {
    "waterfall": {"waterfall"}, "peak": {"peak"}, "lake": {"lake"},
    "castle": {"castle"}, "village": {"village", "hamlet"},
    "town": {"town"}, "city": {"city"}, "hamlet": {"hamlet"}, "resort": {"winter_sports", "resort"},
}
GENERIC_WORDS = {"waterfall", "peak", "mount", "mountain", "lake", "castle"}
CONTEXT_RADIUS_KM = 25

# Exact OSM attributes can retain identity when Nominatim chooses another primary
# category. A generic tourism=attraction is deliberately not a castle criterion.
FEATURE_ATTRIBUTES = {
    "castle": {("historic", "castle")},
    "cathedral": {("building", "cathedral")},
    "church": {("building", "church"), ("building", "cathedral"), ("historic", "church")},
    "lake": {("water", "lake")},
}

SelectionReason = Literal["resolved", "no_geocoding_candidates", "name_mismatch", "type_mismatch",
                          "ambiguous_candidates", "conflicting_identity", "outside_context", "requested_identity_mismatch"]


class CandidateMatch(BaseModel):
    osmType: Literal["node", "way", "relation"]
    osmId: int
    distanceKm: float | None = None


class CandidateSelection(BaseModel):
    reason: SelectionReason
    location: GeocodedPlace | None = None
    candidateCount: int
    nameMatchCount: int = 0
    identityCount: int = 0
    matches: list[CandidateMatch] = Field(default_factory=list)
    requestedMatches: list[CandidateMatch] = Field(default_factory=list)


def words(value: str) -> set[str]:
    plain = "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                    if not unicodedata.combining(c))
    tokens = re.findall(r"[^\W_]+", plain)
    # Only expand the leading saint abbreviation for religious building names;
    # do not globally equate street suffix "St" with "Saint".
    if tokens and tokens[0] == "st" and {"cathedral", "church"} & set(tokens):
        tokens[0] = "saint"
    return set(tokens)


def matches_feature(candidate: GeocodingCandidate, feature: str) -> bool:
    if candidate.type in FEATURE_TYPES.get(feature, set()):
        return True
    if feature in {"city", "town", "village", "hamlet"} and (candidate.category, candidate.type) == ("boundary", "administrative"):
        # Nominatim can rank a settlement's administrative relation as the search
        # result. Do not infer a settlement from admin_level or a generic boundary.
        labels = {label for label in (candidate.addresstype, candidate.extratags.get("place", ""))
                  if label in {"city", "town", "village", "hamlet"}}
        return bool(labels) and labels <= FEATURE_TYPES[feature]
    return any((candidate.category, candidate.type) == (key, value) or candidate.extratags.get(key) == value
               for key, value in FEATURE_ATTRIBUTES.get(feature, set()))


def distance_km(left: GeocodedPlace, right: GeocodedPlace) -> float:
    lat1, lat2 = math.radians(left.lat), math.radians(right.lat)
    dlat, dlon = lat2 - lat1, math.radians(right.lon - left.lon)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


def matches_requested_name(candidate: GeocodingCandidate, name: str) -> bool:
    expected = words(name.split(",")[0])
    aliases = [candidate.name, candidate.display_name.split(",")[0],
               *(value for key, value in candidate.namedetails.items() if "name" in key)]
    return bool(expected) and any(expected == words(alias)
                                  for item in aliases for alias in item.split(";"))


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
    features = {tag.casefold() for tag in tags if tag.casefold() in FEATURE_TYPES or tag.casefold() in FEATURE_ATTRIBUTES}
    matched = {}
    for candidate in candidates:
        aliases = [candidate.name, candidate.display_name.split(",")[0]]
        aliases.extend(value for key, value in candidate.namedetails.items()
                       if "name" in key)
        if expected and not any(expected <= words(alias) for item in aliases for alias in item.split(";")):
            continue
        counts["nameMatchCount"] += 1
        if features and not all(matches_feature(candidate, feature) for feature in features):
            continue
        identity = candidate.osm_type, candidate.osm_id
        previous = matched.get(identity)
        if previous and (previous.lat, previous.lon) != (candidate.lat, candidate.lon):
            counts["identityCount"] = len(matched)
            return CandidateSelection(reason="conflicting_identity", **counts)
        matched[identity] = candidate
    counts["matches"] = [CandidateMatch(osmType=identity[0], osmId=identity[1],
        distanceKm=round(min(distance_km(candidate, anchor) for anchor in anchors), 3) if anchors else None)
        for identity, candidate in sorted(matched.items())]
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
