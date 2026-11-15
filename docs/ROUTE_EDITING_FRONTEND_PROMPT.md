# Implement the trego. route editor in the frontend

You are working with Daniil on the React/TypeScript frontend. Implement a reviewable patch in his checkout. Read the current root CLAUDE.md, docs/ROUTE_EDITING_CONTRACT.md and docs/contracts/route-editing.examples.json before editing. If the two local attachments are missing, ask Daniil for them. The contract governs the wire format. This handoff targets main at 9f65a86. Check the current files and preserve teammate changes. All UI text, comments and commits are in English. Work in frontend/. Leave API, agent, infrastructure and the shared contract to their owners. Deliver the local diff and test results for review.

## 1. Wire types and request boundary

In src/types.ts add the following types, extend RouteRequest with optional nullable startPlaceId and endPlaceId, and add getRouteEditingContext(routeId: string): Promise<RouteEditingContext> to ApiClient. Preserve Route, ChatRequest and existing createRoute callers.

```ts
export type EditingEndpoint = LatLon & { place: Place | null }
export type RouteEditingContext = {
  routeId: string
  start: EditingEndpoint
  end: EditingEndpoint
  stops: Place[]
  preferences: string[]
}
```

In src/api/realApi.ts use the Java API base URL, encode the route ID and GET /api/routes/{id}/editing-context without query parameters. Receive unknown JSON. Validate the requested UUID, both finite WGS84 points, required nullable place, complete canonical Place shape including legacy Photo arrays, exact numeric coordinate equality for each binding, at most five stops and the string array of preferences. Preserve array order and multiplicity. For rebuild, accept exactly HTTP 201 with a valid baseline Route, valid new UUID different from the source, LineString in lon/lat order, finite metrics and submitted stop IDs in order. The existing generic request<T> casts JSON and accepts any 2xx. Add checks at the route boundary; leave unrelated agent and media calls alone. Preserve ApiError.code for recognized HTTP failures. An unexpected success status, unreadable JSON, invalid success payload or network loss after sending is an uncertain save. Never retry a POST in the client.

## 2. Use this draft core

Place this in src/lib/routeEditing.ts after adding the types above. Validate context at the boundary before calling fromContext. Use immutable updates to the endpoint and row arrays. The canonical payload comparison intentionally ignores local row keys, display text and photo metadata.

```ts
import type { EditingEndpoint, LatLon, Place, RouteEditingContext, RouteRequest } from '../types'

type Row = { key: string; place: Place }
export type Draft = {
  start: EditingEndpoint
  end: EditingEndpoint
  rows: Row[]
  preferences: string[]
}

export function fromContext(c: RouteEditingContext): Draft {
  return {
    start: { ...c.start }, end: { ...c.end },
    rows: c.stops.map(place => ({ key: crypto.randomUUID(), place })),
    preferences: [...c.preferences],
  }
}

export function rawEndpoint({ lat, lon }: LatLon): EditingEndpoint {
  return { lat, lon, place: null }
}

export function boundEndpoint(place: Place): EditingEndpoint {
  return { lat: place.lat, lon: place.lon, place }
}

export function removeVisit(draft: Draft, key: string): Draft {
  return { ...draft, rows: draft.rows.filter(row => row.key !== key) }
}

export function moveVisit(draft: Draft, key: string, delta: -1 | 1): Draft {
  const from = draft.rows.findIndex(row => row.key === key)
  const to = from + delta
  if (from < 0 || to < 0 || to >= draft.rows.length) return draft
  const rows = [...draft.rows]
  ;[rows[from], rows[to]] = [rows[to], rows[from]]
  return { ...draft, rows }
}

export function toRequest(d: Draft): RouteRequest {
  return {
    start: { lat: d.start.lat, lon: d.start.lon },
    end: { lat: d.end.lat, lon: d.end.lon },
    placeIds: d.rows.map(row => row.place.id),
    preferences: [...d.preferences],
    startPlaceId: d.start.place?.id ?? null,
    endPlaceId: d.end.place?.id ?? null,
  }
}

export function isDirty(initial: Draft, current: Draft): boolean {
  return JSON.stringify(toRequest(initial)) !== JSON.stringify(toRequest(current))
}
```

Swap complete endpoint objects. Selecting a map coordinate uses rawEndpoint even if it is identical to the previous point. Selecting an existing Place uses boundEndpoint without rounding. Removing every row is valid. Preserve descriptive preferences verbatim.

## 3. Implement the request lifecycle in useTrip

Keep useTrip as the single owner of the committed trip and chat. Extract editor state or a small reducer if needed. App and panels receive state and callbacks; components never issue route writes. Expose open, cancel, move/remove occurrence, replace/swap endpoints and rebuild. Keep the committed route and its display inputs separate from initialDraft/currentDraft. A local error belongs to the editor. useAsyncTask currently turns exceptions into strings and React busy state cannot block a second click in the same tick.

Implement these transitions in this order:

1. Open: capture the active route ID and increment a request generation ref. GET context. Install only while that ID and generation still match. Cancel, route replacement and unmount invalidate pending completions. A failed GET shows an editor error with a GET-only retry; leave the track usable. Never initialize from snapped geometry or chatPlaces.
2. Edit: input actions only update the draft. Route changes outside the editor discard its stale state, with an unsaved-changes confirmation when appropriate. Prevent a rebuild while another trip operation is pending. Guard action handlers as well as disabling buttons.
3. Submit: reject absent, invalid or unchanged draft. Acquire a synchronous ref lock **before the first await**. Capture source ID, generation, immutable submitted draft and a fresh toRequest payload. Freeze draft, cancel, chat, manual build and route switching. Exactly one createRoute call. For an uncertain prior outcome require an explicit confirmation before a new user-initiated submission.
4. Recognized error: retain source route, session, draft and metrics, release lock; map Problem Details codes per contract section 5. For uncertain outcomes display “The route may have been saved. Submitting again can create another route.” Never infer closure or season from routing failure. An old completion must not clear a newer operation's lock.
5. Valid 201: synchronously commit returned route, frozen submitted inputs and new active ID to application state, archive current messages as read-only original-plan history, clear active messages, generate a fresh session ID once, clear former selection, chatPlaces and stale manual route display inputs. Treat storage writes as best effort. Do this outside any effect or render that React might replay. Separate post-commit GET handling from the POST catch. If refreshing context fails, retain the new route and session, show metadata error and retry only GET. Ignore stale replies. Do not send an agent message on rebuild. The next explicit message sends only new sessionId and message.
6. Reload: persist only the committed route ID in tab-scoped sessionStorage on route activation (including ordinary manual and chat routes). Clear it when there is deliberately no active route. On startup GET route and context by this ID; render valid route geometry even if context fails, enable editing once both match. Guard against late restore after a newer action. Do not clear the saved ID just because initial React state is null. Keep draft and chat history in memory. Warn before unloading a dirty draft when feasible.

## 4. Connect the existing screens and media

- Sidebar/ManualPanel: make “Edit route” reachable for any active saved route from either entry mode. Keep fresh manual creation working. An editor panel shows Start, ordered visit rows, Finish, Swap endpoints, Cancel and Rebuild route. Use labelled buttons for moving a single occurrence up/down and removing it, with boundary controls disabled. Support raw map picks and explicit selection from available saved places for either endpoint. No geocoding or new map library.
- App.tsx and MapView.tsx: route edit picks go to the draft callback, not the existing manual start/end state. Render the committed geometry, metrics and committed visit list throughout editing. Prior to editing, legacy chat display can use current routeEndpoints/routeVisits. For a rebuilt/restored route use verified editing inputs. A null endpoint binding gives a role and coordinates. Keep both A/B roles on a round trip. A/B markers must not disappear when stops are empty.
- src/lib/places.ts, AlongTheWay and App: derive marker/card/strip inputs from the same committed data. Keep ordered occurrences in the strip; only the media fetch list is unique by UUID. Reuse the single usePlaceMedia instance, its selected-place priority and two-request limit. Unbound endpoints request no photo. On route change close a stale pinned/preview card and viewer, including pending hover timers. A media error cannot cause route/chat resubmission.
- ChatPanel: show previous messages as historical and “Manual edits are not sent to the assistant. A new message starts a new plan.” Failed edits and Cancel preserve the current conversation.

## 5. Make mocks exercise the real contract

Update src/api/mock.ts and mockStore.ts for both manual and chat-created routes. Capture original inputs when building the route, using a per-route context registry and fresh UUID for each success. Return independent snapshots. Preserve old records. Fix createRoute's map/filter that silently drops unknown places. Missing references yield 422 unknown_place, bound coordinate mismatch yields 400 invalid_request. Keep visits even when a stop equals an endpoint. A chat-created route supplies no bindings. Use synthetic contract fixtures for deterministic tests; never call Wikimedia, ORS or an agent for the new editor fixtures. Current data/tatras.ts uses demo-* place IDs: if migrating these to deterministic fixture UUIDs, update every mock photo lookup and its tests together so mock photo demos keep working. Keep real UUID validation strict. The mock registry is in memory: use a seeded fixture for a reload demo or report its limitation; verify arbitrary saved-route reload against the real API. Never persist drafts or full routes in client storage to simulate backend persistence.

## 6. Verification and handoff to Murat

Use existing Vitest conventions. Add focused tests for the pure helpers, request validation and orchestration with deferred promises and call counters. Test actual production transitions/handlers, including two synchronous submits, instead of reimplementing them in tests. Use fixture groups legacyRead, boundRead, rebuildReordered, repeatedVisits, roundTrip, directRoute, coordinateMismatch, unknownEndpoint and frontendTransitions.

- X,Y,X: move the last X and separately remove it; check occurrence keys and exact outbound arrays. Clear an endpoint binding at the same coords and assert dirty; restore binding and assert clean. Check original preferences, exact endpoint precision, empty stops and equal A/B.
- Cancel and failed rebuild preserve original ID/session/track/photos. Late context GET after route change has no effect. Malformed 2xx/lost POST yields uncertain state and exactly one POST. A valid 201 plus failed metadata GET commits once and rotates chat once. GET-only retry and a media retry leave POST counters unchanged. Assert next chat payload uses the new session only.
- Verify route restoration reads both endpoints, drops dirty draft and issues zero POSTs. Check ordinary manual build, chat-origin routes with null bindings, existing mock media and empty/error galleries for regressions.
- From frontend run npm test, npm run lint and npm run build. Report commands and results, changed files, outstanding integration checks and how Murat can reproduce one success and one failure. For a real backend run use the same reviewed revision pair: build a route with multiple stops, edit order/endpoints, rebuild, reload, and GET both IDs. Manual flow must run with the agent stopped. Separately check the chat transition with the agent running. Mark live checks pending if the Java endpoint is unavailable; do not report mock results as live E2E.
- Keep the real editor disabled until the matching API is available (a frontend environment flag defaulting off in real mode is sufficient; document its name). The mock editor may run immediately. Do not drop binding fields and replay against an older backend. Keep CI, release tags and shared services unchanged.
