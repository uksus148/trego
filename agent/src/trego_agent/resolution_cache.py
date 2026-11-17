"""Reuse source-grounded resolutions only for identical provider/model requests."""

import hashlib
import json

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from redis.asyncio import Redis

from trego_agent.diagnostics import cache_event
from trego_agent.exa import ResearchSource
from trego_agent.resolver import ClaudePlaceResolver, SourceResolution


CACHE_TTL_SECONDS = 86400
PROVISIONAL_TTL_SECONDS = 300


class ResolutionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    place: SourceResolution | None
    accepted: bool = False

    @model_validator(mode="after")
    def require_place_for_acceptance(self):
        if self.accepted and self.place is None:
            raise ValueError("Only a concrete resolution can be accepted.")
        return self


# Compare exact payloads to avoid promoting/demoting a different concurrent result.
# Repeated hits do not extend either the provisional or accepted lifetime.
UPDATE_SELECTION = """
local value = redis.call('get', KEYS[1])
if ARGV[1] == 'accept' and value == ARGV[2] then
    redis.call('set', KEYS[1], ARGV[3], 'EX', ARGV[4])
    return 1
elseif ARGV[1] == 'reject' and value == ARGV[3] then
    local ttl = redis.call('pttl', KEYS[1])
    if ttl == -1 then ttl = tonumber(ARGV[5]) * 1000 end
    if ttl <= 0 then return 0 end
    redis.call('set', KEYS[1], ARGV[2], 'PX', math.min(ttl, tonumber(ARGV[5]) * 1000))
    return 1
end
return 0
"""


class CachedPlaceResolver:
    def __init__(self, resolver: ClaudePlaceResolver, cache: Redis, *, cache_namespace: str = "gopstop:place-resolution:v3") -> None:
        self._resolver, self._cache = resolver, cache
        self._cache_namespace = cache_namespace

    def _key(self, description, sources):
        # Covers model, prompt/schema and ordered evidence, without credentials or session IDs.
        identity = self._resolver.cache_identity(description, sources)
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return f"{self._cache_namespace}:{digest}"

    async def record_selection(self, description: str, sources: list[ResearchSource],
                               place: SourceResolution, *, accepted: bool) -> None:
        changed = await self._cache.eval(
            UPDATE_SELECTION, 1, self._key(description, sources), "accept" if accepted else "reject",
            ResolutionEntry(place=place).model_dump_json(),
            ResolutionEntry(place=place, accepted=True).model_dump_json(),
            CACHE_TTL_SECONDS, PROVISIONAL_TTL_SECONDS,
        )
        if changed:
            cache_event("resolution", "promoted" if accepted else "demoted")

    async def resolve(self, description: str, sources: list[ResearchSource]) -> SourceResolution | None:
        if not sources:
            return None
        key = self._key(description, sources)
        cached = await self._cache.get(key)
        if cached is not None:
            try:
                place = ResolutionEntry.model_validate_json(cached).place
                if place is None or place.sourceIndex < min(len(sources), 3):
                    cache_event("resolution", "hit")
                    return place
            except ValidationError:
                pass
        cache_event("resolution", "invalid" if cached is not None else "miss")
        # A cache read outage stops before spending credits; failed writes propagate too.
        place = await self._resolver.resolve(description, sources)
        await self._cache.set(key, ResolutionEntry(place=place).model_dump_json(), ex=PROVISIONAL_TTL_SECONDS)
        return place
