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
