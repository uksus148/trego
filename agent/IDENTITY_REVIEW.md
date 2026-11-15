# PR #78: identity acceptance review

## Observed blockers

Murat's [120B review of 2acec61](https://github.com/uksus148/trego./pull/78#pullrequestreview-5908981867)
supersedes his earlier approval. Both original English city requests passed, but
the exact full Russian #77 request failed intent validation; #76's two-stop request
lost Castle in the query, and the three-stop request could not select Stupava.
HTTP 200 clarification is not a route pass. Earlier 20B evidence covers fewer cases.

## Corrections proposed for both owners

**Intent references.** A free-text classification list redundantly copied target
strings and could fail a cross-field equality validator even under strict JSON.
That validator is the only explicit `value_error` producer in this RouteIntent
snapshot, matching the new 120B diagnostic. The rejected output was not captured;
its exact content is unknown. Replace copied strings with enum roles `start`,
`end`, `stop:1` through `stop:5`. Strict generation excludes interests/place names
from that list. Local validation still rejects missing referenced targets using
`invalid_target_reference`; safe diagnostics now include allowlisted field names.
A repeated target classified as named anywhere retains named identity protection.
Classification remains model-interpreted. This is an internal schema change,
requires a restarted agent and both-owner review, and adds no model call.

**Lossy search hint.** Before geocoding/cache lookup, if the query's first component
is a strict token subset of the complete sourced name, use that complete name and
retain geographic qualifiers. Thus the observed name `Bratislava Castle` with query
`Bratislava, Slovakia` searches `Bratislava Castle, Slovakia`. This also corrects
cached defective hints. Different-language queries remain available. Selection
still checks requested identity, names, features and context; no source is invented.

**Linked settlement representation.** A single administrative boundary and a single
place node can represent one settlement. Select the boundary only when the matched
pair has the requested settlement type, exact requested aliases, identical validated
coordinates, the same valid Wikidata Q ID, and matching boundary `linked_place`.
Keep both OSM IDs/counts in diagnostics. Multiple boundaries/nodes or absent or
conflicting evidence stay ambiguous. This selects one representation; it neither
merges stored places nor changes ingestion uniqueness. No runtime OSM/Wikidata
lookup, coordinate threshold, nearest ranking or hardcoded city identity is added.

Owner question: is this narrowly evidenced boundary representation acceptable for
ingestion/source/media continuity? Existing node records remain separate. The
public DTO and source binding stay on the agreed contract.

## Independent checks on November 15

Public Nominatim with the project's contact User-Agent returned Stupava boundary
relation/2206975 and place/town node/26036885, both Q782928 at
48.273044 / 17.0329528; the boundary has linked_place=town. A third suburb is excluded
by the requested town type. Independent [OSM relation data](https://api.openstreetmap.org/api/0.6/relation/2206975.json)
explicitly includes node/26036885 as its label. These observations inform the generic
policy; runtime uses the returned Nominatim evidence. Public data:
[OSM contributors / ODbL](https://www.openstreetmap.org/copyright).

Actual `NominatimGeocoder`, public HTTPS Nominatim and a disposable local Valkey
8.1 container passed these deliberate scenarios with no provider/cache doubles:

| Input / constraint | Observed selected identity |
| --- | --- |
| Bratislava city | relation/1702499 |
| Vienna city | relation/109166 |
| Full castle name with truncated Bratislava query | way/1128350263 |
| Devín Castle | way/722938329 |
| Devínska Kobyla peak | node/715814546 |
| Stupava town, with both matching OSM representations | relation/2206975; both IDs retained |
| Requested Bratislava, resolved Bratislava Castle | requested_identity_mismatch; no location |
| Requested Vienna, resolved Stephansdom | requested_identity_mismatch; no location |
| Requested Vienna, resolved Kahlenberg | requested_identity_mismatch; no location |

Ten uncached HTTP requests; start-to-start gaps 1.143–1.630 seconds, through the
existing token gate and completion cooldown. A repeat of all six positive cases
made zero HTTP requests. No Java/route/session writes occurred. This proves the
geocoding correction against current public data, not model or route acceptance.
New regression tests call real schema/selection functions directly; no new mocks.

Frozen Python 3.12 suite: **549 passed in 92.79 seconds**, with the existing
Starlette/httpx deprecation warning. Compilation, offline lock validation and
`git diff --check` passed; historical E4 evidence is preserved. Commands from `agent/`:
`uv run --frozen --extra test pytest -q`, `uv run --frozen python -m compileall -q src tests`,
and `uv lock --check --offline`. The existing suite retains its original provider
fixtures; its result is distinct from the real Nominatim/Valkey check above.

## Remaining acceptance before merge or issue closure

Keys remain on team machines. No live Groq/Exa/ORS, Aiven persistence or browser
acceptance was performed here. Primary 20B and independent 120B must each run the
five exact prompts in #76/#77 on the corrected revision, with cache conditions and
fresh sessions recorded. Use the existing private identity probe to compare intent,
resolution, selection and ordered stops. Stop on quota/provider failure.

For successful two/three-stop cases capture actual route POST, city endpoints,
ordered intermediate UUIDs, sources, saved GET, session and browser track. Preserve
the Rysy and July Tatras controls and media error isolation. If the Russian intent
still fails, attach safe validation fields/type and a locally sanitized intent
object for engineering review; do not log raw provider output or retry failed POSTs.
Both owners must re-review the new internal schema and settlement policy. Keep
#76/#77 open until matching live evidence establishes their acceptance.
