# Baseline fixture acceptance

Owner: Murat; frontend boundary review: Daniil; agent fixture review: Mukhamed.
Implements the test/infrastructure slice of [#83](https://github.com/uksus148/trego./issues/83),
following the review hub [#81](https://github.com/uksus148/trego./issues/81).

## Run

Prerequisites: Docker with sufficient disk, JDK21+, Maven, Node24+, Python3.12 and uv.
On Linux, install Chromium system libraries with Playwright's `install --with-deps
chromium` command first (CI does this). From the repository root:

```sh
bash tests/integration/check.sh
```

The wrapper installs frozen dependencies and Chromium, then runs the baseline. With
dependencies already installed, `python tests/integration/run.py` runs just the stack.
Its `--python /absolute/path/to/python` option can reuse an existing synced agent
environment. There are no required cloud keys or root `.env` edits.

## What is real and what is a fixture

Real React/Vite, FastAPI factories/discovery/handoff/sessions, Java HTTP/JPA/Flyway,
canonical PostgreSQL18/PostGIS/pgvector and Valkey run on disposable loopback ports.
The API uses a clean Maven build; applied Flyway script names must exactly match
this checkout's sources, so stale target files from another branch cannot leak in.
No shared Compose volumes, Aiven services, production data or migration V4 are used.
The runner removes only its own container IDs and process groups, including on failure.

Groq20B responses are synthetic structured JSON, not model execution. Exa and
Nominatim HTTP are strict in-process fixtures. The agent transport forwards only
the exact local Java API origin and rejects unknown provider hosts/paths. Its negative
test proves there is no network fallback. Java ORS points at a local strict HTTP fixture;
media uses a synthetic local catalog, automatic discovery is disabled, and unused
metadata endpoints point at the local fixture too. Browser routing supplies a blank
map style, empty font CSS and a synthetic image, and rejects other external URLs. This verifies
integration and error handling, not live geographic correctness or photographic rights.

Child environments are constructed from an allowlist. Spring config import is empty,
the test agent disables dotenv before importing its default app, and the test Vite
config disables envDir while reusing production plugins. No developer keys are read
to configure these services. Package/image downloads happen during setup, outside
the provider-fixture boundary. This is application-level containment, not an OS sandbox.

## Assertions and known findings

The shared [baseline corpus](../../docs/contracts/baseline.examples.json) uses only
accepted Route/Place/chat semantics. Java, Python and TypeScript consume it directly;
no schema generator or duplicate editor DTO is introduced. The actual-service run
checks sources/coordinates, ordered X→A→X visits, independent route GET, a distinct
saved ID without a second ORS request, incomplete-intent zero writes, persisted chat
history, both database extensions, and catalog/empty media results. Browser checks
use the real chat/API, inject a media-only503, and require exactly one GET on Retry
without another POST or lost route.
The browser readback is matched to the routeId returned by that browser's chat
response, not a setup route. A failed readback must not append a new ready reply;
any retained route must separately show a visible previous-route status label.

The two #82 defects were corrected by merged #86. Their browser assertions are now
ordinary required regressions: a failed readback must suppress a new ready reply
and label any retained previous route; invalid route200 must remain recoverable
without blanking React. All three browser cases must pass, with no expected failures,
unexpected failures or skips. No route activation/parser implementation is duplicated
in this infrastructure PR.

The synthetic provider protocol follows merged #78: complete and incomplete intents
explicitly carry advisory `descriptiveTargets: []`, and research uses the exact-target
query prefix. A factory-level compatibility test exercises both cases through actual
discovery. Named fixture targets never gain descriptive authorization; unexpected
provider/query protocols still fail closed.

The fixture workflow does not cover the pending #80 editor, #78 named-target guard,
same-session races, public API security, live provider quotas or navigation safety.
It preserves hiking options, current budgets, source continuity and no POST retries.

## CI and evidence

`acceptance.yml` runs the stack for service/infra/corpus/harness changes.
`frontend.yml` adds frontend tests/build/lint for frontend/shared examples.
Existing API/agent workflows and main rulesets are unchanged; these conditional jobs
are not made globally required checks. #80's API-workflow edit is not overwritten.

Ignored `api/target/fixture-e2e/` contains service/build logs, exact Git revision and
working-tree diff digest, assertions, provider counts and Playwright JSON. CI uploads
only named synthetic logs and JSON, for seven days. Logs redact checkout paths and
fixture credentials; no HAR, trace, video, .env or generic target archive is uploaded.
Inputs are synthetic public constants; never point this harness at private locations.
Existing unit suites and actual-service fixtures remain separate from live evidence.

Review `run.py` for process/DB isolation and HTTP assertions, `fixture_agent.py` for
provider boundaries, then `baseline.spec.ts` for required UI regressions.
Shared-owner review and a reviewed integrated revision remain necessary before merge.

Current integrated verification on November 15 against main `7833de8` (merged #78
and #86) plus this PR: all HTTP/storage/cache/migration assertions passed, and all
three Chromium cases passed in 9.8 seconds with zero expected/unexpected failures
or skips. Six deliberate route POSTs reused one ORS fixture request; only V1–V3
migrations were applied. The shared-corpus and outbound/protocol controls passed
(four tests), and all 95 frontend tests, production build and lint passed. These
results use disposable local storage and synthetic providers, not live E5 evidence.

Historical verification on November 15 against main9f65a86 plus the original test-only patch:
296 API tests (including Java/Python gate checks), 494 agent tests, the isolated
transport-guard test and 79 frontend tests passed. Frontend production build/lint
passed with the existing bundle-size warning. Final actual-service/browser run:
one positive browser case, two explicitly expected #82 failures, zero unexpected
failures/skips; all HTTP/storage/cache assertions passed. Canonical PostgreSQL18
with both PostGIS and pgvector was used. This is fixture evidence, not live E5.


## Saved-route editor profile

With the matching API and frontend editor, run `bash tests/integration/check.sh --editor`.
This enables the real editor for the local frontend and adds a fourth browser case.
The case starts from a manual API save, removes one repeated visit, reorders the
remaining visits, swaps endpoints and explicitly binds an endpoint to a saved Place.
It verifies the new route/context, unchanged source route, preserved preferences,
reload restoration and zero agent requests during editing. Baseline provider calls
remain explicit fixtures; this is not live geographic acceptance. CI runs this profile.

Combined #80/#87 verification after current-main integration: four Chromium cases
passed in 12.8 seconds with no failures/skips; actual V4, API/storage/cache assertions
passed. The editor case has no dependency on an AI provider or a running AI service.
