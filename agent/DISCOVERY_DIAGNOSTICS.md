# Diagnose an unresolved place (S3)

The #65 review observed a new cold Rysy-request clarification for Štrbské Pleso,
and a duplicated translated/misspelled intent description. The #63 120B report
also could not build Castle -> Cathedral despite successful stage completion.
Neither observation identifies the failing identity gate. This block adds evidence;
it does not assert that these live discovery cases are fixed.

## Interpret the results

`PlaceFinding.reason` is an internal result, not a public chat field. Missing
endpoints stop after intent, before Exa, resolution or geocoding. Other findings
distinguish the following outcomes:

| Reason | Meaning |
|---|---|
| `no_sources` | Exa returned no usable research entries (an empty valid result) |
| `insufficient_evidence` | Sources exist, but the resolver returned null; this does not establish a geographic or provider cause |
| `no_geocoding_candidates` | Nominatim returned an empty candidate set after the existing allowed query handling |
| `name_mismatch` | Candidates exist but do not match the requested evidenced name/aliases |
| `type_mismatch` | Name matches exist, but none passes the known object-type filter |
| `ambiguous_candidates` | Multiple distinct accepted OSM identities remain |
| `conflicting_identity` | Accepted entries for the same OSM identity disagree on coordinates |
| `requested_identity_mismatch` | Original-target lookup establishes a settlement inconsistent with the source-led resolution, or cannot distinguish its identities |
| `outside_context` | Several matches existed, and none survived the existing independent-anchor context filter |
| `resolved` | One identity is accepted with source binding and coordinates |

