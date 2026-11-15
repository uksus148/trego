import { describe, expect, it } from 'vitest'
import { ApiContractError, parseChatResponse, parseCreatedRoute, parsePlace, parseRoute } from './apiContract'
import type { Place, Route, RouteRequest } from '../types'

const a = '00000000-0000-4000-8000-000000000001'
const b = '00000000-0000-4000-8000-000000000002'
const place = (id: string): Place => ({ id, name: id, lat: 49, lon: 20, tags: [], photos: [], source: 'manual' })
const route = (places: Place[] = []): Route => ({
  id: '00000000-0000-4000-8000-000000000099',
  geojson: { type: 'LineString', coordinates: [[20, 49], [20.1, 49.1]] },
  distanceKm: 12.3,
  ascentM: 200,
  durationMin: 240,
  places,
  segments: [],
})

describe('baseline response validation', () => {
  it('accepts complete chat, place and route responses', () => {
    expect(parseChatResponse({ reply: 'Ready', places: [place(a)], routeId: route().id }).places[0].id).toBe(a)
    expect(parsePlace(place(a)).id).toBe(a)
    expect(parseRoute(route([place(b)])).places[0].id).toBe(b)
  })

  it('rejects malformed chat and place data instead of passing partial objects into React', () => {
    expect(() => parseChatResponse({ reply: 'Ready', places: {} })).toThrow(ApiContractError)
    expect(() => parseChatResponse({ reply: 'Ready', places: [{ id: a }] })).toThrow(ApiContractError)
    expect(() => parsePlace({ ...place(a), lat: Infinity })).toThrow(ApiContractError)
    expect(() => parsePlace({ ...place(a), lon: 181 })).toThrow(ApiContractError)
  })

  it.each([
    ['missing structure', { id: route().id }],
    ['wrong identity', { ...route(), id: '00000000-0000-4000-8000-000000000098' }],
    ['invalid geometry', { ...route(), geojson: { type: 'LineString', coordinates: [[20, 49], [181, 49]] } }],
    ['invalid metrics', { ...route(), distanceKm: Number.NaN }],
    ['invalid stop', { ...route(), places: [{ id: a }] }],
    ['invalid segment', { ...route(), segments: [{ fromKm: 0, toKm: 20, photos: [] }] }],
  ])('rejects a route with %s', (_label, value) => {
    expect(() => parseRoute(value, route().id)).toThrow(ApiContractError)
  })

  it('checks exact stop order and keeps repeated visits', () => {
    const request: RouteRequest = { start: { lat: 49, lon: 20 }, end: { lat: 49.2, lon: 20.2 }, placeIds: [b, a, b], preferences: [] }
    const saved = route([place(b), place(a), place(b)])
    expect(parseCreatedRoute(saved, request).places.map((item) => item.id)).toEqual([b, a, b])
    expect(() => parseCreatedRoute(route([place(a), place(b), place(b)]), request)).toThrow(ApiContractError)
  })
})
