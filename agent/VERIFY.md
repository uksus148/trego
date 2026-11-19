# Verify the AI part

Start with offline tests; real Java, PostgreSQL, ORS and team keys are unnecessary
for that layer. A passing fixture test proves the behavior of the supplied inputs,
not that a live model will produce them. HTTP 200 clarification is not a saved route.

## Offline checks

From the repository root after [installing test dependencies](README.md#install-and-run-the-existing-service):

```powershell
uv run --project agent --frozen --extra test pytest -q -r s
uv run --project agent --frozen python -m compileall -q agent/src agent/tests devtools start_agent_lab.py
uv lock --project agent --check --offline
```

The Python test suite blocks external socket connections and DNS lookups.
Tests exercise application code with substitutions at external boundaries.
Real-Valkey runtime tests skip unless `TEST_VALKEY_URL` points to a disposable loopback
instance. Skips are not a pass for that boundary. [Agent CI](../.github/workflows/agent.yml)
provides Valkey 8.1 and runs the suite without live credentials.

For just the new step-1 boundary, run
`uv run --project agent --frozen --extra test pytest agent/tests/test_v2_foundation.py -q`.
It checks explicit configuration, the chat contract and limits, private validation
errors, dependency substitution, deadline cancellation, unexpected/invalid outputs,
concurrent trace isolation and external cancellation. Network connects are blocked
inside these tests. Try the [new local factory](README.md#run-the-new-foundation-locally-step-1)
manually; a fixed fixture reply is not interpretation or conversation acceptance.

Keep meaningful controls for requested-city substitution, advisory descriptive roles,
empty independent verification, cache promotion/demotion, aliases/translations,
settlement features, nearby ambiguity, repeated stops, language switches, incomplete
intent, invalid output/source indices, provider errors, cancellation and uncertain writes.
Prefer a regression reproducing the actual failure over many implementation-shaped tests.

### V2 regressions

- [Walking core](tests/test_v2_walking.py): substitute only the model and draft
  store. Exercise the real workflow to distinguish malformed output from an
  invalid clarification. Confirm the draft still carries the airport phrase.
- [Lab HTTP](../devtools/tests/test_agent_lab.py): substitute the Groq transport
  and vault. Check explicit live selection at the HTTP boundary, provider errors
  without fallback, and shared-core clarification, session isolation, stop
  repeats and the stop limit. After a UI change, save a key with the local mode
  selected and verify that the selector stays local.

```powershell
uv run --project agent --frozen --extra test pytest agent/tests/test_v2_walking.py devtools/tests/test_agent_lab.py -q
```

## Local Agent Lab

Use [the launcher](README.md#open-the-new-local-lab-step-2). The new UI exposes
the v2 foundation, technical failure and timeout checks, bounded private inspection,
and live Groq checks for summaries and walking requests. Drafts for endpoint
clarification live in the lab process. The walking handler in the core owns their
updates and questions. Java and durable conversation state are later steps.
The older full-pipeline lab remains separate.

From the repository root, after dependencies are prepared:

```powershell
agent\.venv\Scripts\python.exe -m pytest devtools\tests agent\tests\test_v2_foundation.py -q -o asyncio_mode=auto
agent\.venv\Scripts\python.exe -m compileall -q devtools start_agent_lab.py
node --check devtools\agent_lab\lab.js
```

These tests use an in-memory vault and ASGI HTTP. The Groq checks substitute an
HTTP transport to exercise the actual request, parser, and local validation.
They cover loopback host/origin/auth, bounded requests, real core validation,
opt-in/redacted payloads, ERROR/WARNING capture, timeout/cancellation/overlap,
reset/shutdown, report bounds, write-only keys, vault failure without plaintext,
launcher reuse/occupied ports/startup cleanup and worktree-isolated setup.
Groq cases include a missing key, success, malformed output, refusal, HTTP 401/429,
provider timeout and cancellation. Check **Stage log** for the precise reason.
The provider status (such as `401` or `429`) appears in the diagnostic fields.
The lab's chat boundary reports upstream failures as `502` and timeouts as `504`.
A personal-key run is the separate check for live access and available quota.
For walking requests, try a missing destination followed by a named place under
the same session label. Inspect `route_draft` to confirm the start phrase survived.
The lab suite checks the wire schema, state isolation, endpoint changes, order
and repeats, the stop limit, and quota wait with substituted Groq responses.
The existing agent workflow now includes Linux checks and a Windows lab job;
configured CI jobs are not evidence of a completed CI run.
Review exports for private free text even after known-secret redaction.

For live understanding checks, explicitly choose **Groq live · understand a
walking request** and use a personal key. Use fresh requests in more than one
language, including a qualified origin followed by destination clarification,
repeated visits, more than five stops and a second session. Compare the original
phrase to the user's text, the proposed name to the intended entity and the
question to the missing detail. Record failures as well as successes. In the
PR record the revision, commands or lab mode, substitutions, real checks and
skips. Fixture results describe application behavior when given those outputs.

## Explicit provider probes

These commands can spend personal quota and read root `.env`. Set the selected
LLM/Exa configuration privately as described in [README.md](README.md). Point any
required Valkey at your own local instance. Keep TLS enabled. Start with one run;
record commit, model, cache mode, result/reason, latency and call count. Compare
profiles separately. Stop on failure or quota exhaustion rather than hiding it
behind manual reruns; the bounded Groq 429 policy is described in the notebook.

From `agent/`, model-only interpretation (the existing configuration gate also
requires a nonblank Exa key, but this mode does not call Exa):

```powershell
uv run --frozen python -m trego_agent.probe_resolution --intent-only --query "I would like to see a waterfall."
```

This validates structure and missing endpoints, not coordinates. Resolution-only:

```powershell
uv run --frozen python -m trego_agent.probe_resolution --query "Find hiking place: Sandberg near Bratislava. Route context: Devin Castle to Sandberg near Bratislava."
```

It makes fresh Exa/model calls without Valkey, Nominatim, Java or session writes.
Unresolved is a valid outcome; neither probe certifies route completion.

Full discovery, requiring configured Valkey but no Java/ORS/frontend:

```powershell
uv run --frozen python -m trego_agent.probe_discovery --cold --message "Plan a walk from Bratislava Castle to St. Martin's Cathedral in Bratislava, Slovakia."
```

Default research uses a unique temporary namespace. `--cold` also isolates Nominatim
candidate caches, but retains the shared host rate gate/cooldown. Cleanup deletes
only that namespace; `cleanupFailed` means temporary keys may remain until expiry.
`--shared-research` instead reads/writes ordinary caches and applies normal selection
feedback; it cannot combine with `--cold`. Never flush shared caches. No mode writes
Java places/routes/chat history. The probe receives no conversation history.

`--include-identity` adds requested/extracted/resolved/selected identity details.
Even default reports can include matched OSM IDs and anchor distances; treat reports
as location data. Review before sharing. Exit 0 includes `needs_clarification` as
well as `ready`; exit 1 indicates failure, including unsuccessful cleanup.

## Read stage evidence

Production `logging.json` enables safe metadata. Correlate `trace`, hashed `session`
and `candidate`; inspect `stage`, `elapsed_ms`, outcome and reason. `model_queue`
and `quota_wait` consume the parent deadline. Cache hit/miss/invalid and
promoted/demoted events distinguish warm behavior from fresh requests.
`routing_cache` times the Java POST; it does not prove a cache hit.

The original agent logs stage errors as WARNING and normal progress/cancellation
as INFO. The v2 foundation already logs failed stages as ERROR, invalid requests
as WARNING and normal progress/cancellation as INFO. Full payload/state inspection
still belongs to separate lab work. Never enable public prompt/body/HTTP DEBUG
logging or print keys, raw session IDs or private exception payloads.

Discovery reasons: `no_sources`, `insufficient_evidence`, `no_geocoding_candidates`,
`name_mismatch`, `type_mismatch`, `ambiguous_candidates`, `conflicting_identity`,
`requested_identity_mismatch`, `outside_context`, or `resolved`. An `outcome=ok`
stage can still return an unresolved place. `insufficient_evidence` is not a proven
quota failure. Identity rejection must precede writes and positive cache acceptance.

Provider diagnostics distinguish HTTP/access/quota, transport, timeout, request or
response schema, refusal/truncation, invalid structured content and source-index
errors. Check safe `http_status`, `provider_code`, `timeout_kind`, `validation_count`
and allowlisted `validation_types`. Do not infer the historical #61 cause from a
new unrelated failure. Cache/storage outages remain errors, not geographic ambiguity.

## Focused acceptance corpus

Use the same pinned implementation and explicit expectations for each comparison:

- Bratislava/Vienna in English and Russian: cities remain cities, never their sights.
  Add Devín Castle and repeat a stop: preserve endpoints and visit order.
- Castle/Cathedral aliases and Stupava: accept evidenced representations without
  collapsing genuinely distinct same-named objects. Preserve negative substitution controls.
- July Tatras: source-supported points and exact Skok identity; genuine ambiguity
  clarifies. Original Rysy is a truthful routing-failure control, not a forced success.
- Incomplete waterfall, then a named destination; airport qualifier followed by a
  clarification: retain unfinished intent or ask, without inventing an endpoint.
- Helsinki sights: evidence-backed locations, at most seven visits, west-to-east
  ordering; no claim of optimized length. New unrelated request clears stale stops.
- Unknown language, malformed schema, bad source index, no sources, timeouts, quota,
  session overlap/expiry and lost write response: clear outcomes, no false success/replay.

Capture the first wrong transition before proposing a fix. Lab fixtures, personal live
discovery and integrated acceptance are different evidence; record which was used.

## Real Java and browser: later team acceptance

Coordinate access under [infrastructure rules](../infra/README.md#local-development-resource-rules).
Use reviewed API/V3, local configuration and [the integration runbook](../docs/INTEGRATION_RUNBOOK.md).
First run `uv run --frozen python -m trego_agent.smoke` from `agent/`: this spends
provider quota, writes/reads temporary session/cache data and reads the API; it is
not a route-write test, migration proof or browser acceptance.

After preflight and explicit activation with `AGENT_CHAT_ENABLED=true`, run the
[README server command](README.md#install-and-run-the-existing-service), then:

```powershell
uv run --frozen python -m trego_agent.smoke --chat
```

This creates real places/routes and retains evidence, validates saved GET and reads
the session exchange. Failures may follow committed writes: never automatically
replay. A warm ORS cache does not validate a new ORS key. With frontend mocks off,
check track, markers, sources, units, language, follow-ups and empty-route clearing.
For idle acceptance, test first requests after 25 minutes without process restart.
Use [fixture integration](../tests/integration/README.md) in CI for actual-service
contract checks without live keys; it still does not certify real providers.
Historical successes in [#78](ARCHITECTURE.md#history-not-current-acceptance) do not
certify the current revision. Final deployment acceptance remains a separate team step.
