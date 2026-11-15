import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Route, RouteEditingContext } from '../types'
import { ApiError, realApi, UncertainRouteSaveError } from './realApi'

const ROUTE_ID = '10000000-0000-4000-8000-000000000001'
const NEXT_ROUTE_ID = '10000000-0000-4000-8000-000000000002'
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
})

describe('realApi', () => {
  it('sends GET requests without a Content-Type header', async () => {
    const fetchMock = stubFetch(route)
    await realApi.getRoute(ROUTE_ID)
    expect(fetchMock.mock.calls[0][1]?.method ?? 'GET').toBe('GET')
    expect(sentHeaders(fetchMock).has('Content-Type')).toBe(false)
  })

  it('sends chat POST bodies as JSON', async () => {
    const fetchMock = stubFetch({ reply: 'ok', places: [] })
    await realApi.chat({ sessionId: 's', message: 'hi' })
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST')
    expect(sentHeaders(fetchMock).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ sessionId: 's', message: 'hi' })
  })
})

describe('realApi errors', () => {
  function stubFailure(status: number, body: string, contentType = 'application/json') {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => new Response(body, { status, headers: { 'Content-Type': contentType } })))
  }
  it('shows the API Problem Details detail and keeps its code', async () => {
    stubFailure(422, JSON.stringify({ type: 'about:blank', title: 'No hiking route', status: 422, detail: 'No walking route connects the requested waypoints.', code: 'no_hiking_route' }), 'application/problem+json')
    const error = await realApi.getRoute(ROUTE_ID).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ message: 'No walking route connects the requested waypoints.', status: 422, code: 'no_hiking_route' })
  })
  it("shows the agent's FastAPI detail", async () => {
    stubFailure(503, JSON.stringify({ detail: 'Chat session storage is temporarily unavailable.' }))
    await expect(realApi.chat({ sessionId: 's', message: 'hi' })).rejects.toThrow('Chat session storage is temporarily unavailable.')
  })
  it('preserves a waypoint matching failure separately from a disconnected route', async () => {
    const detail = "One or more waypoints could not be matched to the available hiking network within the provider's search radius."
    stubFailure(422, JSON.stringify({ type: 'about:blank', title: 'Unprocessable Entity', status: 422, detail, code: 'waypoint_not_routable' }), 'application/problem+json')
    const request = { start: { lat: 49, lon: 20 }, end: { lat: 49.2, lon: 20.2 }, placeIds: [], preferences: [] }
    const error = await realApi.createRoute(request).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ message: detail, status: 422, code: 'waypoint_not_routable' })
  })
  it('joins FastAPI validation messages', async () => {
    stubFailure(422, JSON.stringify({ detail: [{ loc: ['body', 'message'], msg: 'String should have at least 1 character', type: 'string_too_short' }] }))
    await expect(realApi.chat({ sessionId: 's', message: '' })).rejects.toThrow('String should have at least 1 character')
  })
  it('does not show raw HTML from a proxy error page', async () => {
    stubFailure(502, '<html><body>Bad Gateway</body></html>', 'text/html')
    await expect(realApi.getRoute(ROUTE_ID)).rejects.toThrow('Request failed (502). Please try again.')
  })
  it('fetches place media without query parameters and validates the response', async () => {
    const placeId = '00000000-0000-4000-8000-000000000002'
    const fetchMock = stubFetch({ placeId, status: 'empty', fetchedAt: null, placeDescription: null, photos: [] })
    const media = await realApi.getPlaceMedia(placeId)
    expect(String(fetchMock.mock.calls[0][0])).toMatch(new RegExp(`/api/places/${placeId}/media$`))
    expect(media.status).toBe('empty')
  })
  it('rejects place media for a different place', async () => {
    stubFetch({ placeId: 'other', status: 'empty', fetchedAt: null, placeDescription: null, photos: [] })
    await expect(realApi.getPlaceMedia('requested')).rejects.toThrow('placeId does not match')
  })
})
