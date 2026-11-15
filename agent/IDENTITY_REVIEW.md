# PR #78: identity decision and audit #84 runtime

## Narrow MVP identity policy

Murat [explicitly agreed option 1](https://github.com/uksus148/trego./pull/78#issuecomment-6889549062)
on November 15, following the [design discussion](https://github.com/uksus148/trego./pull/78#issuecomment-6889496221).
Every target now retains requested-name verification. `descriptiveTargets` is advisory:
model classification cannot authorize an identity change or positive cache promotion.
Evidenced names, translations, aliases and features retain existing acceptance paths.
Otherwise an unbound description, including the TikTok-waterfall example, asks for an
explicit place name through the existing no-write clarification. An extra turn is an
accepted MVP tradeoff; automatic descriptor resolution is not promised. A fresh named
request must independently resolve normally, not treat a model-interpreted "yes" as
authorization. Server-bound candidate confirmation is a separate deferred feature.
Daniil's agreement, independent review and matching-head acceptance still gate merge.

The correction always supplies the original discovery target to the existing guard;
it changes no public DTO, provider call policy, routing option, source/OSM binding,
session lease or cache TTL. Cached resolutions still undergo selection feedback;
rejected substitutes cannot be promoted and accepted bad entries are demoted.
Intent extraction remains model-interpreted: this is a verification boundary,
not a guarantee of infallible multilingual understanding of the raw sentence.

## Evidence and limits

Murat's [fd817bc 120B review](https://github.com/uksus148/trego./pull/78#pullrequestreview-5909075886)
passed all five exact #76/#77 saved routes with sources/order/readback, superseding
older Russian/castle/Stupava failures. It also captured the descriptive-role bypass.
Those historical successes do not certify this correction. Earlier public Nominatim/
Valkey checks covered linked Stupava representations and substitution rejection;
[OSM relation evidence](https://api.openstreetmap.org/api/0.6/relation/2206975.json)
remains public [OSM/ODbL](https://www.openstreetmap.org/copyright) data, not a production override.

Regression controls use actual discovery with explicit HTTP/cache fixtures: captured
misclassified roles on Groq 20B/120B and Anthropic, empty/unusable verification, bad
positive-cache demotion, repeated named stops, translated identities and genuine
description clarification without handoff. These are not live model runs.
Corrected local suite: **574 passed in 146.70s**, zero skips; compilation/lock checks passed.
Run `TEST_VALKEY_URL=redis://127.0.0.1:6379/0 uv run --frozen --extra test pytest -q`
from agent/ with disposable Valkey; compilation and offline lock checks also apply.
Repeat the exact five #76/#77 requests on the corrected revision with separate 20B/
120B/cache evidence, source/order/readback and relevant browser/media controls.
Stop on quota errors; no provider/POST retries. Keep #76/#77 open pending acceptance.

## Issue #84 based on audit #81 — unchanged runtime increment

Mukhamed requested runtime work inside this PR. A random-token Valkey lease covers
history/respond/save across workers; contention returns 409 before provider work.
TTL is chat deadline + storage socket budget + 3s, cleanup is bounded to 2s; expiry,
WATCH-checked append and token-checked release protect successor session ownership.
Both exchange contents must be nonblank strings of at most 4000 characters before
mutation. Invalid content/storage returns 503; deadlines return 504. No truncation or
write replay; a suspended worker's Java POST is not fenced, so committed routes may
survive failure. Both owners must agree 409. Real-Valkey/two-app and fault-proxy tests
cover these boundaries. Earlier 881fb5c independent checks passed 551 tests; identity
acceptance remains separate. No merge, deployment, shared writes or issue closure.
