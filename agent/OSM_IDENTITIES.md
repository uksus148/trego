# S4b: evidenced OSM landmark identity

Baseline: main `cf5fe23`, through merged #67. Both owners approved the short
provisional resolution-cache lifecycle, and Daniil verified primary 20B TTL/reuse
and Rysy routing rejection. The remaining #66 review gates were castle type
mismatch and a varying cathedral name mismatch. #67 also observed two accepted
identities for a fresh Štrbské Pleso resolution; the actual failed model tags were
not recorded, so that observation alone does not justify choosing the lake.

## Independent public evidence

Three public Nominatim searches on November 15, 2026 used the project's contact
User-Agent, limit 8, namedetails=1 and extratags=1, spaced at least one second apart.
No private team credentials or Groq/Exa/ORS calls were used. Reduced public records
are preserved in `tests/test_osm_feature_evidence.py`, with OSM/ODbL attribution.
These are fresh observations, not the team's historical model or provider payloads.

| Search | Observed identity and attributes | Previous gate |
|---|---|---|
| Bratislava Castle, Slovakia | [way 1128350263](https://www.openstreetmap.org/way/1128350263); primary tourism/attraction, extra historic=castle; English alias Bratislava Castle | Type-only comparison rejected attraction despite the explicit castle attribute |
| St. Martin's Cathedral, Bratislava, Slovakia | [relation 16609274](https://www.openstreetmap.org/relation/16609274); primary amenity/place_of_worship, extra building=cathedral and historic=church; English alias Saint Martin's Cathedral | St./Saint token mismatch can reject the recorded alias |
| Štrbské Pleso, Slovakia | administrative relation, winter-sports way, lake way, hamlet node and cadastral relation | A shared name is genuinely insufficient to select a physical entity |

Public data source: [Nominatim search](https://nominatim.openstreetmap.org/search),
[OSM attribution/license](https://www.openstreetmap.org/copyright).
The search may change; coordinates and IDs in fixtures are never production overrides.

## Selection changes

Request `extratags=1` and retain typed extra attributes in the candidate cache.
Null extra tags normalize to an empty mapping. Request options already participate
in cache hashing, so old searches without extra tags cannot mask new retrieval;
no cache is flushed, and the shared Nominatim gate/cooldown is unchanged.

Keep existing primary-type checks and also recognize exact OSM attributes: historic=castle,
building=cathedral, church/cathedral building or historic=church for church, and
water=lake. A generic attraction, a descriptive sentence mentioning a castle or an
unrelated building is insufficient. Attribute values are not parsed as instructions.
Both name/alias and type constraints still apply, and multiple accepted identities
remain unresolved. No importance/first/nearest ranking or radius/provider fallback.

Normalize leading St./St to Saint only in names containing cathedral/church.
Do not globally translate street abbreviations or equate unrelated saints. The
normalization applies symmetrically to requested names and existing OSM aliases.

Recognized entity tags now constrain jointly rather than form a broader union:
lake+resort cannot select whichever object happens to come first. Prompt resolution
for one primary source-supported category, while leaving descriptive tags compatible.
Do not infer lake from the name Štrbské Pleso or hardcode Tatras geography. Without
adequate type evidence, clarification remains the correct outcome. Model prompt
changes invalidate resolution identity naturally through the full-request hash;
the v3 lifecycle/feedback policy itself is unchanged.

## Acceptance

467 local fixture tests passed, including both transports' actual discovery/handoff,
canonical coordinates/OSM/source retention, cached extra attributes, conflicting
tags, multiple identities, wrong-Skok guards and old-option cache isolation.
This is not live model or browser route acceptance.

On the reviewed revision, follow the [discovery probes](DISCOVERY_DIAGNOSTICS.md)
for Castle -> Cathedral, original Rysy and July Tatras. Record five deliberate
read-only cold runs per model, allowing quotas to replenish and stopping on failures.
Keep 20B and 120B evidence separate. Inspect reason/counts; then run the explicit
browser route test with saved GET/source/metric/session verification. A source-
supported lake/resort must select the corresponding OSM identity; untyped or truly
ambiguous input must clarify. Rysy should retain the distinct no-match routing
outcome after successful discovery. Do not replace waypoints to force a track.

## Issue #69: settlement boundaries and unresolved roles

The issue's 120B run on `cfc4c64` found Bratislava/Vienna by name but rejected
both as city endpoints. Two public Nominatim searches on November 15 confirmed:

| Search | OSM identity | Primary category/type | Settlement evidence |
|---|---|---|---|
| Bratislava, Slovakia | [relation 1702499](https://www.openstreetmap.org/relation/1702499) | boundary/administrative | addresstype=city, extra place=city |
| Vienna, Austria | [relation 109166](https://www.openstreetmap.org/relation/109166) | boundary/administrative | addresstype=city; no extra place attribute |

Reduced records with attribution live in `tests/test_settlement_boundaries.py`.
For city/town/village/hamlet constraints, administrative boundaries can use exact
settlement labels from addresstype or extratags.place. Multiple recognized labels
must agree with the requested type. A generic boundary, admin_level, county/state
classification, unrelated attraction or conflicting city/village labels cannot
establish a city. Name/alias, joint feature, identity conflict and ambiguity checks
still apply. Representative coordinates remain the validated Nominatim result;
no production city IDs or coordinate overrides are introduced.

Candidate caching now uses `gopstop:nominatim:search:v3`: earlier serializers
discarded addresstype, so merely extending the model would leave Vienna broken
behind an old 24-hour candidate entry. Old namespaces remain untouched; rate
gating and positive/empty TTLs are unchanged. Resolution v3 is a separate cache
whose selection-aware policy remains unchanged. No resolver prompt change is
needed for this fix, preserving reusable model results during the quota shortage.

When normalized names cannot be found literally in user text (e.g. Russian
"братиславы"/"вены" vs intent Bratislava/Vienna), clarification identifies the start,
destination or intermediate-stop number in EN/RU/SK/FI. It does not guess an
inflected/transliterated spelling or echo fabricated intent text. Literal user
names may still be echoed; repeated visits retain their own stop numbers.

The fixtures exercise both Groq profiles and Anthropic through actual discovery,
including final cache acceptance. Team live/model/browser acceptance remains:
first run geocoding/discovery fixtures, then a deliberately bounded read-only
city probe after quota is available; verify exact identities and use a hiking
request for route acceptance. Cycling, corridor POI search and photos from the
original #69 prompt remain outside this bug and are not enabled by it.

## Issue #76: requested settlements

The initial 20B report on main `db9b0d3` inferred two Vienna candidates followed by
`outside_context`. Daniil's subsequent shared-cache discovery inspection changed
the diagnosis: the resolver mapped requested Bratislava to Bratislava Castle
(way 1128350263), and requested Vienna to Kahlenberg, with two peak nodes
195763017 and 12962364097. This was a fresh run, not recovery of the original
unlogged payloads. A wider radius could route to an unrequested mountain.

Independent public searches on November 15 used the project's contact User-Agent,
the usual limit/format/name/extra options, and more than one second between calls.
`Vienna` and `Vienna, Austria` each returned city relation 109166, Q1741.
`Kahlenberg, Austria` returned the two reported peak nodes at 48.2763418/16.3330680
and 48.2282682/15.4749161. Reduced records with OSM attribution are preserved in
`tests/test_requested_settlement.py`. No live Groq/Exa/ORS calls were made here.

Research now asks for information about the exact target; route context is only
research context. The resolver receives the target string itself, not a route-wide
"Find hiking place" instruction. Its prompt prohibits attraction substitution.
Changed prompt/input identity naturally bypasses old resolution-cache entries;
changed research queries have distinct Exa keys. No shared keys are flushed.

Application verification supplements the prompt. An unchanged name/query with
attested aliases, or a settlement with aliases for both requested/resolved names,
needs no extra request. Otherwise search the original target once using the normal
Nominatim cache/options/gate. An attraction sharing a city's alias does not bypass
verification when the resolver changes the name or query. Only exact
name/alias matches with city/town/village/hamlet evidence can constrain the identity;
do not infer a city from a nearby peak or an arbitrary boundary. Country qualifiers
remain in the verification query; the name comparison uses its first comma component.
If an independently established settlement conflicts with the resolution, or has
multiple identities, return `requested_identity_mismatch`, with no place or route
writes. Never substitute the verification coordinates into an attraction result or
invent a supporting research source. Attested multilingual city aliases need no
extra request. Descriptive landmark discovery remains supported when the original
phrase does not establish a settlement. Model interpretation is still fallible.

The verification adds at most one original-target lookup per geocode invocation,
sharing its existing total timeout. Contextual reconsideration reuses the candidate
cache; errors remain errors, with no automatic provider/model retries. Candidate
v3 already stores the required fields. Positive/empty TTLs, selection feedback and
the 25 km ambiguity filter are unchanged. A rejected resolution cannot be promoted
to the accepted 24-hour lifetime.

Internal/probe `matches` retain resolver-name/type-matched OSM type/IDs and minimum
anchor distance before contextual filtering. `requestedMatches` records constraining
settlement identities on a mismatch. No names, queries or source bodies are added
to routine logs or public chat JSON. Both owners review the policy; live closure
requires the two original English prompts on the reviewed revision with exact
city identities, then saved route/browser/source checks. Fixture success alone
does not establish that the live model now resolves both cities.
