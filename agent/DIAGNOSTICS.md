# Agent diagnostics

## Read the stage evidence

Start the agent with `--log-config logging.json` as in [LIVE_TEST.md](LIVE_TEST.md).
Correlate one request by its random `trace` and hashed `session`; `candidate` identifies
an internal concurrent place task without recording its name. `resolution`, `discovery`
and `chat` retain the same sanitized cause as the failing model call. Errors use WARNING;
success and sibling cancellation use INFO. Cancellation is not another provider failure.

For example, a **fixture** HTTP rejection produces:

```text
chat trace=012345abcdef session=012345abcdef candidate=0 stage=resolution elapsed_ms=503 outcome=ProviderError provider=groq operation=resolve_place reason=http_status http_status=400 provider_code=tool_use_failed
```

This is an example, not new live evidence for #61. Available reasons:

| Reason | Meaning / next check |
|---|---|
| `http_status` | Inspect `http_status` and allowlisted `provider_code`: 401/403 means access/configuration; 429 means provider limits; 400 `tool_use_failed` means rejected tool generation; 5xx means upstream failure |
| `transport` | HTTP connection/protocol failure before a usable response; check connectivity/TLS without disabling verification |
| `timeout` | HTTP timeout, with `timeout_kind` distinguishing connect/read/write/pool |
| `request_schema` | Local request/schema construction failed, before a usable model response |
| `response_json` | Response envelope is not usable JSON or lacks the expected structure |
| `model_refusal` | The structured extraction was refused; no raw refusal text is exposed |
| `structured_content` | Groq returned missing/non-JSON structured content |
| `incomplete_generation` | Inspect allowlisted `finish_reason`, such as `length` or `max_tokens` |
| `unexpected_tool` / `tool_arguments` | Wrong tool/count or unusable argument JSON/object |
| `schema_validation` | Tool object violates the application schema; `validation_count` and up to three allowlisted `validation_types` describe it |
| `invalid_source_index` | Structurally valid resolution selected evidence outside the supplied source list |
| `no_usable_sources` | Exa returned entries but none passed source validation |
| `discovery_deadline` / `deadline` | Overall discovery/chat budget elapsed; inspect nested waits before blaming an HTTP timeout |
| `cancelled` | Work cancelled by a parent deadline or a sibling failure; find the original WARNING in this trace |

`model_queue` measures the per-worker Groq lock wait; `quota_wait` measures the
existing token-header wait. Both remain cancellable within the parent deadline.
Advisory quota headers cannot replace an HTTP failure with a parsing error.
Cache events for `exa`, `resolution` and `nominatim` distinguish `hit`, `miss`,
`invalid` (refresh) and Exa's explicit probe `bypass`. A warm resolution hit makes
no model call. `routing_cache` still times the Java route POST, not a measured cache hit.

Only LLM/Exa failure adapters carry the new provider metadata. Unknown codes/reasons
become `unknown`. Logs exclude raw bodies, prompts/messages, generated arguments,
source URLs, coordinates, keys, raw session IDs and exception tracebacks. Validation
messages, input, context and field paths are excluded too; extra field names can
contain private data. Do not enable HTTP DEBUG logging or publish private `.env` files.

## Isolate a cold resolution on the team's machine

After checking out the reviewed revision, use the existing private root `.env` with
`AGENT_LLM_PROVIDER=groq`, `AGENT_GROQ_MODEL=openai/gpt-oss-20b`, `GROQ_API_KEY` and
`EXA_API_KEY`. This command does not require enabled chat or a running server:

```sh
cd agent
uv sync --frozen --extra test
mkdir -p target
uv run --frozen python -m gopstop_agent.probe_resolution --query "Find hiking place: Sandberg near Bratislava. Route context: Devín Castle to Sandberg near Bratislava." > target/resolution-probe.json 2> target/resolution-probe.log
```

One invocation makes one fresh Exa search and, if sources exist, one model resolution task.
It bypasses both caches without deleting keys, needs no Valkey, and never calls
Nominatim, Java or ORS or writes places, routes or sessions. Groq retains its bounded 429 exception; there is no provider fallback. Run it deliberately, after the account's token
budget replenishes; it shares Groq/Exa quotas with the running application.
Both calls share the configured discovery deadline and provider HTTP timeouts.

