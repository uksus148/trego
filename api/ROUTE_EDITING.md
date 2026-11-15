# Route editing — backend implementation

This branch implements Murat's Java slice of the agreed-by-Murat
[local proposal](../docs/ROUTE_EDITING_CONTRACT.md). The proposed wire contract and
[shared examples](../docs/contracts/route-editing.examples.json) remain unchanged.
This is draft work for review; shared approval, frontend implementation and joint
browser acceptance remain separate. No agent code or frontend presentation is changed.

## Read/rebuild flow

1. `GET /api/routes/{id}/editing-context` reads the saved original endpoints, nullable
   canonical Place bindings, ordered stop occurrences and verbatim preferences in a
   short read-only transaction. GET needs PostgreSQL, not ORS or Valkey. Unknown
   query parameters return 400; unknown route is 404; storage failure is safe 503.
2. `POST /api/routes` retains its four-field input and unchanged Route response.
   It accepts optional root `startPlaceId` / `endPlaceId`; malformed/empty/non-string
   IDs are rejected rather than coerced to absent bindings. Null/omitted means unbound.
3. `RouteCreation` carries the unchanged `NewRoute` plus the two optional identities.
   `RoutePersistence.resolveInputs` resolves all distinct references together and
   checks exact numeric endpoint-coordinate equality before the routing gateway.
   Only the ordered intermediate Place DTOs leave this transaction.
4. `RouteService` builds the same ordered provider query from `NewRoute`. Endpoint
   bindings stay out of `RoutingQuery` serialization, preserving the legacy cache
   identity. Invalid bindings cannot bypass validation through a cached track.
5. A separate save transaction re-resolves/revalidates references, constructs a new
   entity and saves geometry/metrics/original points/preferences/visits/bindings
   atomically. Commit finishes before 201. The source route is never updated.

The short second read protects against a missing or changed endpoint between initial
validation and persistence without holding a database transaction during provider work.
Place mutation is not introduced by this feature. Corrupted stored coordinate bindings
fail safely instead of guessing a replacement or silently moving a point.

## Schema and compatibility

Migration `V4__add_route_endpoint_places.sql` adds nullable foreign keys and
partial indexes. It changes neither old migration files nor old rows' bindings.
Before integration, confirm V4 is still the next unused shared migration number.
Referenced endpoints cannot be deleted while saved routes use them; deleting a route
does not delete its places. Read/mapping keeps JPA entities inside the persistence layer.

Current agent writes remain four-field calls and need no agent implementation change.
Their original endpoints stay coordinate-only until a user explicitly binds an existing
Place on rebuild. Repeated visits, including an endpoint also used as a stop or equal
start/finish identities, retain their independent roles and order.

Run this branch only against an explicitly selected local/disposable database during
review. Starting it with a cloud-targeting root .env would apply V4 there; no cloud
migration or runtime activation was performed as part of the local tests below.
The automated test commands provision their own disposable resources and ignore root
configuration in Spring test applications.

## Verification and review order

From api, with Docker running and the agent's frozen test environment synced:

```sh
mvn --batch-mode --no-transfer-progress -Dagent.python=../agent/.venv/bin/python verify
```

The peer option runs the existing Nominatim compatibility checks too; they use local
fixtures, not model/provider keys. Route editor tests load the shared JSON directly
from docs, so there is one fixture source. API CI watches changes to that JSON.

Review `RouteCreation` / `RouteEditingContext`, then `CreateRouteRequest` and
`RouteController`, then `RouteService`, `RoutePersistence`, `RouteEntity` and V4.
`RouteEditingApiTest` covers the real HTTP/JPA/PostGIS/Valkey path with fixture ORS:
the shared JSON response, original-vs-snapped coordinates, nullable/single/both
bindings, warm-cache validation, independent immutable snapshots, repeats/round trips,
raw endpoints, zero stops, strict UUIDs, missing places, exact coordinate checks,
preferences, CORS, provider/storage failures and endpoint foreign-key protection.
Its isolated upgrade test seeds an actual V3 database and verifies V4 preserves its
original data without inferring identities. No shared Aiven data is used or removed.

Local verification on November 15 passed all 336 API tests with zero failures,
errors or skipped tests, including the Java/Python Nominatim peer checks. The existing
Dockerfile also built `trego-api:route-editing-local` successfully. Logs and the
verification summary are under ignored `api/target/route-editing-*` paths.

Backend acceptance does not implement the frontend draft controls, sessionStorage,
photo-store updates or new-chat-session transition. Daniil owns those through the
unchanged contract/frontend handoff. Complete the joint browser matrix on a reviewed
combined revision before claiming feature #2 ready end to end.


## Joint backend/frontend integration check

PRs #80 and #87 were reconciled with main930cb25 on November 15. Their v1 wire
examples agree. The original 41 editor HTTP/model tests passed independently, and
117 combined frontend tests, lint and production build passed after retaining #86
validation and deferred chat-answer activation. The shared v1 JSON examples are
also consumed by frontend parser tests.

The disposable actual-service profile `bash tests/integration/check.sh --editor`
passed four Chromium scenarios in12.8s with V4 applied. The manual editor case
removes one repeated visit, reorders remaining stops, swaps endpoints, binds a saved
Place, saves a new ID and restores the binding after reload. It verifies that the
source route/context stay unchanged and the editor sends zero requests to the agent.
Provider/map/photo inputs are synthetic fixtures; no Aiven migration, live hiking
correctness, deployment or shared-owner approval is claimed by this result.
