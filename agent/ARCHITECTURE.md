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

## What actually exists in v2

**Implemented:** the HTTP foundation. **Temporary fixture:** a fixed diagnostic
reply. **Not implemented:** LLM interpretation, draft state, research, discovery,
Java handoff or the new lab UI. Passing the foundation tests proves none of those.
The Python import package is `trego_agent`; its distribution is `trego-agent`.
Persisted `gopstop:` Valkey keys stay compatible with Java and existing data; their
migration is separate from renaming Python imports. No old-package alias is provided;
repository consumers and commands are updated together.

- [main.py](src/trego_agent/v2/main.py): `create_app(settings, service)` assembles
  FastAPI without constructing providers. Lifespan logs start/stop. Middleware
  assigns a fresh trace, times HTTP work and returns a safe 500 for unexpected
  failures. Validation/deadline handlers return safe 422/504. The thin `chat`
  function validates the HTTP envelope, times the operation and awaits the supplied
  service inside `asyncio.timeout`. `create_fixture_app` explicitly selects the
  demonstration service; importing the module opens no network/storage connections.
- [config.py](src/trego_agent/v2/config.py): `AppSettings` is an explicitly supplied
  Pydantic value, not an environment reader. Strict types, no unknown fields, frozen
  values and finite numbers catch bad configuration. The only current setting is
  the bounded chat timeout, default 180 seconds. Future tunable provider/model,
  call/concurrency budgets belong here when used, loaded once at the composition
  boundary. Public payload limits and identity rules are compatibility constraints.
  Legacy geographic selection thresholds become named, validated policy settings
  when integrated; changing their defaults/meaning is a separate reviewed decision.
- [models.py](src/trego_agent/v2/models.py): `Nonblank` rejects whitespace-only text;
  `ChatRequest` enforces the existing session/message fields and bounds without
  rewriting user text. `ChatResponse` validates the reply, canonical place records
  and optional routeId. `default_factory=list` creates a separate list per response;
  absent routeId is omitted by the handler. Only the existing pure `ApiPlace` schema
  is reused, not the old controller. Future domain/state types stay separate from HTTP.
- [chat.py](src/trego_agent/v2/chat.py): `ChatService` is a Protocol describing one
  async `respond(request)` operation. Any conforming implementation can be supplied.
  `FixtureChatService` currently ignores message meaning and always returns the
  same `[LOCAL FIXTURE]` diagnostic. That is deliberately fixed test data, not an
  intelligent answer or evidence of routing. It is selected only by the explicit
  fixture factory. Move development fixtures outside production behavior as the
  lab/real coordinator arrives; never use one as an outage fallback.
- [diagnostics.py](src/trego_agent/v2/diagnostics.py): `request_trace` uses UUIDs and
  a ContextVar to isolate concurrent request traces, restoring context in `finally`.
  `stage` measures elapsed time and records success, cancellation or failure, then
  propagates exceptions. INFO/WARNING/ERROR carry metadata only; no user text,
  raw session IDs, credentials or exception bodies. Detailed private inspection
  is an opt-in lab collector to be built in step 2, not current behavior.
- [__init__.py](src/trego_agent/v2/__init__.py): marks the package and documents its
  development status. It has no configuration, client construction or startup work.

### Chosen design and alternatives

Use a small explicit async workflow: the model proposes interpreted data; code
validates it and controls actions. A single giant endpoint is shorter initially
but couples HTTP, providers, state and write decisions. A model freely choosing
arbitrary tools would give it too much authority over identity and writes. A new
orchestration framework is not needed for this bounded workflow. Reconsider only
when an actual requirement justifies its complexity.

App factories make dependency selection and tests explicit; a global configured
app would be simpler to start but could read private dotenv or open clients during
import. One Protocol is enough now; do not create a generic plugin platform or
empty service/repository layers. Pydantic handles structural validation; business
correctness remains in application code, not in the JSON schema.

## Target workflow and responsibilities (planned)

1. HTTP boundary in `main.py` validates the unchanged request and establishes trace
   and deadline. The composed application owns client lifetimes and configuration.
2. The chat coordinator obtains session ownership and loads explicit state. Early
   lab slices use memory; real activation requires the reviewed Valkey protections.
3. An interpretation task calls the selected LLM with current text and bounded
   relevant state. It returns a validated proposed action, never trusted coordinates
   or permission to execute arbitrary tools. Original wording and qualifiers remain
   alongside normalized names; assistant prose is not a state database.
