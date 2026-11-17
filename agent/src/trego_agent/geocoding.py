"""Cached Nominatim lookup with a distributed request gate and OSM attribution."""

import asyncio
import hashlib
import json
import math
from uuid import uuid4

import httpx
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis

from trego_agent.diagnostics import cache_event
from trego_agent.intent import ProviderError, ProviderTimeout
from trego_agent.provider_errors import http_failure
from trego_agent.geocoding_candidates import (
    CONTEXT_RADIUS_KM, CandidateMatch, CandidateSelection, FEATURE_ATTRIBUTES, FEATURE_TYPES, GeocodingCandidate,
    addressed_in_anchor, distance_km, is_infrastructure, matches_feature, merge_same_wikidata, matches_requested_name, select_candidate_result, words,
)
from trego_agent.geocoding_models import GeocodedPlace


OSM_ATTRIBUTION = "© OpenStreetMap contributors — https://www.openstreetmap.org/copyright"
COOLDOWN = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], 1000)
end
return 0
"""


locations_adapter = TypeAdapter(list[GeocodingCandidate])
KM_PER_DEGREE = 111.0
SEARCH_OPTIONS = {"format": "jsonv2", "limit": 8, "namedetails": 1, "extratags": 1}


def preserve_query_name(query: str, name: str | None) -> str:
    """A search hint may translate a sourced name, but must not truncate it."""
    parts = [part.strip() for part in query.split(",")]
    if name and words(parts[0]) and words(parts[0]) < words(name.split(",")[0]):
        parts[0] = name.split(",")[0].strip()
        return ", ".join(parts)
    return query


class NominatimGeocoder:
    def __init__(self, client: httpx.AsyncClient, redis: Redis, user_agent: str,
                 base_url: str = "https://nominatim.openstreetmap.org",
                 timeout_seconds: float = 20, *, cache_namespace: str = "gopstop:nominatim:search:v3") -> None:
        self._client, self._redis, self._user_agent = client, redis, user_agent
        self._cache_namespace = cache_namespace
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._timeout = httpx.Timeout(timeout_seconds)
        host_hash = hashlib.sha256(self._base_url.encode()).hexdigest()
        self._gate = f"gopstop:nominatim:gate:v1:{host_hash}"

    async def geocode(self, query: str, *, name: str | None = None, tags: list[str] | None = None,
                      anchors: list[GeocodedPlace] | None = None) -> GeocodedPlace | None:
        return (await self.geocode_result(query, name=name, tags=tags, anchors=anchors)).location

    async def geocode_result(self, query: str, *, name: str | None = None, tags: list[str] | None = None,
                             anchors: list[GeocodedPlace] | None = None, requested_name: str | None = None) -> CandidateSelection:
        query = query.strip()
        if not query:
            raise ValueError("Geocoding query must not be blank.")
        query = preserve_query_name(query, name)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                candidates = await self._search(query)
                parts = [part.strip() for part in query.split(",")]
                # Preserve the supplied name and country; remove only intermediate
                # region qualifiers after an empty response, never after an error.
                if not candidates and len(parts) >= 3 and all(parts):
                    candidates = await self._search(f"{parts[0]}, {parts[-1]}")
                selection = select_candidate_result(candidates, name or parts[0], tags or [], anchors or [])
                return await self._guard_settlement_identity(selection, candidates, name or parts[0], parts[0], requested_name, anchors or [])
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise ProviderTimeout("Place geocoding is temporarily unavailable.", provider="nominatim",
                                  operation="geocode", reason="timeout", timeout=type(exc).__name__) from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError("Place geocoding is temporarily unavailable.", provider="nominatim",
                                operation="geocode", reason="transport" if isinstance(exc, httpx.HTTPError) else "response_json") from exc

    async def geocode_nearby(self, name: str, anchors: list[GeocodedPlace]) -> CandidateSelection:
        """Find one exactly named OSM object around independently resolved route points.

        For explicit names that web evidence cannot identify (a generic local name such
        as a hostel). Never ranks: several local matches remain ambiguous.
        """
        name = name.strip()
        if not name or not anchors:
            return CandidateSelection(reason="no_geocoding_candidates", candidateCount=0)
        lat_margin = CONTEXT_RADIUS_KM / KM_PER_DEGREE
        lon_margin = lat_margin / max(0.1, math.cos(math.radians(max(abs(anchor.lat) for anchor in anchors))))
        lats, lons = [anchor.lat for anchor in anchors], [anchor.lon for anchor in anchors]
        viewbox = (f"{min(lons) - lon_margin:.3f},{max(lats) + lat_margin:.3f},"
                   f"{max(lons) + lon_margin:.3f},{min(lats) - lat_margin:.3f}")
        candidates = await self._search(name, viewbox=viewbox)
        nearby = [candidate for candidate in candidates
                  if not is_infrastructure(candidate) and matches_requested_name(candidate, name)
                  and any(distance_km(candidate, anchor) <= CONTEXT_RADIUS_KM for anchor in anchors)]
        places = merge_same_wikidata(nearby)
        # Address containment is evidence, not ranking: 'Heldenplatz' in Vienna rather
        # than the same name in a neighbouring town. Otherwise ambiguity remains.
        inside = [candidate for candidate in places if addressed_in_anchor(candidate, anchors)]
        if len(places) > 1 and len(inside) == 1:
            places = inside
        return select_candidate_result(places, name, [], anchors)

    async def _guard_settlement_identity(self, selection: CandidateSelection, candidates: list[GeocodingCandidate],
                                         name: str, query_name: str, requested_name: str | None,
                                         anchors: list[GeocodedPlace]) -> CandidateSelection:
        if requested_name is None or selection.reason == "conflicting_identity":
            return selection
        identity = (selection.location.osm_type, selection.location.osm_id) if selection.location else None
        unchanged_name = words(requested_name.split(",")[0]) == words(name) == words(query_name)
        # Ordinary name/type/context selection already applies when the resolver
        # retains the requested name and query. Changed identities need proof.
        if unchanged_name:
            return selection
        if any((candidate.osm_type, candidate.osm_id) == identity
               and matches_requested_name(candidate, requested_name) and matches_requested_name(candidate, name)
               and any(matches_feature(candidate, kind) for kind in ("city", "town", "village", "hamlet"))
               for candidate in candidates):
            return selection
        # Preserve evidenced local-language names for an explicitly requested
        # feature. Its category comes from the original target, not resolver tags.
        features = words(requested_name) & (FEATURE_TYPES.keys() | FEATURE_ATTRIBUTES.keys())
        if features:
            proof = select_candidate_result(candidates, requested_name.split(",")[0], sorted(features), anchors)
            if proof.location and (proof.location.osm_type, proof.location.osm_id) == identity:
                return selection
        # Verify the immutable requested target independently of the source-led
        # resolver. Exact settlement names can constrain an attraction suggestion;
        # a free-form description does not become an inferred city by proximity.
        requested = [candidate for candidate in await self._search(requested_name)
                     if matches_requested_name(candidate, requested_name)
                     and any(matches_feature(candidate, kind) for kind in ("city", "town", "village", "hamlet"))]
        identities = {(candidate.osm_type, candidate.osm_id) for candidate in requested}
        # Empty/unusable verification is not permission to accept a renamed POI.
        if len(identities) == 1 and identity in identities and any(matches_requested_name(candidate, name) for candidate in requested):
            return selection
        return selection.model_copy(update={"reason": "requested_identity_mismatch", "location": None, "identityCount": 0,
            "requestedMatches": [CandidateMatch(osmType=kind, osmId=number) for kind, number in sorted(identities)]})

    async def _search(self, query: str, *, viewbox: str | None = None) -> list[GeocodingCandidate]:
        # Unbounded searches keep their existing cache identity.
        options = SEARCH_OPTIONS if viewbox is None else {**SEARCH_OPTIONS, "viewbox": viewbox, "bounded": 1}
        identity = json.dumps([self._base_url, query, options], sort_keys=True)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        # v1 cached a selected place/null for 24h. v2 retains candidates so a
        # different category or geographic context cannot inherit an old decision.
        key = f"{self._cache_namespace}:{digest}"
        cached = await self._redis.get(key)
        if cached is not None:
            try:
                value = locations_adapter.validate_json(cached)
                cache_event("nominatim", "hit")
                return value
            except ValidationError:
                pass
        cache_event("nominatim", "invalid" if cached is not None else "miss")
        try:
            async with asyncio.timeout(self._timeout_seconds):
                token = uuid4().hex
                lease_ms = math.ceil(self._timeout_seconds * 1000) + 2000
                while not await self._redis.set(self._gate, token, nx=True, px=lease_ms):
                    await asyncio.sleep(0.05)
                try:
                    response = await self._client.get(
                        self._base_url + "/search", timeout=self._timeout, follow_redirects=False,
                        headers={"User-Agent": self._user_agent},
                        params={"q": query, **options},
                    )
                    if response.is_error or response.is_redirect:
                        raise http_failure(response, provider="nominatim", operation="geocode")
                    results = locations_adapter.validate_python(response.json())
                finally:
                    # Keep one second between completion and the next uncached request.
                    # Compare the token so a timed-out worker cannot release another's gate.
                    await self._redis.eval(COOLDOWN, 1, self._gate, token)
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise ProviderTimeout("Place geocoding is temporarily unavailable.", provider="nominatim",
                                  operation="geocode", reason="timeout", timeout=type(exc).__name__) from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError("Place geocoding is temporarily unavailable.", provider="nominatim",
                                operation="geocode", reason="transport" if isinstance(exc, httpx.HTTPError) else "response_json") from exc
        await self._redis.set(key, locations_adapter.dump_json(results), ex=86400 if results else 300)
        return results
