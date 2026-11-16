# Live agent checks

Follow the [integration runbook](../docs/INTEGRATION_RUNBOOK.md) and
[shared resource rules](../infra/README.md#local-development-resource-rules).
These commands can spend model/Exa/ORS quota and create data. Run deliberately on
the recorded revision; stop on quota or dependency failure.

## Configuration

Use private root .env with an explicitly selected AGENT_LLM_PROVIDER and model,
the matching provider key, EXA_API_KEY, agent Valkey URL and Java API URL.
Groq supports the profiles listed in structured_output.py, including GPT OSS 20B,
120B and Qwen. Keep results per model/profile; the root example selects 20B.
Anthropic is an explicit alternative. Source defaults do not establish account access.

Keep AGENT_CHAT_ENABLED=false during initial preflight. Configure Java database,
cache and ORS separately. Use local data services unless a shared Aiven run is agreed.
Keep TLS verification and do not shell-source .env.

## Preflight and HTTP route smoke

From agent/, with the Java API and dependencies running:

```sh
uv sync --frozen --extra test
mkdir -p target
uv run --frozen python -m gopstop_agent.smoke > target/preflight.json
```

Preflight checks language/intent/resolution, fresh Exa access, Nominatim, cache/session
operations and read-only API access. It cleans only its temporary keys. A successful
report does not verify the full browser flow; an existing cache hit cannot validate
every upstream key. Inspect the report and selected profile before enabling chat.

Set AGENT_CHAT_ENABLED=true, restart the agent, then invoke one explicit route check:

```sh
uv run --frozen python -m gopstop_agent.smoke --chat > target/chat-smoke.json
```

This verifies CORS, POST chat, the saved route GET and stored exchange. A normal
clarification can be valid application behavior while failing the smoke's route
expectation. Saved data and expiring history remain. Do not automatically replay
uncertain POSTs or infer a fresh ORS request from cache-served success.

## Browser acceptance

Set VITE_USE_MOCKS=false and matching service/CORS settings. Use the matrix in the
runbook for a short direct walk, multiple stops, the July Tatras prompt, another
region, clarification, failures, media and editor behavior. Rysy remains a separate
unmatched-waypoint regression, rather than the mandatory positive route.

Inspect track endpoints, stop order, canonical sources, OSM attribution, metrics,
previous-route status and session transitions. Frontend clarification retains a
previous built route after #89. A ready reply needs a matching browser route GET.

## Isolate extraction and discovery

Use an intent-only probe for parsing/schema problems:

```sh
uv run --frozen python -m gopstop_agent.probe_resolution --intent-only --query "Walk from Bratislava Castle to St. Martin's Cathedral."
```

Use [DIAGNOSTICS.md](DIAGNOSTICS.md) for resolution/discovery probes and cache profiles.
They do not create Java places/routes; ordinary cache misses can still write Valkey
and consume provider budget. Include identity details only in private local reports.

## Required regression observations

- Unsupported/excessive intent gives useful clarification; no requested stop is
  silently dropped merely to fit the schema.
- Model descriptive classification cannot bypass requested-place verification.
- Same-named distinct OSM objects remain ambiguous without identity evidence.
- Source and canonical coordinates survive ingestion and saved-route readback.
- Unconfirmed resolutions expire quickly; final accepted results can be promoted.
- Idle Valkey sockets recover during connection preparation; application writes
  and uncertain POSTs are not automatically replayed.
- Supported reply languages and follow-ups preserve the user's substantive language.
- New-plan, add/remove-stop and popular-place requests are evaluated separately.
- Record provider/model and actual cache hits for every conclusion. Structured JSON
  validity, fixture passes and source checkpoints do not establish geographic correctness.
