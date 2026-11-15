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
| `outside_context` | Several matches existed, and none survived the existing independent-anchor context filter |
| `resolved` | One identity is accepted with source binding and coordinates |

`finding=...` log lines retain trace/candidate index and source/candidate/name-match/
identity counts. Contextual reconsideration emits a second result using the same
candidate index. These are outcomes, not HTTP exceptions: `stage=... outcome=ok`
alone still does not prove resolution. Provider/timeouts/storage failures remain
errors, never normal ambiguity. Nominatim HTTP failures now retain safe status/code.
Selection rules, OSM provenance, query broadening limits and routing inputs are unchanged.

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

Exa/resolution use a unique temporary cache namespace for every probe. `--cold`
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
