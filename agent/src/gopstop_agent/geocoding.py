"""Cached Nominatim lookup with a distributed request gate and OSM attribution."""

import asyncio
import hashlib
import json
import math
from uuid import uuid4

import httpx
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis

from gopstop_agent.diagnostics import cache_event
from gopstop_agent.intent import ProviderError, ProviderTimeout
from gopstop_agent.provider_errors import http_failure
from gopstop_agent.geocoding_candidates import (
    CandidateMatch, CandidateSelection, FEATURE_ATTRIBUTES, FEATURE_TYPES, GeocodingCandidate,
    matches_feature, matches_requested_name, select_candidate_result, words,
)
from gopstop_agent.geocoding_models import GeocodedPlace


OSM_ATTRIBUTION = "© OpenStreetMap contributors — https://www.openstreetmap.org/copyright"
COOLDOWN = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], 1000)
end
return 0
"""


locations_adapter = TypeAdapter(list[GeocodingCandidate])
SEARCH_OPTIONS = {"format": "jsonv2", "limit": 8, "namedetails": 1, "extratags": 1}


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

    async def _search(self, query: str) -> list[GeocodingCandidate]:
        identity = json.dumps([self._base_url, query, SEARCH_OPTIONS], sort_keys=True)
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
                        params={"q": query, **SEARCH_OPTIONS},
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
