# Agent stabilization: route MVP

Mukhamed approved this sequence on November 15. Baseline: main `5020cd5`,
merged #62 with both reviews. Evidence: [#60](https://github.com/uksus148/trego./issues/60),
[#61](https://github.com/uksus148/trego./issues/61) and the separate 20B/120B runs in
[#63](https://github.com/uksus148/trego./issues/63). This plan does not establish live acceptance.

## Target and boundaries

Deliver reliable chat -> sourced places -> persisted hiking route -> factual reply.
The primary model remains Groq `openai/gpt-oss-20b`; 120B is a separate comparison.
Keep FastAPI, Exa, Nominatim, Valkey and Java ownership. Public chat JSON, Java APIs,
database schema and Kafka stay on the accepted contract. Photos, embeddings, uploads,
day planning and public availability research follow after route-MVP stabilization.

Use a hybrid: the model interprets intent/evidence; application code controls actions
and renders known outcomes. The approved next reply block introduces reviewed English,
Russian, Slovak and Finnish catalogs. An unsupported/uncertain language asks for a
choice before route creation. That user-visible language boundary needs both owners'
review and a CLAUDE.md update in its implementation PR; this transport PR does not enable it.

## Sequential delivery

Every block starts from current main after the preceding PR's review, fixes and merge.
Keep each PR below 1000 changed lines and split it into logical commits. Request both
uksus148 and nnatthebest, including again after reviewable changes.

| Block | Implementation | Acceptance gate |
|---|---|---|
| S1: structured extraction | Groq strict JSON Schema; Anthropic adapter; local shape and business validation; versioned resolution cache; preflight and intent probe | Fixtures plus explicit team 20B/120B incomplete-intent and cold-resolution runs |
| S2: factual localized replies | Internal language and follow-up classification; four catalogs; typed clarification subjects; authoritative visit sequence/metrics; no model call after saved route | #60 English/Slovak-name regressions, language switching, repeated visits, no invented bearings or closure claims |
| S3: diagnosable discovery | Early missing-endpoint clarification; explicit no-source/evidence/name/type/identity/ambiguity outcomes; read-only discovery probe | The Castle -> Cathedral case identifies the precise unresolved gate |
| S4: evidenced identity correction | Turn captured S3 input/output into a regression; fix its demonstrated gate | Named landmarks route successfully when uniquely supported; ambiguous and wrong-Skok/type protections remain |
| S5: integrated acceptance | One shared scenario corpus, redacted per-model/cache reports, current ledger and issue evidence | Same-revision browser/readback/session results and idle-Valkey acceptance |

S1 merged in #64 at `204058c`. S2 merged in #65 at `4edccf3` with both approvals:
Daniil recorded 15/15 correct 20B language selections in his sample and browser
clarification clearing. S3 is prepared for review, including his formatting nits
and deduplication observation. S4-S5 are not started. His cold Rysy request left
Štrbské Pleso unresolved; S3 must capture that gate before S4 changes selection.
No paid retries or provider fallback are introduced. Strict JSON controls structure,
not geographic truth, language or availability. Dependency failures remain errors.

S3 will distinguish resolved, no sources, insufficient evidence, no geocoding candidates,
name/type mismatch, ambiguity and conflicting identity. Errors are not ordinary ambiguity.
S4's correction follows evidence: preserve sourced city/country for empty searches;
accept aliases only when grounded in sources/OSM; map types using captured categories.
Never choose the first/nearest candidate, hardcode coordinates or relax checks to force success.

## Verification and ownership

Fixtures cover all model operations, nulls/required fields, over-limit intent without
silent truncation, malformed/refused/truncated output, provenance, cache changes,
timeouts/cancellation and no replay of uncertain writes. Language/fact and discovery
regressions are added in their corresponding blocks, not counted as delivered by S1.

The shared live corpus is July Tatras, same-session follow-up, incomplete waterfall,
Sandberg, Castle -> Cathedral, Devín -> Devínska Kobyla, Dior/Budapest and original Rysy.
Run against the same commit on each model, recording cache state and stage timings.
Make five deliberate read-only repetitions per failing diagnostic case; stop on quota
or dependency errors rather than hiding them with retries. Keep real route tests explicit.
Use isolated diagnostic cache namespaces when testing cold discovery; never flush shared data.

Successful route acceptance requires saved GET, browser track/markers, correct metrics,
sources and the exact Valkey exchange. Clarification is not a built route. Verify the
first three requests after 25 minutes idle without restarting the process for #58.
The historical 20B #61 cause remains unconfirmed; 120B intent tool_use_failed is separate.
Close issues only with matching live evidence; a finite test sample is not a universal guarantee.

- Mukhamed owns S1-S5 agent code, fixtures, diagnostic commands and the combined report.
- Murat reviews dependency/storage boundaries and no-write-retry behavior; checks Java
  readback, idle Valkey and an independent 120B run.
- Daniil reviews chat behavior and runs primary 20B/browser/language/source checks.

Keys remain on team machines. Fixture development uses no live credentials or paid calls.
Update the [integration runbook](INTEGRATION_RUNBOOK.md) with actual results; preserve
historical E4 evidence and distinguish test, merge and live-acceptance milestones.
