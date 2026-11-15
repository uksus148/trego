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

Two desired browser assertions are deliberately marked `test.fail` for Daniil's #82:
new ready reply plus retained previous route after readback404, and a blank React
body after invalid route200. Preconditions run before those annotations so ordinary
startup/request failures are not accepted as the known defect. Unexpected passes
also fail: remove the annotations when #82 fixes the behavior. These are visible
expected failures, not passing product acceptance and not disabled tests. No route
activation/parser implementation is duplicated in this infrastructure PR.

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
provider boundaries, then `baseline.spec.ts` for UI faults and expected failures.
Shared-owner review and a reviewed integrated revision remain necessary before merge.

Local verification on November 15 against main9f65a86 plus this test-only patch:
296 API tests (including Java/Python gate checks), 494 agent tests, the isolated
transport-guard test and 79 frontend tests passed. Frontend production build/lint
passed with the existing bundle-size warning. Final actual-service/browser run:
one positive browser case, two explicitly expected #82 failures, zero unexpected
failures/skips; all HTTP/storage/cache assertions passed. Canonical PostgreSQL18
with both PostGIS and pgvector was used. This is fixture evidence, not live E5.