`finding=...` log lines retain trace/candidate index and source/candidate/name-match/
identity counts. Contextual reconsideration emits a second result using the same
candidate index. These are outcomes, not HTTP exceptions: `stage=... outcome=ok`
alone still does not prove resolution. Provider/timeouts/storage failures remain
errors, never normal ambiguity. Nominatim HTTP failures now retain safe status/code.
OSM provenance and routing inputs are unchanged. The
[issue #76 verification](OSM_IDENTITIES.md#issue-76-requested-settlements) can perform
one cached original-target lookup to reject a settlement/attraction substitution.

## Issue #76: inspect requested identity

The explicit probe includes `matches`: name/type-matched `osmType`, `osmId` and
minimum `distanceKm` to independent anchors before contextual filtering. Distances
are null without anchors. `requestedMatches` contains independently evidenced
settlement type/IDs on an identity mismatch. Counts therefore no longer hide which
objects the resolver found. Routine logs keep counts only; treat the local report
as location data, without publishing private configuration.

From `agent/` on the reviewed revision, using the team's existing private configuration:

```sh
uv run --frozen python -m gopstop_agent.probe_discovery --shared-research --message "Hike from Bratislava to Vienna."
uv run --frozen python -m gopstop_agent.probe_discovery --shared-research --message "Walk from Bratislava, Slovakia to Vienna, Austria."
```

Each is an explicit run that can spend model/Exa credits on cache misses. Stop on
quota/provider errors. Expected success uses city relations 1702499 and 109166,
not Bratislava Castle or either Kahlenberg peak. An identity mismatch must clarify
without Java/route/session writes. A probe success still needs normal browser and
persisted-route acceptance. Keep 20B and 120B evidence separate; never flush team caches.

## Full discovery probe on the team's machine

Use the reviewed revision and existing private root LLM/Exa/Valkey configuration.
Chat can stay disabled; API/ORS/frontend need not run. From `agent/`:

```sh
uv sync --frozen --extra test
mkdir -p target
uv run --frozen python -m gopstop_agent.probe_discovery --cold --message "Plan a walk from Bratislava Castle to St. Martin's Cathedral in Bratislava, Slovakia." > target/discovery-castle-20b.json 2> target/discovery-castle-20b.log
uv run --frozen python -m gopstop_agent.probe_discovery --cold --message "I want to hike from Štrbské Pleso to Rysy via the Skok waterfall. I love wild scenery." > target/discovery-rysy-20b.json 2> target/discovery-rysy-20b.log
```

Each explicit run makes one intent call and at most one Exa search/resolution per
unique target (up to seven), with existing concurrency, quota waits and discovery/
provider deadlines. Missing endpoints avoid all subsequent research. The probe
does not classify reply language, call Java/ORS, create places/routes or write chat
history. It is not route or browser acceptance. No retries or fallback providers.

By default, Exa/resolution use a unique temporary namespace for every probe.
The explicit shared-research profile below uses the current chat caches instead. `--cold`
also isolates Nominatim candidate caching; without it, Nominatim uses the ordinary
shared candidate cache, including normal writes on misses. Both profiles retain
the same shared Nominatim rate gate and cooldown; cold mode is not a rate-limit
bypass. Cleanup scans/deletes only its UUID namespace with a two-second deadline.
Shared team keys and the rate gate are never deleted; failed cleanup is reported
as `cleanupFailed: true` with exit 1, so temporary keys may remain until TTL expiry.

The redacted report identifies provider/model profile, trace, cache profile,
missing endpoints and unique findings in start/stops/end first-occurrence order.
`candidate` matches the stage-log task index. It excludes descriptions, queries,
source contents/URLs, OSM IDs and coordinates. Counts describe returned rows/name
matches and distinct accepted identities; they are not a model confidence score.
Exit 0 with `ready` means complete discovery; `needs_clarification` means a valid
incomplete/ambiguous result. Dependency/configuration failure exits 1.

Record revision and all outcomes, retaining separate 20B and 120B filenames.
Run problematic read-only cases deliberately five times after quota replenishes,
stopping on provider/quota failures. Do not flush shared caches or replay an
uncertain route POST. Before S4, capture the failing gate and the team's locally
reviewed inputs/candidate evidence for a focused regression. Do not infer a fix
from a single successful run or choose a first/nearest candidate to force success.

## Reply review follow-up

The #65 wording nits are applied: one decimal km (no redundant `.0`), rounded
hours/minutes with carry at 60, plain visit names, localized endpoint conjunctions,
and warmer ready wording. Unresolved descriptions are deduplicated. Only literal
case-insensitive matches in current/previous user messages are echoed; otherwise
the catalog asks for an exact waypoint name/location. This avoids publishing a
translated or invented intent phrase as if it were the user's wording. Persisted
canonical visit names and intentional repeated route visits remain unchanged.

## S4a: reproduce a sticky research cache

The #66 live review found ordinary chat unresolved at Štrbské Pleso with shared
resolution-cache hits, while isolated research plus the same shared Nominatim cache
was ready. The old v2 cache could retain a structurally valid but ungeocodable result
for 24 hours. v3 bounds new/null/unconfirmed results to five minutes and promotes
only final accepted selections. Old v2 records expire naturally; they are not flushed.

To inspect the **current chat cache policy** on a fresh-session message:

```sh
uv run --frozen python -m gopstop_agent.probe_discovery --shared-research --message "I want to hike from Štrbské Pleso to Rysy via the Skok waterfall. I love wild scenery." > target/discovery-shared-20b.json 2> target/discovery-shared-20b.log
```

This uses ordinary Exa, v3 resolution and Nominatim caches, including their normal
writes/TTL feedback on misses or selection. It never deletes shared keys. It is
read-only with respect to Java/places/routes/chat sessions, not Valkey. A hit does
not extend TTL. `--cold --shared-research` is rejected. The default isolated-research
profile and `--cold` behavior remain available for comparison; only their UUID
namespace is cleaned. No mode bypasses the shared Nominatim rate gate.

Compare identical prompts, model profiles and fresh sessions at the same commit.
The probe supplies no conversation history and cannot recreate a history-dependent
intent. Old v2 sticky entries are ignored by both new chat and the new probe; the
new comparison is against v3. Record `cache=resolution result=promoted|demoted` and
`stage=resolution_cache_validation` together with finding reasons. Failed feedback
is a storage error before any API writes, not a reason to bypass cache or repeat a
paid call. Allow the short TTL to expire before a deliberate new model attempt.

The castle's repeated type mismatch and cathedral's varying name mismatch remain
separate S4 identity work. A successful fresh resolution does not justify loosening
these filters or claiming a Java/ORS outage. The reviewed counts identify the gate,
but a precise alias/category correction still needs the actual candidate evidence.

The next [S4b landmark correction](OSM_IDENTITIES.md) uses fresh public OSM attribute/alias evidence for the castle and cathedral. Remaining multi-identity cases still require type evidence or clarification.

For [issue #69](OSM_IDENTITIES.md#issue-69-settlement-boundaries-and-unresolved-roles),
candidate cache v3 preserves settlement addresstype evidence. A city boundary may
resolve without a primary city type. Rejected endpoints now have role-specific
clarifications even when intent translates or normalizes their names. Remaining
routing failure is separate; do not infer cycling support from a resolved city.
