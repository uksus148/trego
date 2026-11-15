import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, realApi, UncertainRouteSaveError } from './realApi'
import { ApiContractError } from '../lib/apiContract'

const ROUTE_ID = '00000000-0000-4000-8000-000000000099'
const validRoute = { id: ROUTE_ID, geojson: { type: 'LineString', coordinates: [[20, 49], [20.1, 49.1]] }, distanceKm: 12.3, ascentM: 200, durationMin: 240, places: [], segments: [] }

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const sentHeaders = (fetchMock: ReturnType<typeof stubFetch>) => new Headers(fetchMock.mock.calls[0][1]?.headers)

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('realApi', () => {
  it('sends GET requests without a Content-Type so browsers skip the CORS preflight', async () => {
    const fetchMock = stubFetch(validRoute)

    await realApi.getRoute(ROUTE_ID)

    expect(fetchMock.mock.calls[0][1]?.method ?? 'GET').toBe('GET')
    expect(sentHeaders(fetchMock).has('Content-Type')).toBe(false)
  })

  it('sends POST bodies as JSON', async () => {
    const fetchMock = stubFetch({ reply: 'ok', places: [] })

    await realApi.chat({ sessionId: 's', message: 'hi' })

    const init = fetchMock.mock.calls[0][1]
    expect(init?.method).toBe('POST')
    expect(sentHeaders(fetchMock).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(String(init?.body))).toEqual({ sessionId: 's', message: 'hi' })
  })

  it('validates a successful route GET and requires the requested route identity', async () => {
    stubFetch(validRoute)
    await expect(realApi.getRoute(ROUTE_ID)).resolves.toMatchObject({ id: ROUTE_ID, distanceKm: 12.3 })

    stubFetch({ ...validRoute, geojson: undefined })
    await expect(realApi.getRoute(ROUTE_ID)).rejects.toBeInstanceOf(ApiContractError)
    stubFetch({ ...validRoute, id: '00000000-0000-4000-8000-000000000098' })
    await expect(realApi.getRoute(ROUTE_ID)).rejects.toBeInstanceOf(ApiContractError)
  })

  it('turns malformed successful chat and place responses into contract errors', async () => {
    stubFetch({ reply: 'Ready', places: null })
    await expect(realApi.chat({ sessionId: 's', message: 'hi' })).rejects.toBeInstanceOf(ApiContractError)

    stubFetch({ id: 'not-a-uuid', name: 'Skok', lat: 49, lon: 20, tags: [], photos: [], source: 'manual' }, 201)
    await expect(realApi.addPlace({ name: 'Skok', lat: 49, lon: 20, tags: [] })).rejects.toBeInstanceOf(ApiContractError)
  })

  it('requires a created route to preserve every requested stop occurrence and does not retry', async () => {
    const id = '00000000-0000-4000-8000-000000000021'
    const stop = { id, name: 'Skok', lat: 49, lon: 20, tags: ['waterfall'], photos: [], source: 'https://example.org/skok' }
    const request = { start: { lat: 49, lon: 20 }, end: { lat: 49.2, lon: 20.2 }, placeIds: [id, id], preferences: [] }
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ ...validRoute, places: [stop, stop] }), { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)

    await realApi.createRoute(request)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    const mismatched = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ ...validRoute, places: [stop] }), { status: 201 }))
    vi.stubGlobal('fetch', mismatched)
    await expect(realApi.createRoute(request)).rejects.toBeInstanceOf(UncertainRouteSaveError)
    expect(mismatched).toHaveBeenCalledTimes(1)
  })

  it('rejects malformed JSON on a successful response as a recoverable contract error', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => new Response('{broken', { status: 200 })))
    await expect(realApi.getRoute(ROUTE_ID)).rejects.toBeInstanceOf(ApiContractError)
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

    const error = await realApi.createRoute({ start: { lat: 49, lon: 20 }, end: { lat: 49.2, lon: 20.2 }, placeIds: [], preferences: [] }).catch((e: unknown) => e)

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