Stdout is a redacted JSON report with `traceId`, `stage`, `elapsedMs`, `sourceCount`,
`status` and, on failure, safe `error` metadata. Stderr has matching stage logs.
Exit 0 means a valid `resolved` or `unresolved` result; `unresolved` is legitimate
ambiguity/insufficient evidence, not proof of failure or E5 acceptance. Exit 1 means
failure. Record the tested commit and sanitized report/log, not the prompt/key/body.
This isolated probe does not validate intent extraction, geocoding, Java, ORS or the browser.

An HTTP 502 remains an honest dependency/invalid-response failure; it is not converted
to normal ambiguity. Public chat JSON and 502/503/504 mappings are unchanged. Do not
replay an uncertain chat POST: later-stage failures may follow committed writes.
If the cold report confirms `tool_use_failed`, use that evidence for a focused model
schema/generation change and owner review. Record live verification separately from fixture results.

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
| `requested_identity_mismatch` | A changed named target lacks usable independent identity proof: missing, nonmatching, incompatible or ambiguous verification |
| `outside_context` | Several matches existed, and none survived the existing independent-anchor context filter |
| `resolved` | One identity is accepted with source binding and coordinates |

`finding=...` log lines retain trace/candidate index and source/candidate/name-match/
identity counts. Contextual reconsideration emits a second result using the same
candidate index. These are outcomes, not HTTP exceptions: `stage=... outcome=ok`
alone still does not prove resolution. Provider/timeouts/storage failures remain
errors, never normal ambiguity. Nominatim HTTP failures now retain safe status/code.
OSM provenance and routing inputs are unchanged. The
[issue #76 verification](README.md#identity-and-session-invariants) can perform
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

## Locate an incorrect successful destination (#77)

Run the exact #76/#77 corpus at the reviewed revision with separate model/cache
reports. Explicit private capture includes intent roles, resolution/query and OSM IDs:

```sh
uv run --frozen python -m gopstop_agent.probe_discovery --shared-research --include-identity --message "проложи маршрут от братиславы до вены на велике, я хочу увидеть исторические места по пути и поделать фотографий"
```

Compare intent endpoints with resolver names and selected identities; enum-valid
roles can still misclassify named targets, but cannot waive verification. An unbound
description must clarify before handoff/cache acceptance. Default reports omit names/queries.
See [latest evidence and remaining negative controls](README.md#identity-and-session-invariants).
Then verify saved route, stop order, sources, session, browser and media isolation;
HTTP 200 clarification is not route acceptance. Cycling remains deferred.

## Full discovery probe on the team's machine

Use the reviewed revision and existing private root LLM/Exa/Valkey configuration.
Chat can stay disabled; API/ORS/frontend need not run. From `agent/`:

```sh
uv sync --frozen --extra test
mkdir -p target
uv run --frozen python -m gopstop_agent.probe_discovery --cold --message "Plan a walk from Bratislava Castle to St. Martin's Cathedral in Bratislava, Slovakia." > target/discovery-castle-20b.json 2> target/discovery-castle-20b.log
uv run --frozen python -m gopstop_agent.probe_discovery --cold --message "I want to hike from Štrbské Pleso to Rysy via the Skok waterfall. I love wild scenery." > target/discovery-rysy-20b.json 2> target/discovery-rysy-20b.log
```

For the complete named routes shown above, each run makes one intent call and at most one Exa search/resolution per
unique target (up to seven), with existing concurrency, quota waits and discovery/
provider deadlines. Missing endpoints avoid all subsequent research. The probe
does not classify reply language, call Java/ORS, create places/routes or write chat
history. It is not route or browser acceptance. Groq retains its bounded 429 exception;
no route POST or provider switching is introduced.

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
Agree a bounded sample before repeating read-only cases; stop on provider/quota failures. Do not flush shared caches or replay an
uncertain route POST. Capture the failing gate and the team's locally
reviewed inputs/candidate evidence for a focused regression. Do not infer a fix
from a single successful run or choose a first/nearest candidate to force success.

## Compare isolated and shared caches

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