4. Conversation logic applies a new request, edit or clarification to a draft.
   Check requirements for the task: a named route needs endpoints, while an area tour
   can begin with its area and derive suggested visits. Missing/ambiguous intent
   produces a specific question. A new unrelated plan clears
   stale pending targets while preserving previous saved-route facts appropriately.
5. Discovery resolves required targets using geographic context. A direct, uniquely
   evidenced map lookup need not incur a web search and second model call. Use
   research when recommendations, descriptive requests or missing evidence require it;
   retain source binding and the accepted no-write clarification for unbound descriptions.
   These are explicit application policies, not free-form model instructions.
6. Independent validation binds candidates to the requested entity, source, OSM
   identity and coordinates. Multiple distinct valid candidates remain ambiguous.
   Only complete verified required targets permit Java place/route writes.
7. Handoff ingests places, uses canonical returned records, creates once and reads
   back the saved route. A failure may follow committed data; never replay uncertain
   POSTs or run old/new pipelines together with real writes.
8. Render only known outcome facts in the user's supported language, then persist
   the complete exchange and corresponding state atomically before HTTP 200.
   No model invents route metrics or directions after route creation.

Clarification branches return an actual question with no routeId; incomplete
geography causes no partial Java writes. Dependency failures remain errors, not
claims that a place does not exist. Verified routing failures remain separate
normal outcomes, and may follow successful place ingestion. Cache writes are
separate from place/route writes and must not turn failed verification into acceptance.

Introduce files when used: `domain.py` for original targets, draft/saved plans and
verified findings; `conversation.py` for state transitions; `discovery.py` for lookup
coordination and independent selection; adapters for model/research/geocoding,
Java and storage. `chat.py` becomes the thin coordinator. Provider response formats
must not leak into these domain values. The development lab stays in `devtools/`,
composes the same core, and exposes only stages that are genuinely implemented.

### Development and evidence policy

- Implement the actual available logic at each step; substitute only external
  dependencies or explicit diagnostic behavior. A fixture is not a completed feature.
- Never branch production behavior on a demo city, literal prompt, known OSM ID or
  test flag to force success. Sources/model/page contents are untrusted data.
- Fixed protocol fields/units, error categories and validated limits are not a
  geographic shortcut. Tunable provider/model/time/call settings have one explicit
configuration boundary, not scattered constants or hidden environment reads.
- Tests assert rules: all required identities verified before writes, source binding,
  preserved visit order/repetition, state isolation, truthful failures and no write
  replay. Vary names, countries, languages, ordering and provider outputs; include
  negative and multi-turn cases. Do not make tests pass by weakening these rules.
- Use synthetic/renamed entities and transformations where meaningful: consistently
  changing supplied names should preserve the same identity-checking rule; changing
  only the candidate to another entity must not gain acceptance. Real aliases still
  require evidence. Fixtures cannot measure actual model interpretation quality.
- Compare fresh user-chosen requests not used for tuning, real provider outputs and
  error cases when own-key quota permits. Record failures as well as successes,
  model/configuration, cache mode, source/identity outcomes, calls, time and available
  usage. Set performance/cost targets from measurements, not a single warm demo.
- Lab mode is explicit per dependency; no live error silently switches to fixtures.
  Warn which calls are real and which data is simulated. Paid work is bounded and
  cancellable. Capture private inputs/structured outputs only with opt-in redaction,
  bounded retention and no private model reasoning; production logs stay metadata.
- Every increment ends with an inspectable run, focused checks and owner explanation.
  Test count alone never establishes product acceptance; there is no guarantee of
  perfect understanding of arbitrary language. Uncertainty must have a useful outcome.

## Implemented request flow

This is the **legacy baseline**, not the current v2 capability: HTTP/session lease
and six recent exchanges -> language selection -> intent -> discovery -> Java
handoff/readback -> factual reply -> owner-checked exchange save. It currently
uses text history and stale-stop inference from assistant arrow text, not explicit
structured draft state. Its implemented city tour selects evidenced sights, keeps
at most seven visits and orders west to east, not by shortest path. The airport
clarification report came from separate uncommitted lab work; reproduce on a pinned
version before claiming any new state representation fixes its cause.

## Identity and write rules to preserve

