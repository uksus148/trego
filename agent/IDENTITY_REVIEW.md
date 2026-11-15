# PR #78: audit #81 and issue #84 solution

## Conclusions and current identity evidence

[Audit #81](https://github.com/uksus148/trego./issues/81): component tests miss semantic/state mismatches.
Owner slices remain #82 frontend, #83 integration, #84 sessions and #80 editor.
Murat's [fd817bc 120B review](https://github.com/uksus148/trego./pull/78#pullrequestreview-5909075886)
passed all five exact #76/#77 routes, including full Russian and ordered stops,
with saved GET/source/endpoint checks. Earlier Russian/castle/Stupava failures are
superseded. However, all named targets were classified descriptive, and controlled
Stephansdom substitution bypassed protection and gained positive cache acceptance.
This remains an independent #78 merge blocker; runtime work below does not fix it.

Earlier fd817bc checks: 549 tests passed (92.79 s). Actual Nominatim + Valkey passed
six positive geocoding cases and three city-substitution rejections; ten uncached
requests had 1.143–1.630 s spacing; six warm repeats made none. Stupava boundary/node
share Q782928/coordinates/linkage; [OSM relation](https://api.openstreetmap.org/api/0.6/relation/2206975.json)
lists the node as label ([OSM/ODbL](https://www.openstreetmap.org/copyright)). This is public
geocoding evidence, not model acceptance or proof against the captured bypass.

## Solution for issue #84 based on #81 F4/F5 — proposed for review

Mukhamed explicitly requested this runtime increment inside existing PR #78,
overriding #84's original separate-PR sequence. Identity code and #80 stay separate.
A random owner token takes a hashed per-session Valkey lease before history lookup.
It covers history → respond → save across workers; other sessions remain independent.
Contention returns HTTP 409 with `{"detail":"Another request is processing this chat session. Wait for its result."}`
Both owners must agree 409 before merge. Clients await the active result; no POST retry.

Lease TTL is chat deadline + storage socket budget + 3 seconds; acquisition/work
remain inside the existing deadline, with at most 2 seconds for cleanup. Cancellation
releases ownership; crashes/uncertain acquisition recover by expiry. WATCH/GET/MULTI
atomically reject append if ownership expired or changed; no transaction spans model
or API calls. Token-checked Lua release cannot delete a successor's lease. A lost
commit response returns 503 without replay. Storage failures stay 503, deadlines 504.
An arbitrarily suspended worker's external Java POST is not fenced by Valkey;
uncertain routes may survive, and API idempotency/recovery remains separately deferred.

Both contents must be nonblank strings of at most 4000 characters before mutation.
Invalid exchanges return 503, preserving history/TTL without truncation. Pair retention
and six-exchange context remain; an earlier route may have committed before failure.

## Verification and remaining review

Tests use real Valkey and two ASGI apps with an explicit paused local service.
Socket-fault tests proxy real Valkey, without storage/transaction emulation.
Run `TEST_VALKEY_URL=redis://127.0.0.1:6379/0 uv run --frozen --extra test pytest -q`
from agent/; use only a disposable local instance. Agent CI provisions Valkey 8.1.
Coverage: 409/history/session independence, cancellation/expiry/crash, stale owner,
invalid exchanges, retention, lost-response/idle/outage. No Aiven/live keys used.
Full frozen suite: **551 passed in 93.77 s**, existing Starlette/httpx warning only.
Keep #84 open pending independent runtime/409 agreement; keep #76/#77 open for the
separate identity blocker. No merge, deployment or shared-data cleanup is performed.
