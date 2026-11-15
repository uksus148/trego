import { describe, expect, it, vi, afterEach } from 'vitest'
import corpus from '../../../docs/contracts/baseline.examples.json'
import { realApi } from './realApi'
import type { Route } from '../types'

afterEach(() => vi.unstubAllGlobals())

describe('shared accepted baseline examples', () => {
  it('retains the TypeScript route shape, repeated order and exact sources through the HTTP consumer', async () => {
    expect(corpus.route.geojson.type).toBe('LineString')
    const route: Route = { ...corpus.route, geojson: { type: 'LineString',
      coordinates: corpus.route.geojson.coordinates.map(point => {
        expect(point).toHaveLength(2)
        return [point[0], point[1]]
      }),
    } }
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(route)))
    vi.stubGlobal('fetch', fetch)
    const saved = await realApi.getRoute(route.id)
    expect(saved).toEqual(route)
    expect(saved.places.map(p => p.id)).toEqual(corpus.stopIndexes.map(i => corpus.places[i].id))
    expect(saved.geojson.coordinates[0]).toEqual([20, 49])
    expect(saved.places[0].source).toBe('https://evidence.example/falls')
    expect(fetch).toHaveBeenCalledOnce()
  })
})