Original wording, interpreted target, researched name, OSM type/ID and Java UUID
are separate values. `descriptiveTargets` cannot waive requested-name verification.
Keep evidenced aliases/features and settlement labels, joint type constraints,
narrow same-entity rules and final identity/conflict/context rejection. Never pick
first/nearest to conceal ambiguity; no production city-ID/coordinate overrides.
Bounded nearby lookup may use the unique exact OSM match and its URL as evidence;
retain the current 25 km anchor constraint, infrastructure exclusion and ambiguity.
Java owns OSM deduplication and first-write canonical records. Preserve repeated
visits; route placeIds contains intermediate UUIDs, not endpoints. WGS84 objects
use lat/lon, GeoJSON [lon, lat]; units are km/metres/minutes. Public fields and
Java-owned routing do not change without affected-owner agreement.

## Budgets, caches and diagnostics

Legacy source defaults are provider/API 20 s, discovery/handoff 60 s, chat 180 s;
the root example uses discovery 90 s. Three ordinary unique-target chains run
concurrently. Current Groq allows at most two 429 replays with numeric Retry-After
0-60 s; waits count toward deadlines. This is not account-wide coordination.
Exa caches success/empty results 24 h. Nominatim candidate v3 uses 24 h nonempty,
five-minute empty, at most eight candidates and a shared host gate/cooldown.
Resolution v3 starts at five minutes; accepted selection promotes the exact value
to 24 h, rejection demotes it, hits/feedback do not extend lifetime. No single flight.
Sessions default to 200 messages/24 h; six exchanges sent to interpretation.
Do not flush shared keys or rename the cross-language rate gate incidentally.
Legacy contention/dependency/storage/deadline statuses are 409/502/503/504;
verified no-path/unmatched-waypoint outcomes do not prove closure or danger.
See [VERIFY.md](VERIFY.md) for runnable commands and limits of the evidence.

## Replacement direction and sequence

**Working direction:** write a new small core in `refactor/agent-v2`, starting with
explicit data, conversation decisions and stage orchestration. The old implementation
is a behavioral reference, not the structure to copy. Reuse verified provider clients,
identity checks, Java handoff and storage protection when suitable; rework them only
with a demonstrated reason. Replace the running path incrementally through reviewed PRs.

Step 1 is locally verified; steps 2-12 remain planned. Its tests establish HTTP,
configuration and diagnostic behavior, not travel interpretation or model quality.
Each ends with something runnable, a focused behavior
check and a short explanation from actual input/output. Use synthetic providers
first; own-key checks are deliberate and optional when quota is available. Missing
team services must not block core development. Run tests relevant to each change;
local simulation never substitutes for final real-service acceptance.

1. **Foundation and main entrypoint.** Start the new internal `trego_agent/v2/`
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
   The lab composes the actual core; recorded provider responses cannot select a
   different business algorithm. Mark unavailable stages as not implemented rather
   than pretending a generic fixed reply demonstrates those capabilities.
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
   Keep ordinary route, area-tour and unsupported-task requirements distinct.
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
The `v2` name is a temporary parallel-development boundary, not a permanent second
product. Retire the versioned namespace only when the old core is replaced safely.
The development lab stays outside the production package. This is one service's
replacement core, not a second deployed service or a new agent framework.

Step 1 files: `v2/main.py` assembles the app and delegates chat; `config.py` accepts
explicit settings without loading environment; `models.py` preserves chat data;
`chat.py` defines the operation and labelled fixture; `diagnostics.py` records safe
metadata. The shared pure `ApiPlace` model is reused; the old application is not imported.
Use [the local run command](README.md#run-the-new-foundation-locally-step-1).
Local verification: 634 tests passed, 8 real-Valkey tests skipped (no disposable
server configured). After the package rename, the full suite again passed 634
tests with those 8 skips; the expanded focused run passed 18 foundation checks
and 3 integration-transport guard checks. A test-helper audit fixed empty JSON
being silently replaced by default input and added missing-field regressions.
That improves HTTP verification, not model/geographic acceptance. Wheel/sdist
build, compilation, frozen lock and whitespace checks passed. Actual loopback HTTP
returned labelled 200, private 422 and trace headers; the server binds only 127.0.0.1.
Two unchanged legacy TTL tests reproduced a short-sleep timing failure; a bounded
expiry-wait fixture fixes their timing without changing production cache behavior.
No type/lint/coverage tools are configured in this project; no new tools or arbitrary
coverage gate were added. No live providers, Java, Aiven or production acceptance.
Rename checks also confirmed unchanged dependency versions, mechanical-only shared
consumer updates, a clean `trego-agent` wheel without the old import namespace,
and a restarted `trego_agent.v2` app answering real loopback HTTP on port 8011.
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
