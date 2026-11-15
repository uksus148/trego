# Route editing — backend/frontend contract v1

Status: local proposal for Murat and Daniil, November 15, 2026. Murat explicitly
selected the five decisions below. Shared API agreement and implementation review
are still pending; this document does not claim a deployed editor or completed E2E.
Baseline inspected: main `9f65a86` (through #79). Read [CLAUDE.md](../CLAUDE.md) first.
Use [the synthetic examples](contracts/route-editing.examples.json) for both services'
fixtures. No real place, source, photograph or hiking measurement is asserted by them.

## 1. Selected decisions and scope

| Decision | Murat's selection | Consequence |
|---|---|---|
| Saving | Create a new route with a new UUID | The source route is unchanged; no in-place update or lost-update locking |
| Loading | Separate editing-context GET | Existing Route and agent response models stay unchanged |
| Endpoints | Original coordinates plus optional saved Place UUID | Known places retain sources/media; raw points and legacy endpoints can remain unidentified |
| Recalculation | Local draft and explicit Rebuild route | Several edits produce one deliberate POST, not a request for each movement |
| Chat | New session after a successful manual rebuild | Old chat describes the original plan; the agent receives no edited-route context |

The editor deletes or reorders intermediate visits and changes start/finish by a
map point or an explicitly selected existing Place. It supports manually built and
chat-origin routes. It preserves repeated visits and allows an empty stop list.
Keep the existing maximum of five intermediate visits, with start/end counted separately.

Natural-language editing, new place-name geocoding, category/corridor POI discovery,
automatic optimization, revision-history UI, alternative routes, new travel modes,
constraints/ranking, sharing links and GPX belong to other steps. Existing manual
place creation remains available through its own workflow. This slice does not
require a new agent request/response field or Python implementation.

## 2. State and persistence

Distinguish the committed route from the unsaved editor draft. Geometry, metrics,
markers and galleries describe the committed route until a successful rebuild.
Draft inputs may have separate preview markers, clearly labelled as unbuilt; never
draw a guessed replacement track or attach old metrics to draft points.

Flyway adds nullable `start_place_id` and `end_place_id` foreign keys to `routes`.
Existing `start_geom` / `end_geom` remain the original requested coordinates;
`geom` remains the actual provider track. Existing `route_places.position` stores
ordered intermediate occurrences. Retain `preferences` unchanged as descriptive
strings; they do not become routing constraints in this feature.

Use the next unused migration version agreed before parallel implementation. Never
rewrite V1–V3. Existing endpoint bindings stay null; do not backfill from nearest
places, names, equal coordinates or track ends. Referenced places must not be
cascade-deleted with a route; foreign keys prevent dangling endpoint references.

Bindings are optional for all callers, including the current agent, which sends
coordinates only. Thus a newly agent-created route can also lack persisted endpoint
identities. It remains editable; the user may explicitly select a known Place before
rebuilding. This limitation does not require agent changes or invented identity.

Saved routes are independent snapshots. The old route remains fetchable by its ID;
this slice does not add a parent/revision chain, delete old routes or store drafts
in PostgreSQL. A GET never contacts ORS or refreshes route/media caches.

## 3. Read API: GET /api/routes/{routeId}/editing-context

No query parameters. Success is HTTP 200 with exactly these required root fields:

```json
{
  "routeId": "10000000-0000-4000-8000-000000000001",
  "start": {"lat": 49.1, "lon": 20.1, "place": null},
  "end": {"lat": 49.13, "lon": 20.13, "place": null},
  "stops": [],
  "preferences": ["quiet scenery"]
}
```

| Field | Meaning |
|---|---|
| routeId | Exact requested saved UUID |
| start / end | Required `{lat, lon, place}`; original requested finite WGS84 coordinates, never snapped track endpoints |
| start.place / end.place | Required key; canonical existing Place when a UUID is stored, otherwise null |
| stops | Ordered `[Place]` for intermediate occurrences; duplicate UUIDs remain duplicated |
| preferences | Original stored string array, including an empty array; preserve values/order |

Place is the existing `{id,name,lat,lon,tags,photos,source}` DTO. Do not include JPA
entities, OSM identifiers or media DTOs here. A bound endpoint's coordinates equal
the canonical Place coordinates. Identity is carried by `place.id`, not a second
potentially contradictory ID field. Stop input IDs are derived as `stops.map(p => p.id)`.
There is no provider or model call to enrich an unidentified endpoint.

Malformed UUID/unsupported query yields 400 `invalid_request`; missing route yields
404 `route_not_found`; unavailable storage yields 503 `storage_unavailable`.
Unexpected corrupted persistence remains a safe server failure, not a guessed binding.
Read/map within a short read-only transaction, with Open EntityManager in View disabled.

Keep `GET /api/routes/{id}` and its existing Route JSON unchanged. Before implementation,
the new path does not exist; the frontend must not assume its presence on older APIs.

## 4. Write API: backward-compatible POST /api/routes extension

Keep the four baseline fields required. Add two optional root fields only:

```json
{
  "start": {"lat": 49.1, "lon": 20.1},
  "end": {"lat": 49.13, "lon": 20.13},
  "placeIds": ["00000000-0000-4000-8000-000000000003"],
  "preferences": ["quiet scenery"],
  "startPlaceId": null,
  "endPlaceId": null
}
```

The baseline implementation currently rejects these new fields. Implement/agree this
extension before the real frontend sends them. Existing four-field agent/manual
requests remain valid and mean null endpoint bindings; no agent change is required.

Rules:

1. `startPlaceId` / `endPlaceId` may be omitted or null. A supplied non-null value is
   a UUID of an existing Place. Empty/malformed strings or other JSON types yield 400.
2. A supplied UUID requires coordinates numerically equal to that canonical Place's
   coordinates after JSON parsing (`-0` equals `0`). No geographic tolerance or
   silent coordinate substitution. Mismatch yields 400 `invalid_request`; an absent
   referenced Place yields 422 `unknown_place`. Include both cases in fixtures.
3. Validate all endpoint/stop references and coordinate bindings before cache/provider
   work. Preserve each intermediate occurrence and the submitted order. Never add
   endpoints to placeIds automatically, deduplicate visits or drop an invalid stop.
4. Endpoint bindings may be equal to each other or an intermediate UUID. Start/end
   remain independent roles; a round trip is not permission to remove a visit.
5. All baseline validation remains: finite WGS84, both coordinates per endpoint,
   at most five non-null intermediate UUIDs, required arrays and non-null preference
   strings. Unknown root/nested fields still yield 400. Nested endpoints contain
   only lat/lon; bindings are root fields, not nested `placeId` objects.
6. Resolve the complete input with short database transactions. Perform ORS/cache
   work without holding a database transaction. Persist the route, endpoint bindings,
   original points, metrics, preferences and ordered stops atomically before 201.
7. HTTP 201 returns the unchanged baseline Route, with a new server-generated UUID,
   actual LineString, km/m/min metrics and ordered intermediate `places` only.
   GET of this ID and its editing-context must read the committed result. Even an
   ORS cache hit creates a distinct saved route. No source route ID is reused.

Keep ORS foot-hiking, provider options/snap limits and the required 24-hour track
cache. Endpoint UUIDs annotate already validated coordinates; they are not provider
waypoints in addition to those coordinates. Keep the existing routing-cache projection
of baseline request fields, resolved ordered waypoints and provider/options. Do not
accidentally change legacy cache hashes by serializing new nullable metadata fields.
Validate bindings even on a cache hit. Do not cache saved route IDs or editor drafts.

## 5. Errors and uncertain submissions

Use the current Problem Details envelope: `type`, `title`, `status`, safe English
`detail` and stable `code`. UI branches on code, never parses detail text.

| HTTP / code | Editor behavior |
|---|---|
| 400 invalid_request | Keep committed route and draft; identify invalid input without guessing another point |
| 404 route_not_found | Context cannot load; report that the source route is unavailable |
| 422 unknown_place | Keep draft; ask the user to reselect the missing referenced place |
| 422 no_hiking_route | Report that the requested points have no verified path under current options |
| 422 waypoint_not_routable | Ask to inspect/reselect the point that cannot match the available network |
| 502 routing_provider_error | Keep committed route/draft and report dependency failure |
| 503 storage_unavailable / cache_unavailable | Keep committed route/draft and report unavailable dependency |
| 504 routing_timeout | Keep committed route/draft and report timeout |

Neither 422 code proves closure, seasonality or difficulty. Keep technical failures
separate from official restriction evidence; do not widen snap radius or change provider.

Disable duplicate submission while rebuilding. POST remains non-idempotent: no
automatic retry, retry-on-reconnect, background resubmission or replay after reload.
A lost/invalid success response can leave a saved route whose ID the client did not
receive. Keep the previous visible route and the draft; state that the outcome is
uncertain. A later user-confirmed new submission can create another independent route.
Do not invent an ID or claim the server rolled back. Idempotency/recovery lookup is
a separate future decision; no Idempotency-Key contract is introduced here.

## 6. Frontend editing workflow

1. Open the editor for the active saved route. Load editing-context and check routeId,
   finite coordinates, canonical binding consistency and arrays before installing it.
   Late responses for a different route must not replace the active draft. A failed
   context GET leaves the committed map/photos usable; no guessed context fallback.
2. Copy the context into a local draft. Keep one local key per stop occurrence, not
   just per Place UUID. Up/down controls are the baseline; drag-and-drop is optional
   presentation over the same ordered occurrence list. Removing one repeated visit
   removes only that occurrence. Deleting all stops creates a valid direct-route draft.
3. Selecting an existing Place sets its UUID and canonical coordinates together.
   Moving an endpoint to a raw map point clears its UUID and old name/source/photo
   association immediately. Swapping A/B swaps the entire endpoint objects.
4. Show unbound endpoints as Start/Finish plus coordinates, not an inferred landmark.
   The server-side original input is authoritative; displayed snapped track positions
   must not silently overwrite it. Existing-place selection uses already available
   Place records or current place APIs; it does not introduce typed name geocoding.
5. Preserve preferences read from the context, without a new preference editor or
   claims of routing influence. Mark changed inputs as unsaved. Disable Rebuild when
   inputs are invalid or semantically unchanged; adding/removing an endpoint binding
   counts as a change even if coordinates stay equal.
6. Rebuild freezes the draft and sends one POST. Disable draft edits, chat submission
   and route switching until it settles. Ignore obsolete async completions. Cancel
   discards an unsent draft and restores its committed input; it does not delete a route.
7. A valid 201 is the commit point: activate the returned new ID/track/metrics/stops
   and save that ID as the tab's active route. Keep the old route on the server.
   Preserve a frozen input snapshot for the new editor state. Optional subsequent
   context refresh failure cannot undo a successful save or trigger another POST;
   show metadata loading/error until confirmed rather than reuse stale endpoint labels.
8. On rebuild failure keep the old track, metrics, active ID and chat session, while
   retaining the draft for correction. The user can explicitly discard it. Explain
   which inputs are draft; never present the old track as the result of failed edits.

Drafts are memory-only in this slice. Store only the active committed routeId in
tab-scoped sessionStorage to restore the saved route/context after reload. A refresh
discards unsaved edits; warn when feasible. This is not draft autosave, public sharing
or a promise to preserve a draft after closing the tab. On restore, validate both GET
results before enabling the editor. Keep failures local and never replay POST.

## 7. Photos, repeated visits and endpoint metadata

Keep the [landmark-media contract](LANDMARK_PHOTOS_CONTRACT.md). Media is loaded by
canonical Place UUID from one shared frontend store, maximum two concurrent GETs,
selected place first. Route edits do not change that read API or media/route error isolation.

For an edited route use its committed endpoint bindings and ordered intermediate
visits as the source of labels/media, rather than guessing endpoint UUIDs from the
deduplicated chat array. Visit order is A -> stops in order -> B. Retain repeated
occurrences in the strip; deduplicate requests by UUID only. If start and finish are
the same Place, retain both roles (a combined A/B marker is acceptable).

While editing, committed galleries remain attached to the committed route. After
success, remove old endpoint/stop views that no longer belong; cached media can be
reused for UUIDs still present. Stale gallery responses must not relabel another
place/route. Unbound raw endpoints have no media request. A bound manual Place may
validly have an empty gallery. Missing/broken photos leave name/type/source available;
an unbound point has coordinates and a role label, not a fabricated description.

Legacy/current-agent routes can still use their existing chat display behavior before
editing. Persisted editor identity is intentionally stricter: absent binding stays
null after reload. To retain a known endpoint's media on a rebuilt route, explicitly
select that Place and submit the binding. Do not retroactively claim that the agent
stored endpoint UUIDs it never sent.

## 8. Chat session transition

On successful manual rebuild, generate a fresh sessionId before the next chat POST.
Keep any displayed previous messages in a clearly separated read-only history marked
as the original plan. Do not send those messages, the old sessionId or the new route
to the agent as implicit context. Do not mutate/delete the old Valkey session.

Suggested UI wording: "Manual edits are not sent to the assistant. A new message
starts a new plan." This is a local status, not a fabricated assistant reply.
The editor does not add a session exchange. Failed/cancelled edits do not reset chat.

A new session has no knowledge of the edited route. No promise that "remove another
stop" refers to the current map. New explicit planning messages use the existing
chat contract and its normal route/clarification behavior. Synchronizing manual edits
with the agent requires a separate contract and Mukhamed's implementation.

## 9. Ownership, delivery and compatibility gates

| Owner | Deliverable |
|---|---|
| Murat | Separate read DTO/endpoint; optional POST bindings; JPA/Flyway persistence; reference validation; unchanged routing/cache semantics; API/integration tests |
| Daniil | Draft/committed state; occurrence-aware controls; map/place selection; reload behavior; media reuse; session transition; matching mocks and UI tests |
| Mukhamed | Review compatibility of unchanged four-field route writes and Route/chat responses; no new agent code is required for this scope |
| Murat + Daniil | Agree this wire/fixture version, review each other's PRs and run the same-revision acceptance matrix |

Implement in existing feature packages/Maven module using constructor injection,
Lombok where appropriate, application-layer workflows and separate JPA/HTTP models.
Avoid generic editing frameworks or new services. Coordinate Flyway naming before
parallel migrations. Deploy the reviewed backend/migration before enabling the real
editor. An older API rejecting new fields is not permission to drop endpoint bindings
and silently retry the POST. Fixtures must not call live providers or model APIs.

Current Route/Place/Photo/chat shapes and four-field requests stay valid. The new
GET and two optional POST root fields are shared proposals until reviewed. This local
document does not itself amend the team's accepted contract or activate the feature.
Use normal PR review, at least one independent approval and affected-owner agreement.
Retain the immutable recovery release; do not move its tag to include this work.

## 10. Acceptance matrix

Record tested revisions, entry mode, cache state, timings and created IDs. Use disposable
database/cache and fixture ORS for failure cases; do not disrupt shared Aiven services.

- Legacy agent/manual four-field POST and unchanged Route GET still pass.
- Legacy and current-agent route context returns original requested endpoints and
  null bindings even when its track is snapped nearby. No identity backfill occurs.
- Endpoint UUID bindings survive rebuild/reload; source route/context remain unchanged.
- Both bindings omitted/null, one binding present and both present are supported.
- Bound coordinates match canonical Place; mismatch is 400 and missing UUID is 422,
  before cache/ORS/write. Malformed/unknown fields and six stops also fail before work.
- Delete/reorder several visits, including X -> Y -> X; delete just one X occurrence;
  no automatic endpoint insertion, deduplication or changed visit order.
- Raw point selection clears old identity; selecting a saved Place restores explicit
  binding. Equal A/B UUIDs and a UUID repeated as a stop retain separate visit roles.
- Delete all stops and rebuild a direct route. ORS/Valkey limits and honest failures remain.
- Each successful rebuild has a new fetchable UUID, correct editing-context and real
  geometry/metrics. An equivalent provider-cache hit still saves a separate route.
- Preserve preferences and old route cache-key identity; binding validation cannot be
  bypassed by a warm track cache. No endpoint metadata fields accidentally rekey legacy inputs.
- Cancel/dirty reload behavior, duplicate-click protection, response races, failed
  context loads and uncertain POST outcomes do not overwrite or auto-replay work.
- New-session transition happens once after valid 201, including when later context
  refresh fails; never after failed/cancelled rebuild. Old history is clearly historical.
- Endpoint and stop thumbnails, original viewer, sources and information-only cards
  follow the new committed context. Media failure cannot repeat a route/chat POST.
- Live manual E2E without a running agent: build/save -> open editor -> remove/reorder
  two or more stops -> change A/B -> rebuild -> reload -> verify ordered visits, metrics,
  bindings and photos. Read the original ID to prove it was not modified.
- Separately open a chat-origin route and edit it; original endpoint bindings can be
  null. Validate new session behavior with a subsequent explicit planning request,
  without claiming context-aware conversational editing.

All items are pending implementation/verification. Existing photo E2E evidence or a
successful old route does not establish acceptance of this editor. General city
discovery issues remain separate; manual editor E2E must be independently executable.
