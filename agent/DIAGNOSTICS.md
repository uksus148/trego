# Agent provider diagnostics

Issue [#61](https://github.com/uksus148/trego./issues/61) records one failed resolution
on main `e6b8145`, after successful research and before Java ingestion/routing.
The historical log has no provider status/code: it cannot establish a quota,
transport, tool-generation or schema cause. The model client uses HTTP, not gRPC.
The subsequent clarification may involve caches and does not prove cold-call recovery.

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

One invocation makes one fresh Exa search and, if sources exist, one model resolution.
It bypasses both caches without deleting keys, needs no Valkey, and never calls
Nominatim, Java or ORS or writes places, routes or sessions. There are no automatic
paid retries or fallback providers. Run it deliberately, after the account's token
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
schema/generation change and owner review. Do not claim #61's original cause is fixed
from fixtures or close it before a team live rerun identifies/verifies that cause.
