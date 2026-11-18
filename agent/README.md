# trego. AI agent

Python understands a walking request, finds and verifies places, and asks Java to
save them and calculate a route. Java owns routing and PostgreSQL; the frontend
owns the map. A model response alone never proves that a place or route is correct.

<a id="source-grounded-place-discovery"></a>

## Read and work here

1. [ARCHITECTURE.md](ARCHITECTURE.md): responsibilities, data flow, safeguards,
   open questions and the replacement plan. This is our single working notebook.
2. [VERIFY.md](VERIFY.md): checks without team keys, provider probes, diagnostics
   and the limits of each kind of evidence.
3. [Accepted handoff](../docs/AGENT_API_HANDOFF.md) and [root decisions](../CLAUDE.md):
   authoritative shared contracts. The notebook cannot override them.

The [availability core](AVAILABILITY.md) is implemented internally but disconnected
from chat/startup. Older agent guide paths are short compatibility links; their
superseded reports remain in Git history. Do not add another report for each task.

## Open the new local lab (step 2)

Double-click **Start-Agent-Lab.cmd** in this repository root (the `agent-next`
working copy). Python must be available as `python`; first launch may download uv,
Python 3.12 and frozen dependencies. Later launches reuse the prepared environment.
The authenticated page opens on http://127.0.0.1:8012. Use the launcher to reopen
it after a tab refresh; the private launch token is never written to a plaintext file.
The launcher reports an occupied port and leaves its process running.

To check Groq, open **Personal keys**, enter a personal Groq key and click **Save**.
The lab selects **Groq live · summarize text**. Enter any short message and select
**Run request**. The text goes to Groq `openai/gpt-oss-20b` and uses your quota.
Expect a short summary in the input language. Select **Groq live · understand a
walking request** to extract a start, destination and stops. Supply details in a
second message with the same session label when asked. Open the `route_draft`
event to see the combined draft with input/output inspection enabled. Place lookup
and routing are later steps.
Use **Normal foundation response**, **Deliberate handler failure** or **Wait** for
local checks without external calls. All modes use the v2 HTTP app.

Enable **Show input/output values** before running to inspect the summary and the
Groq request and response under **Stage log**. The model response preview includes
the final content and token counts when available. Without opt-in the lab retains
only metadata. Review INFO/WARNING/ERROR events, choose an earlier run,
cancel work, reset local reports or explicitly export reviewed JSON. Capture is
bounded to 20 runs, 128 events per run and bounded individual payloads; truncation
is marked without altering inputs to the core. Known keys/auth fields/private
reasoning are redacted, but free text may still contain personal information.

The Anthropic and Exa cards prepare keys for later steps. Keys stay in process
unless **Remember in Windows**
is selected. Remember uses a separate `trego.agent-v2-lab/` Credential Manager
namespace; the old lab's keys are never imported or overwritten. Values are not
returned to the browser, browser storage or `.lab/`. An unavailable vault has no
plaintext fallback. Delete/replace keys through the same card.

**Reset** clears reports and drafts. **Stop lab** cancels active work and stops
only this server; process-only data disappears. After Python code changes, stop
and relaunch to load the new version. Inspect `.lab/server.log` for safe startup
metadata. The earlier lab in the separate `source` copy remains on port 8010.

## Run the new foundation locally (step 1)

The old agent stays in place while `src/trego_agent/v2/` is built and compared.
It remains the production entrypoint; do not delete it or switch deployment yet.
The new foundation is an independent development factory using explicit settings,
the existing chat envelope and a labelled deterministic response. It has no LLM,
research, Java, session storage or dotenv access. It cannot calculate a route.

From `agent/`, after `uv sync --frozen --extra test`:

```powershell
.venv\Scripts\python.exe -m uvicorn trego_agent.v2.main:create_fixture_app --factory --host 127.0.0.1 --port 8011 --log-config logging.json --no-access-log
```

Open http://127.0.0.1:8011/docs and try `POST /api/chat` with
`{"sessionId":"learning","message":"Walk from Bratislava to Vienna."}`.
Expect a `[LOCAL FIXTURE]` reply, empty places and no routeId; nothing is stored.
Use Ctrl+C to stop it. This is a separate HTTP-only probe; the new lab above is
the preferred entrypoint and does not need this extra server.

`create_app(settings, service)` accepts the chat implementation explicitly.
`X-Trace-Id` links the HTTP response to safe stage logs. Invalid input returns a
sanitized 422, the configured chat deadline 504, and unexpected/invalid-response
failures 500. Cancellation propagates. Messages, raw session IDs, unknown-field
names and exception payloads are not logged or echoed in validation errors.
This development slice has no session lease or persistence, so it is not ready
to replace the production handler. Those protections precede real activation.

## Install and run the existing service

Python 3.11+ is required; CI uses 3.12. From `agent/`:

```powershell
uv sync --frozen --extra test
uv run --frozen uvicorn trego_agent.main:app --app-dir src --host 127.0.0.1 --port 8000 --log-config logging.json
```

Without uv, use `python -m venv .venv`, then
`.venv\Scripts\python.exe -m pip install -e ".[test]"` on Windows. Run commands
through that environment's Python. Prefer uv's frozen lock for reproducibility.

Settings read the private repository-root `.env` and process environment. See
[.env.example](../.env.example) and [config.py](src/trego_agent/config.py).
Do not publish keys or point experiments at team storage by accident.

- `AGENT_CHAT_ENABLED=false` is the default: it saves an exchange and returns a
  placeholder, rather than researching places. Storage is still required.
- Enabled chat needs `EXA_API_KEY`, the selected model key and Valkey. Explicitly
  set `AGENT_LLM_PROVIDER=groq` and `GROQ_API_KEY`, or `anthropic` and
  `ANTHROPIC_API_KEY`; the source default is Anthropic, the example selects Groq.
- Groq's allowlist is `openai/gpt-oss-20b`, `openai/gpt-oss-120b` and
  `qwen/qwen3.8-27b`. Choose with `AGENT_GROQ_MODEL`; compare profiles separately.
  Anthropic uses `AGENT_ANTHROPIC_MODEL`. Configuration is not a live access check.
- `AGENT_VALKEY_URL` falls back to `SPRING_DATA_REDIS_URL`, then local port 6379.
  `AGENT_API_BASE_URL` defaults to `http://localhost:8080` for real Java handoff.
- Nominatim uses `AGENT_NOMINATIM_BASE_URL` and an identifying
  `AGENT_NOMINATIM_USER_AGENT`; the configured public endpoint needs no API key.
- Browser CORS defaults to `http://localhost:5173`. Set `AGENT_CORS_ORIGINS` to
  a JSON list containing the frontend's actual origin, then restart the agent.

Follow [verification](VERIFY.md) before enabling real chat. Startup validates
configuration, not provider access, API migrations or route correctness.
The earlier full-pipeline lab exists in the separate uncommitted working copy.
The new v2 lab in this branch exposes the HTTP foundation, Groq connection check
and walking request interpretation.

## Stable boundary

`POST /api/chat` accepts only `{sessionId, message}`: nonblank strings, at most
128 and 4000 characters respectively. It returns `{reply, places, routeId?}`.
Only a validated saved-route readback permits `routeId`. Clarification has no
route ID. Unknown fields/invalid input return 422; overlapping turns in one
session return 409; dependency failures 502; cache/storage failures 503;
deadlines 504. Never replay an uncertain write automatically.

Current routing is walking. Preferences do not change ORS geometry. Cycling,
transit, day planning, embeddings and uploads are deferred; public availability
research also needs owner agreement. Local simulation cannot certify any of them.
