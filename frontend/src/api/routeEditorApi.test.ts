import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Route, RouteEditingContext } from '../types'
import { ApiError, realApi, UncertainRouteSaveError } from './realApi'

const ROUTE_ID = '10000000-0000-4000-8000-000000000001'
const NEXT_ROUTE_ID = '10000000-0000-4000-8000-000000000002'
const request = { start: { lat: 49.1, lon: 20.1 }, end: { lat: 49.2, lon: 20.2 }, placeIds: [], preferences: [] }
const route: Route = {
  id: ROUTE_ID,
  geojson: { type: 'LineString', coordinates: [[20.1, 49.1], [20.2, 49.2]] },
  distanceKm: 1, ascentM: 10, durationMin: 15, places: [], segments: [],
}
const context: RouteEditingContext = {
  routeId: ROUTE_ID,
  start: { lat: 49.1, lon: 20.1, place: null },
  end: { lat: 49.2, lon: 20.2, place: null },
  stops: [], preferences: ['quiet scenery'],
}
function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
const sentHeaders = (fetchMock: ReturnType<typeof stubFetch>) => new Headers(fetchMock.mock.calls[0][1]?.headers)
afterEach(() => vi.unstubAllGlobals())

describe('realApi route editor boundary', () => {
  it('fetches and validates editing context using the API base URL without query parameters', async () => {
    const fetchMock = stubFetch(context)
    await expect(realApi.getRouteEditingContext(ROUTE_ID)).resolves.toEqual(context)
    expect(String(fetchMock.mock.calls[0][0])).toMatch(new RegExp(`/api/routes/${ROUTE_ID}/editing-context$`))
    expect(fetchMock.mock.calls[0][1]?.method ?? 'GET').toBe('GET')
    expect(sentHeaders(fetchMock).has('Content-Type')).toBe(false)
  })

  it('rejects a malformed route ID before making a request', async () => {
    const fetchMock = stubFetch(context)
    await expect(realApi.getRouteEditingContext('not-a-uuid')).rejects.toMatchObject({ status: 400, code: 'invalid_request' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('accepts a confirmed 201 once and validates the new route against the request', async () => {
    const request = { start: { lat: 49.1, lon: 20.1 }, end: { lat: 49.2, lon: 20.2 }, placeIds: [], preferences: [], startPlaceId: null, endPlaceId: null }
    const fetchMock = stubFetch({ ...route, id: NEXT_ROUTE_ID }, 201)
    await expect(realApi.createRoute(request, ROUTE_ID)).resolves.toMatchObject({ id: NEXT_ROUTE_ID })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual(request)
  })

  it('treats an unexpected success status as uncertain and never retries', async () => {
    const request = { start: { lat: 49.1, lon: 20.1 }, end: { lat: 49.2, lon: 20.2 }, placeIds: [], preferences: [] }
    const fetchMock = stubFetch({ ...route, id: NEXT_ROUTE_ID }, 200)
    await expect(realApi.createRoute(request, ROUTE_ID)).rejects.toBeInstanceOf(UncertainRouteSaveError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('treats an unreadable 201 body and a lost response as uncertain without retry', async () => {
    const request = { start: { lat: 49.1, lon: 20.1 }, end: { lat: 49.2, lon: 20.2 }, placeIds: [], preferences: [] }
    const badBodyFetch = vi.fn<typeof fetch>(async () => new Response('not json', { status: 201 }))
    vi.stubGlobal('fetch', badBodyFetch)
    await expect(realApi.createRoute(request, ROUTE_ID)).rejects.toBeInstanceOf(UncertainRouteSaveError)
    expect(badBodyFetch).toHaveBeenCalledTimes(1)

    const lostFetch = vi.fn<typeof fetch>(async () => { throw new TypeError('network lost') })
    vi.stubGlobal('fetch', lostFetch)
    await expect(realApi.createRoute(request, ROUTE_ID)).rejects.toBeInstanceOf(UncertainRouteSaveError)
    expect(lostFetch).toHaveBeenCalledTimes(1)
  })

  it.each([502, 504])('treats an HTML gateway %i as an uncertain save without retry', async (status) => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response('<html>Gateway failure</html>', { status, headers: { 'Content-Type': 'text/html' } }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(realApi.createRoute(request, ROUTE_ID)).rejects.toBeInstanceOf(UncertainRouteSaveError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each([
    [502, 'routing_provider_error'],
    [503, 'cache_unavailable'],
    [503, 'storage_unavailable'],
    [504, 'routing_timeout'],
  ])('preserves a confirmed API failure %i %s without retry', async (status, code) => {
    const detail = 'The requested route could not be produced.'
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(
      JSON.stringify({ status, code, type: 'about:blank', title: 'Route failed', detail }),
      { status, headers: { 'Content-Type': 'application/problem+json; charset=utf-8' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    const error = await realApi.createRoute(request, ROUTE_ID).catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status, code, message: detail })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not trust a Problem Details code that contradicts the HTTP status', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(
      JSON.stringify({ status: 504, code: 'routing_provider_error', type: 'about:blank', title: 'Failure', detail: 'Gateway failure' }),
      { status: 504, headers: { 'Content-Type': 'application/problem+json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(realApi.createRoute(request, ROUTE_ID)).rejects.toBeInstanceOf(UncertainRouteSaveError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
