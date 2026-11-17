# Agent architecture and working notebook

Keep current understanding, decisions and the next task here. Edit sections in
place; do not append chat transcripts or create a Markdown report per discussion.
Use **implemented**, **proposed direction**, and **idea to evaluate** explicitly.
Repository documentation is English; learning explanations in chat are Russian.

Baseline reviewed: main `c38953f` (through #90). The shared [root decisions](../CLAUDE.md)
and [handoff contract](../docs/AGENT_API_HANDOFF.md) remain authoritative.
This document proposes internal work; it approves no new public fields or Java changes.

## Goal, ownership and learning position

The goal is a reliable walking assistant: understand a request, retain its intended
places, attach verifiable sources/OSM identities, and publish a real saved route
or a clear question/error. Reliability means measurable behavior on agreed cases,
including failures; it does not mean infallible language understanding.

- Python/AI owner: interpretation, research, geographic verification, conversation,
  Java client, factual replies, diagnostics and tests of those boundaries.
- Java owner: canonical place UUIDs, OSM deduplication, persistence, ORS routing,
  saved-route APIs and database migrations.
- Frontend owner: chat/map state, markers, route editing, media presentation.
- Shared changes need affected-owner agreement; an internal rewrite preserves the
  accepted HTTP/identity/unit/error contracts until that agreement exists.

Covered together: product responsibilities, the broad pipeline, provider roles and
the accepted request/handoff boundary. The owner now wants implementation-led
learning: build, inspect and explain one working increment at a time.
Step 1 is locally verified. New `v2/` code implements
the explicit app factory, request/result validation, deterministic fixture and safe
trace/stage logs; no interpretation, providers or conversation state are connected.
Next: step 2, attach this foundation to the minimal lab UI. Update this position after a step is checked;
do not mark a topic understood or a capability delivered merely because it was described.

### Requirements for the replacement

Product goal: help a visitor plan a sourced walking trip through intended places,
including city sightseeing and outdoor trips. Historical hackathon deadlines and
vendor-credit choices explain the old design; they are not the definition of a
correct user result. Replacing a provider still must satisfy accepted contracts.

The first replacement must preserve these observable behaviors:

- Named route: keep requested start/end and ordered/repeated stops; attach evidence
  to verified places and use Java's canonical records before routing.
- Conversation: add/remove/correct a stop, answer a pending question, or start an
  unrelated plan without leaking stale places. Preserve unfinished intent as well
  as the last saved route. The state representation is new work, not delivered code.
- Uncertainty: ask a specific question for missing/ambiguous targets; never silently
  replace a city with a sight or an airport with its city. Provider outages remain
  errors rather than invented locations or claims that a place does not exist.
- City tour: retain evidence-backed sight suggestions as a separate supported
  scenario. Existing west-to-east ordering is a baseline to compare, not optimal routing.
- Completion: factual localized reply, correct saved-route ID/metrics when real Java
  is used, clear simulation labels in the lab, and no false success after failure.
- Developer control: one local launcher, explicit module/provider/key choices,
  inspectable stage inputs/outputs, bounded time/calls and private safe diagnostics.

Baseline examples: a direct named walk; that walk plus a repeated stop; an airport
request followed by destination clarification; a fresh unrelated request; a city
tour; an ambiguous same-name place; and a provider failure. For each, write the
expected action, retained state and whether any Java write is allowed before coding.
Record fixture/live mode; fixed numeric performance/cost targets need measurements.
Preferences are user wishes, not evidence that today's router optimizes scenery.

## Implemented request flow

Start in [main.py](src/gopstop_agent/main.py), `create_app` and its `/api/chat` handler:

1. Validate `ChatRequest`; acquire a per-session Valkey lease inside the total
   deadline. Read the last six complete exchanges from `ValkeySessionStore.history`.
2. [ChatService.respond](src/gopstop_agent/chat.py) selects EN/RU/SK/FI using
   `LanguageSelector`. Unsupported/uncertain language asks for a choice before discovery.
3. [ClaudeIntentExtractor.extract](src/gopstop_agent/intent.py) reads message/history
   into `RouteIntent`: start/end, up to five intermediate `mustSee` stops, up to
   twelve preferences, and advisory `descriptiveTargets` roles. Missing endpoints
   remain null; excessive ordinary-route intent clarifies rather than truncates.
4. [PlaceDiscovery.discover](src/gopstop_agent/discovery.py) handles ordinary routes
   or eligible city tours. For each ordinary target: `ExaSearch.search` returns
   title/URL/text evidence; `ClaudePlaceResolver.resolve` chooses a source-backed
   name, query, type tags and source index. No LLM supplies trusted coordinates.
5. [NominatimGeocoder](src/gopstop_agent/geocoding.py) obtains OSM candidates;
   [candidate selection](src/gopstop_agent/geocoding_candidates.py) checks names,
   features, context and identity. `DiscoveryResult` retains start/stops/end,
   evidence and reasons. Incomplete ordinary intent stops before place research;
   tour detection may still perform a model call.
6. Only `ready_for_handoff` permits [RouteHandoff.persist](src/gopstop_agent/handoff.py).
   Ingest verified places, use Java's returned records, create the route once and
   fetch it by ID. [TrailsApi](src/gopstop_agent/trails_api.py) validates HTTP results.
7. `FactualReplyWriter` renders authoritative outcome facts locally. There is no
   final reply-generation LLM call. Store the complete exchange before HTTP 200;
   a later failure may leave already committed Java data.

For Bratislava -> Devín Castle -> Vienna, discovery must retain those three roles
and sources. Handoff sends canonical endpoint coordinates and only the intermediate
castle UUID in `placeIds`. Java computes the walking track. A city-to-city result
does not imply cycling support, even if the user mentioned a bicycle.

Data types live in `intent.py` (`RouteIntent`), `discovery.py` (`PlaceFinding`,
`DiscoveredPlace`, `DiscoveryResult`), `geocoding_models.py` (`GeocodedPlace`) and
`api_models.py` (Java records). History stores text, not a structured saved/draft plan.
`drop_stale_stops` partly infers previous built routes from assistant arrow text;
this fragile dependency is a candidate for replacement, not a reliable state model.

## Identity and write rules to preserve

The user's wording, extracted target, researched name, OSM type/ID and Java UUID
are different values. Trace them separately. Strict JSON validates shape, not truth.
Groq uses strict JSON Schema plus local validation; Anthropic uses tool output.
Historical `Claude*` names do not mean that Anthropic is always selected.

Every ordinary target passes its requested name to verification. `descriptiveTargets`
cannot authorize a city-to-landmark substitution or positive cache promotion.
An unbound description asks for an explicit name before writes. Source index must
refer to supplied evidence; a model's confident answer is insufficient.

Names/aliases and supported feature constraints apply together. Exact OSM attributes
such as `historic=castle` or `building=cathedral` can supplement primary categories;
generic attraction text cannot. St./Saint normalization is limited to church/cathedral
names. City boundaries need explicit settlement labels, not admin level alone.
Several distinct valid identities remain ambiguous; never select the first/nearest
to force success. Narrow evidenced same-Wikidata/linked-settlement rules can merge
representations of one entity; historical OSM IDs are fixtures, not runtime overrides.

The nearby-name path (#89) can resolve one exact OSM object within 25 km of independent
route anchors when web resolution is inadequate. It excludes infrastructure and
retains ambiguity; address containment can distinguish local matches. Requested-identity,
conflict and outside-context rejections remain final. The OSM URL supplies evidence
when no research source exists. This is bounded lookup, not unrestricted fallback.

Java deduplicates by `(osmType, osmId)`, not by name/coordinates. First write wins;
use its authoritative UUID, source and coordinates. Preserve repeated visits and
intermediate-stop order; deduplicate only display records. WGS84 objects use lat/lon;
GeoJSON is `[lon, lat]`; metrics are km, metres and minutes. Validate route creation
and saved GET before publishing the ID. Never retry an uncertain Java POST or
substitute a straight line. There is no cross-service rollback or durable request idempotency.

## Conversation and city-tour limits

Implemented: recent text history, model follow-up interpretation, stale-stop filtering,
session ownership and owner-checked exchange append. A lease prevents overlapping
turns but does not fence an already running Java write or undo a saved route.

Implemented city tours (#90): eligible incomplete/same-city/over-limit requests
can research up to ten suggestions and retain up to seven distinct located sights.
Tour visits are ordered west to east; this is not shortest-tour optimization.
Explicitly named sights must all resolve; optional suggestions may be skipped.
Selection can make one additional generation when the suggestion list is short.

Open finding from uncommitted local lab work: an airport-to-city-centre request
followed by a named destination lost the airport qualifier and remained unresolved.
This is not reproduced evidence against the exact main revision. First capture
intent/history/evidence on a pinned version. Proposed structured state must retain
an unfinished request as well as the last successful route; do not assume that
remembering only a successful route fixes clarification.

## Budgets, caches and diagnostics

Source defaults: provider/API call 20 s, discovery/handoff 60 s, total chat 180 s.
The root example overrides discovery to 90 s. At most three ordinary unique target
chains run concurrently; unfinished siblings are cancelled/joined on failure.
Groq serializes calls per worker and waits on advisory quota headers inside the
deadline. Current main permits up to two replays only for HTTP 429 with a numeric
Retry-After of 0-60 s. Other errors and Java POSTs are not automatically replayed.
Per-worker coordination does not coordinate separate processes or daily quotas.

- Exa: successful/empty results 24 h; full-request hash; corrupt entries refreshed.
- Resolution v3: new/null results provisional for five minutes; exact final accepted
  selections promoted to 24 h; rejected entries demoted. Hits/feedback do not refresh
  lifetimes; compare-and-update protects concurrent replacements. No single-flight guarantee.
- Nominatim candidate v3: nonempty 24 h, empty five minutes, at most eight candidates.
  A shared host gate and cooldown space requests. Empty search can use one narrower
  name/country query; HTTP errors/ambiguity do not trigger that fallback.
- Sessions: default retention 200 messages, TTL 24 h; only six exchanges sent onward.
  Managed Valkey checks idle connections before use; application writes have no replay.

Missing/ambiguous findings are normal clarification. Provider/invalid-response failures
are 502; cache/storage failures 503; deadlines 504; same-session contention 409.
Verified `no_hiking_route` and `waypoint_not_routable` are distinct normal outcomes.
Neither proves a closure, season restriction or danger. Production diagnostics log
safe trace/timing/reason/count metadata; payload inspection remains local development work.
See [VERIFY.md](VERIFY.md) for commands and evidence limits.

## Replacement direction and sequence

**Working direction:** write a new small core in `refactor/agent-v2`, starting with
explicit data, conversation decisions and stage orchestration. The old implementation
is a behavioral reference, not the structure to copy. Reuse verified provider clients,
identity checks, Java handoff and storage protection when suitable; rework them only
with a demonstrated reason. Replace the running path incrementally through reviewed PRs.

Step 1 is locally verified; steps 2-12 remain planned.
Each ends with something runnable, a focused behavior
check and a short explanation from actual input/output. Use synthetic providers
first; own-key checks are deliberate and optional when quota is available. Missing
team services must not block core development. Run tests relevant to each change;
local simulation never substitutes for final real-service acceptance.

1. **Foundation and main entrypoint.** Start the new internal `gopstop_agent/v2/`
   package alongside the old implementation. Add only the request/result data and
   executable behavior needed now. `main.py` assembles a FastAPI app and dependencies;
   settings arrive explicitly; a thin handler delegates to the core. Define safe
   trace IDs, stage timing and error outcomes from the start. No automatic root-dotenv
   loading in lab mode, provider calls or new production activation.
   Learn: entrypoint, configuration, request/response and dependency injection
   (supplying a component instead of constructing it inside business code).
   Check: the local app starts/stops, validates the existing chat envelope and can
   run an explicitly labelled fixture turn without contacting external services.

2. **Minimal local lab for the new core.** Review and reuse only the necessary parts
   of the existing uncommitted launcher/UI/key controls. Attach the new app, stage
   inputs/outputs and fixture scenarios; keep Java simulated. Loopback-only launch,
   personal key controls, opt-in private payload inspection, redaction and bounded
   capture are part of this slice. INFO/WARNING/ERROR must distinguish normal work,
   recoverable conditions and failed stages. Do not copy the dirty tree wholesale.
   Learn: how to reproduce a run and find the first wrong value.
   Check: one launcher opens the lab; fixture success, clarification and failure
   are distinguishable; reset/shutdown and unexpected-network blocking work.

3. **LLM connection.** Introduce the small structured-model interface when first used;
   inspect/reuse a suitable existing transport behind it. Start with one selected
   Groq profile and a fake model, keeping prompt/task logic outside the HTTP adapter.
   Validate JSON shape and application rules; handle invalid output, refusal,
   access/quota errors, timeout and cancellation without hidden provider fallback.
   Account for every call/wait in the deadline; preserve the documented bounded
   replay policy only if the reviewed adapter is reused unchanged.
   Learn: model request, structured response, validation and provider error.
   Check: fixtures cover malformed output, timeout and quota; an optional own-key
   extraction is inspectable without Java, research or geographic calls.

4. **Understand one message.** Define validated proposed actions such as a new
   route, stop edit or answer to a question, with the needed endpoint/stop fields.
   Retain original wording/qualifiers alongside normalized names; unknown values
   stay unknown. Model suggestions cannot authorize writes or identity changes.
   Start with a named walk and missing endpoint, adding action types only as used.
   Learn: a user's intention versus a verified geographic fact.
   Check: named route, incomplete request and excessive/invalid output have explicit
   results, with no coordinates invented and no Java writes.

5. **Conversation and decisions.** Implement explicit draft plan, pending question
   and last saved route; apply validated actions deterministically. Start with
   isolated in-memory lab storage and introduce a storage boundary when it is needed.
   Distinguish new plan, clarification answer, correction and abandoned plan.
   Ask for missing data rather than guessing; do not parse assistant prose as state.
   Learn: state before/after a turn and why history alone is insufficient.
   Check: airport qualifier survives destination clarification; add/remove/repeat
   stops work; an unrelated request clears stale context; sessions remain isolated.
   Capture the existing airport report on a pinned version before claiming its cause fixed.

6. **Research and sources.** Add a research adapter, initially Exa, returning
   application-owned title/URL/text evidence. Separate query construction from
   network access, keep sources bound to results, and preserve bounded/cancellable
   work. Decide explicitly when a task needs research; a model suggestion or a
   search result is not a confirmed coordinate or proof of image rights.
   Learn: evidence, provenance and the difference between no results and an outage.
   Check: fixtures exercise empty/mixed/invalid sources and dependency failures;
   optional own-key research shows which source supports each proposed place.

7. **Geocoding and identity.** Add the geocoding adapter, initially Nominatim, and
   use/rework deterministic selection behind the new data types. Preserve original
   target, evidenced name, OSM type/ID, aliases, feature/context checks, ambiguity,
   attribution and public-provider request gating. Neither LLM classification nor
   provider choice can disable validation. Any nearby lookup has explicit bounds.
   Learn: coordinates versus entity identity; why a city and its castle differ.
   Check: city substitution, airport qualifier, genuine aliases, same-name places,
   empty identity proof and cache acceptance controls; ambiguity creates no Java writes.

8. **Java boundary with a simulator first.** Adapt the existing verified handoff
   client to new-core data: ingest only complete verified findings, use canonical
   UUIDs/coordinates, preserve intermediate-stop order/repeats, create once and
   GET the saved result. Keep uncertain-write failure explicit; no POST replay.
   Learn: source/OSM identity versus Java UUID, persistence and partial failure.
   Check: a recording fake Java verifies exact requests, first-write canonical
   records, lost responses, malformed readback and distinct routing failures.
   Synthetic geometry/metrics must remain visibly simulated.

9. **Complete chat behavior and factual replies.** Assemble the named-route flow
   through the growing coordinator; render only known results. Preserve EN/RU/SK/FI
   behavior and unsupported-language clarification before write actions. No final
   LLM-generated directions/metrics. Save a successful plan only after route readback;
   pending and previously saved state must survive appropriate clarification/failure.
   Learn: interpretation, application decision and user-facing outcome as separate steps.
   Check: full local conversations return either saved-route-shaped simulated success,
   a specific clarification or an honest failure; no invented route ID or metrics.

10. **Storage, caches and runtime safeguards.** Bring reviewed Valkey/session/cache
    adapters behind the new boundaries. Preserve lease ownership, atomic exchange/state
    persistence, expiry, selection-aware caching, cancellation and zero uncertain-write
    replay. Version changed cache/state payloads instead of reading incompatible data.
    Deadlines, privacy and provider gating already apply in earlier steps; validate
    their combined behavior here. No real Java activation before these protections.
    Learn: memory versus persisted state, TTL, cache hits and concurrent turns.
    Check: disposable local/CI Valkey covers overlap, stale owner, restart/expiry,
    corrupt records, outage and promotion/demotion without shared Aiven access.

11. **City tours and provider comparison.** Add the evidence-backed city-sights
    scenario with bounded optional suggestions and existing stop limits. Keep explicit
    user destinations mandatory. Retain west-to-east ordering as the comparison
    baseline; changing its product semantics is separate work. Add a second research,
    model or geocoding adapter only after specifying required capabilities and measuring
    the same scenarios; routing-provider changes remain Java-owned.
    Learn: suggestions versus required stops, provider capabilities and measured tradeoffs.
    Check: tours, too few valid sights, named-place preservation and source/OSM continuity;
    compare correctness, clarification rate, elapsed time, calls and available usage data.

12. **Gradual integration and retirement.** Keep one local choice between old and
    new paths; do not dual-execute real writes. Package coherent accepted slices as
    small PRs against main, preserving the accepted HTTP contract and a rollback path.
    Team-owned real Java/browser checks happen when services are available, on a
    reviewed revision. Remove old code only when its behavior is demonstrably replaced.
    Check: offline regression corpus and isolated service checks pass; record any
    outstanding live acceptance honestly before enabling the replacement in production.

After each step: explain the change briefly, inspect one concrete run together,
review the diff and relevant checks, then record delivered behavior and the next
step here. Aim for a small working core within several focused days; all later
capabilities and real-service acceptance are not promised within that estimate.

### Providers and deferred scope

**Proposed direction:** small replaceable research/geocoding/model adapters with
application-owned result types; validation stays independent of provider choice.
Factories already accept dependencies but still compose concrete providers.
Exa's selection reflects the original challenge/credits, not demonstrated superiority.
Tavily, Photon and GraphHopper are only ideas to evaluate, not selected replacements.
An alternative geocoder must supply OSM type/ID or a verified mapping; coordinates
alone cannot satisfy current ingestion. Routing changes belong with the Java owner.
Use provider-specific cache identity and explicit unsupported capabilities; no silent fallback.

[AVAILABILITY.md](AVAILABILITY.md) remains the useful internal-core reference;
public consent/dates/evidence mapping is deferred. Day planning, personalization,
cycling/transit, Gemini/pgvector ranking, uploads/EXIF/Kafka, photo-rights policy,
candidate confirmation and durable idempotency need separate acceptance/owner decisions.
Installed pgvector or an Exa image result does not deliver ranking or photo rights.

## V2 branch: starting checkpoint

Workspace branch: `refactor/agent-v2`. It starts from the reviewed baseline plus
documentation in [PR #94](https://github.com/uksus148/trego./pull/94). The original
runtime remains intact; step 1 adds the isolated `v2/` foundation. Provider switch,
lab migration and a functional replacement agent are not implemented yet.

Merge order: review/merge #94 first. After its squash merge, rebase this branch's
own commits onto current main, excluding the old docs commit; check the resulting
diff. Each implementation slice gets its own PR against main, then the workspace
follows the merged revision. Do not merge the whole experimental branch at once.

### Intended internal boundaries

Proposed responsibilities, not an instruction to create empty scaffolding:

- Data: plain typed intent, draft/saved plan, sourced findings and verified places.
  Data definitions must not import controllers or HTTP clients.
- Conversation: apply a new request, correction or clarification to explicit state;
  retain original qualifiers and distinguish pending targets from confirmed places.
- Discovery: coordinate research/resolution/geocoding, return typed outcomes;
  deterministic identity validation stays independent of any selected provider.
- Adapters: translate LLM, research, geocoding, storage and Java responses into
  those types. Start with existing services; add a second provider only when needed.
- Chat: choose the next action, render factual outcomes and use the existing
  ownership/storage boundary. Route geometry remains Java's responsibility.

Reuse the existing Python package, dependencies and tests where useful. New core
code starts in its internal `v2/` namespace so old imports keep working during
development. `v2/main.py` composes the app; task/data/state/orchestration modules
belong beside it, provider/storage clients behind adapters. Choose further file
names when responsibilities become executable; do not create empty layers upfront.
The development lab stays outside the production package. This is one service's
replacement core, not a second deployed service or a new agent framework.

Step 1 files: `v2/main.py` assembles the app and delegates chat; `config.py` accepts
explicit settings without loading environment; `models.py` preserves chat data;
`chat.py` defines the operation and labelled fixture; `diagnostics.py` records safe
metadata. The shared pure `ApiPlace` model is reused; the old application is not imported.
Use [the local run command](README.md#run-the-new-foundation-locally-step-1).
Local verification: 634 tests passed, 8 real-Valkey tests skipped (no disposable
server configured); 15 tests specifically cover the new foundation. Wheel/sdist
build, compilation, frozen lock and whitespace checks passed. Actual loopback HTTP
returned labelled 200, private 422 and trace headers; the server binds only 127.0.0.1.
Two unchanged legacy TTL tests reproduced a short-sleep timing failure; a bounded
expiry-wait fixture fixes their timing without changing production cache behavior.
No type/lint/coverage tools are configured in this project; no new tools or arbitrary
coverage gate were added. No live providers, Java, Aiven or production acceptance.
Next is step 2, minimal lab UI integration. Paid model
calls follow in step 3. Update this checkpoint instead of opening another plan file.

## History, not current acceptance

Historical stage reports and sequencing are preserved at
[the pre-consolidation tree](https://github.com/uksus148/trego./tree/c38953f02413ca3946101f1dd4d6b0b3c50bc872/agent)
and in [the former plans](https://github.com/uksus148/trego./tree/c38953f02413ca3946101f1dd4d6b0b3c50bc872/docs).
Old guide paths stay as compatibility pointers because shared documents link to them.

The [final #78 review](https://github.com/uksus148/trego./pull/78#pullrequestreview-5909280030)
approved the corrected `602bb90` head and recorded five real 120B saved-route/readback
cases using shared/warm caches. It explicitly excluded primary-20B, browser/media
and combined-fixture acceptance. Earlier claims that all corrected-head live checks
were pending are superseded; this historical sample still does not certify current main.
Use the [shared runbook](../docs/INTEGRATION_RUNBOOK.md) for the team's acceptance ledger.
