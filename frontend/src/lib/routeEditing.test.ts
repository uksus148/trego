import { describe, expect, it } from 'vitest'
import type { Place, Route, RouteEditingContext } from '../types'
import {
  boundEndpoint, canOpenRouteEditor, fromContext, isDirty, isValidDraft, moveVisit, parseEditingContext,
  parseRoute, rawEndpoint, removeVisit, swapEndpoints, toRequest,
} from './routeEditing'

const ids = {
  route: '10000000-0000-4000-8000-000000000001',
  rebuilt: '10000000-0000-4000-8000-000000000002',
  start: '00000000-0000-4000-8000-000000000001',
  x: '00000000-0000-4000-8000-000000000002',
  y: '00000000-0000-4000-8000-000000000003',
  end: '00000000-0000-4000-8000-000000000004',
}
const place = (id: string, name: string, lat: number, lon: number): Place => ({
  id, name, lat, lon, tags: ['other'], photos: [], source: 'https://example.org/fixture',
})
const startPlace = place(ids.start, 'Fixture start', 49.100001, 20.100002)
const x = place(ids.x, 'Fixture X', 49.11, 20.11)
const y = place(ids.y, 'Fixture Y', 49.12, 20.12)
const endPlace = place(ids.end, 'Fixture finish', 49.13, 20.13)
const context: RouteEditingContext = {
  routeId: ids.route,
  start: { lat: startPlace.lat, lon: startPlace.lon, place: startPlace },
  end: { lat: endPlace.lat, lon: endPlace.lon, place: endPlace },
  stops: [x, y, x],
  preferences: ['quiet scenery', 'wild scenery'],
}
const route: Route = {
  id: ids.rebuilt,
  geojson: { type: 'LineString', coordinates: [[20.1, 49.1], [20.11, 49.11], [20.12, 49.12], [20.13, 49.13]] },
  distanceKm: 8.4, ascentM: 120, durationMin: 150, places: [x, y, x], segments: [],
}

describe('route editor entry guard', () => {
  const base = { enabled: true, status: 'closed' as const, requestPending: false, tripBusy: false, activeRouteId: ids.route }

  it('opens only for an idle, closed editor with an active route', () => {
    expect(canOpenRouteEditor(base)).toBe(true)
    expect(canOpenRouteEditor({ ...base, status: 'ready' })).toBe(false)
    expect(canOpenRouteEditor({ ...base, status: 'loading' })).toBe(false)
    expect(canOpenRouteEditor({ ...base, requestPending: true })).toBe(false)
    expect(canOpenRouteEditor({ ...base, tripBusy: true })).toBe(false)
    expect(canOpenRouteEditor({ ...base, activeRouteId: null })).toBe(false)
  })
})

describe('route editing context validation', () => {
  it('keeps bound endpoints, source photos, preferences and stop order', () => {
    expect(parseEditingContext(context, ids.route)).toEqual(context)
  })

  it('rejects mismatched endpoint coordinates, wrong route IDs, and more than five stops', () => {
    expect(() => parseEditingContext({ ...context, start: { ...context.start, lat: 49.2 } }, ids.route)).toThrow(/coordinates/)
    expect(() => parseEditingContext(context, ids.rebuilt)).toThrow(/invalid/)
    expect(() => parseEditingContext({ ...context, stops: [x, x, x, x, x, x] }, ids.route)).toThrow(/invalid/)
  })
})

describe('route draft helpers', () => {
  it('moves and removes one X occurrence without collapsing X → Y → X', () => {
    const draft = fromContext(context)
    const keys = draft.rows.map((row) => row.key)
    const moved = moveVisit(draft, keys[2], -1)
    expect(moved.rows.map((row) => row.place.id)).toEqual([ids.x, ids.x, ids.y])
    expect(moved.rows.map((row) => row.key)).toEqual([keys[0], keys[2], keys[1]])

    const removed = removeVisit(draft, keys[2])
    expect(removed.rows.map((row) => row.place.id)).toEqual([ids.x, ids.y])
    expect(removed.rows.map((row) => row.key)).toEqual([keys[0], keys[1]])
  })

  it('keeps exact coordinates and treats clearing/restoring a binding at the same point as dirty/clean', () => {
    const initial = fromContext({ ...context, stops: [] })
    const raw = { ...initial, start: rawEndpoint(initial.start) }
    expect(raw.start).toEqual({ lat: 49.100001, lon: 20.100002, place: null })
    expect(isDirty(initial, raw)).toBe(true)
    const rebound = { ...raw, start: boundEndpoint(startPlace) }
    expect(isDirty(initial, rebound)).toBe(false)
    expect(toRequest(rebound).start).toEqual({ lat: 49.100001, lon: 20.100002 })
  })

  it('swaps complete endpoint objects, accepts direct routes and preserves preferences', () => {
    const draft = fromContext({ ...context, stops: [] })
    const swapped = swapEndpoints(draft)
    expect(swapped.start.place?.id).toBe(ids.end)
    expect(swapped.end.place?.id).toBe(ids.start)
    expect(swapped.rows).toEqual([])
    expect(toRequest(draft).placeIds).toEqual([])
    expect(toRequest(draft).preferences).toEqual(context.preferences)
    expect(isValidDraft(draft)).toBe(true)
  })
})

describe('route response validation', () => {
  it('accepts a new route with repeated submitted stops in exact order', () => {
    const request = toRequest(fromContext(context))
    expect(parseRoute(route, request, ids.route)).toEqual(route)
  })

  it('rejects reordering, reuse of the source ID and malformed geometry', () => {
    const request = toRequest(fromContext(context))
    expect(() => parseRoute({ ...route, places: [y, x, x] }, request, ids.route)).toThrow(/order/)
    expect(() => parseRoute({ ...route, id: ids.route }, request, ids.route)).toThrow(/invalid/)
    expect(() => parseRoute({ ...route, geojson: { type: 'LineString', coordinates: [[20, 49], [181, 49]] } })).toThrow(/invalid/)
  })
})
