import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const runtime = vi.hoisted(() => ({ slots: [] as unknown[], cursor: 0, cleanup: null as null | (() => void) }))
const apiMock = vi.hoisted(() => ({
  chat: vi.fn(), addPlace: vi.fn(), createRoute: vi.fn(), getRoute: vi.fn(),
  getRouteEditingContext: vi.fn(), getPlaceMedia: vi.fn(),
}))

vi.mock('react', () => ({
  useState: (initial: unknown) => {
    const index = runtime.cursor++
    if (!(index in runtime.slots)) runtime.slots[index] = typeof initial === 'function' ? (initial as () => unknown)() : initial
    return [runtime.slots[index], (next: unknown) => {
      runtime.slots[index] = typeof next === 'function'
        ? (next as (previous: unknown) => unknown)(runtime.slots[index])
        : next
    }]
  },
  useRef: (initial: unknown) => {
    const index = runtime.cursor++
    if (!(index in runtime.slots)) runtime.slots[index] = { current: initial }
    return runtime.slots[index]
  },
  useEffect: (effect: () => void | (() => void)) => {
    const index = runtime.cursor++
    if (!(index in runtime.slots)) {
      runtime.slots[index] = true
      runtime.cleanup = effect() ?? null
    }
  },
}))
vi.mock('../api/client', () => ({ api: apiMock, USE_MOCKS: true }))

import { useTrip } from './useTrip'
import { ApiError, UncertainRouteSaveError } from '../api/realApi'
import type { Place, Route, RouteEditingContext } from '../types'

const ids = {
  route: '10000000-0000-4000-8000-000000000001',
  rebuilt: '10000000-0000-4000-8000-000000000002',
  start: '00000000-0000-4000-8000-000000000001',
  stop: '00000000-0000-4000-8000-000000000002',
  secondStop: '00000000-0000-4000-8000-000000000003',
  end: '00000000-0000-4000-8000-000000000004',
}
const makePlace = (id: string, name: string, lat: number, lon: number): Place => ({
  id, name, lat, lon, tags: ['other'], photos: [], source: 'https://example.org/fixture',
})
const startPlace = makePlace(ids.start, 'Fixture start', 49.1, 20.1)
const stop = makePlace(ids.stop, 'Fixture stop', 49.11, 20.11)
const secondStop = makePlace(ids.secondStop, 'Second fixture stop', 49.12, 20.12)
const endPlace = makePlace(ids.end, 'Fixture finish', 49.13, 20.13)
const route = (id: string, places: Place[]): Route => ({
  id, geojson: { type: 'LineString', coordinates: [[20.1, 49.1], [20.13, 49.13]] },
  distanceKm: 8, ascentM: 100, durationMin: 120, places, segments: [],
})
const sourceRoute = route(ids.route, [stop, secondStop])
const rebuiltRoute = route(ids.rebuilt, [stop])
const context = (routeId: string, stops: Place[] = [stop, secondStop]): RouteEditingContext => ({
  routeId, start: { lat: startPlace.lat, lon: startPlace.lon, place: startPlace },
  end: { lat: endPlace.lat, lon: endPlace.lon, place: endPlace }, stops,
  preferences: ['quiet scenery'],
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
async function flushPromises() {
  for (let i = 0; i < 6; i++) await Promise.resolve()
}
function renderTrip() {
  // oxlint-disable-next-line react/immutability
  runtime.cursor = 0
  // oxlint-disable-next-line react-hooks/rules-of-hooks
  return useTrip()
}
async function startChatRoute() {
  apiMock.chat.mockResolvedValue({ reply: 'Original plan', places: [startPlace, stop, secondStop, endPlace], routeId: ids.route })
  apiMock.getRoute.mockResolvedValue(sourceRoute)
  apiMock.getRouteEditingContext.mockImplementation(async (routeId: string) =>
    context(routeId, routeId === ids.rebuilt ? [stop] : [stop, secondStop]))
  let trip = renderTrip()
  await trip.sendMessage('Make a plan')
  trip = renderTrip()
  await trip.openEditor()
  return renderTrip()
}

beforeEach(() => {
  runtime.slots = []
  runtime.cursor = 0
  runtime.cleanup = null
  vi.resetAllMocks()
  const values = new Map<string, string>()
  vi.stubGlobal('window', {
    sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
    confirm: vi.fn(() => true),
  })
})
afterEach(() => {
  runtime.cleanup?.()
  vi.unstubAllGlobals()
})

describe('useTrip route editing lifecycle', () => {
  it('does not reload context over an open dirty draft', async () => {
    let trip = await startChatRoute()
    expect(trip.editor.status).toBe('ready')
    if (trip.editor.status !== 'ready') throw new Error('Expected editor to be ready')
    trip.removeEditorVisit(trip.editor.draft.rows[1].key)
    trip = renderTrip()
    await trip.openEditor()
    trip = renderTrip()

    expect(apiMock.getRouteEditingContext).toHaveBeenCalledTimes(1)
    expect(trip.editor.status).toBe('ready')
    if (trip.editor.status === 'ready') expect(trip.editor.draft.rows.map((row) => row.place.id)).toEqual([ids.stop])
  })

  it('allows only one synchronous rebuild and rotates chat after the valid save', async () => {
    let trip = await startChatRoute()
    if (trip.editor.status !== 'ready') throw new Error('Expected editor to be ready')
    const sourceSessionId = trip.sessionId
    trip.removeEditorVisit(trip.editor.draft.rows[1].key)
    trip = renderTrip()
    const pending = deferred<Route>()
    apiMock.createRoute.mockReturnValue(pending.promise)

    const first = trip.rebuildRoute()
    const second = trip.rebuildRoute()
    expect(apiMock.createRoute).toHaveBeenCalledTimes(1)
    expect(apiMock.createRoute).toHaveBeenCalledWith(expect.objectContaining({ placeIds: [ids.stop] }), ids.route)
    pending.resolve(rebuiltRoute)
    await Promise.all([first, second])
    await flushPromises()
    trip = renderTrip()

    expect(trip.route?.id).toBe(ids.rebuilt)
    expect(trip.messages).toEqual([])
    expect(trip.history).toHaveLength(1)
    expect(trip.sessionId).not.toBe(sourceSessionId)
    expect(trip.editor.status).toBe('ready')
    expect(trip.metadataError).toBeNull()
    const freshSessionId = trip.sessionId
    apiMock.chat.mockResolvedValue({ reply: 'New plan', places: [] })
    await trip.sendMessage('Plan another walk')
    expect(apiMock.chat).toHaveBeenLastCalledWith({ sessionId: freshSessionId, message: 'Plan another walk' })
  })

  it('keeps the source route, chat session, and draft after a recognized route error', async () => {
    let trip = await startChatRoute()
    if (trip.editor.status !== 'ready') throw new Error('Expected editor to be ready')
    const sourceSession = trip.sessionId
    trip.removeEditorVisit(trip.editor.draft.rows[1].key)
    trip = renderTrip()
    apiMock.createRoute.mockRejectedValue(new ApiError('No hiking path.', 422, 'no_hiking_route'))

    await trip.rebuildRoute()
    trip = renderTrip()

    expect(trip.route?.id).toBe(ids.route)
    expect(trip.sessionId).toBe(sourceSession)
    expect(trip.editor.status).toBe('ready')
    if (trip.editor.status === 'ready') {
      expect(trip.editor.draft.rows.map((row) => row.place.id)).toEqual([ids.stop])
      expect(trip.editor.error).toContain('No verified walking path')
    }
  })

  it('requires confirmation before another submit after an uncertain POST', async () => {
    let trip = await startChatRoute()
    if (trip.editor.status !== 'ready') throw new Error('Expected editor to be ready')
    trip.removeEditorVisit(trip.editor.draft.rows[1].key)
    trip = renderTrip()
    apiMock.createRoute.mockRejectedValueOnce(new UncertainRouteSaveError())

    await trip.rebuildRoute()
    trip = renderTrip()
    expect(trip.editor.status).toBe('ready')
    if (trip.editor.status === 'ready') expect(trip.editor.uncertain).toBe(true)
    expect(apiMock.createRoute).toHaveBeenCalledTimes(1)

    const confirm = (window as Window & { confirm: (message: string) => boolean }).confirm as ReturnType<typeof vi.fn>
    confirm.mockReturnValueOnce(false)
    await trip.rebuildRoute()
    expect(apiMock.createRoute).toHaveBeenCalledTimes(1)

    confirm.mockReturnValueOnce(true)
    apiMock.createRoute.mockRejectedValueOnce(new ApiError('No hiking path.', 422, 'no_hiking_route'))
    await trip.rebuildRoute()
    expect(apiMock.createRoute).toHaveBeenCalledTimes(2)
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('keeps a successful route and new chat session if its context refresh fails', async () => {
    let trip = await startChatRoute()
    if (trip.editor.status !== 'ready') throw new Error('Expected editor to be ready')
    const sourceSessionId = trip.sessionId
    trip.removeEditorVisit(trip.editor.draft.rows[1].key)
    trip = renderTrip()
    apiMock.createRoute.mockResolvedValue(rebuiltRoute)
    apiMock.getRouteEditingContext.mockRejectedValueOnce(new Error('Metadata unavailable'))

    await trip.rebuildRoute()
    await flushPromises()
    trip = renderTrip()

    expect(apiMock.createRoute).toHaveBeenCalledTimes(1)
    expect(trip.route?.id).toBe(ids.rebuilt)
    expect(trip.sessionId).not.toBe(sourceSessionId)
    expect(trip.metadataError).toContain('Metadata unavailable')
  })

  it('restores route and context from the tab route ID without posting', async () => {
    const values = (window as Window & { sessionStorage: Storage }).sessionStorage
    values.setItem('trego.activeRouteId', ids.route)
    apiMock.getRoute.mockResolvedValue(sourceRoute)
    apiMock.getRouteEditingContext.mockResolvedValue(context(ids.route))

    let trip = renderTrip()
    await flushPromises()
    trip = renderTrip()

    expect(trip.route?.id).toBe(ids.route)
    expect(trip.committedContext?.routeId).toBe(ids.route)
    expect(apiMock.createRoute).not.toHaveBeenCalled()
  })

  it('ignores an old context response after a newer chat route replaces it', async () => {
    const lateContext = deferred<RouteEditingContext>()
    apiMock.chat
      .mockResolvedValueOnce({ reply: 'Original plan', places: [startPlace, stop, endPlace], routeId: ids.route })
      .mockResolvedValueOnce({ reply: 'Replacement plan', places: [startPlace, endPlace], routeId: ids.rebuilt })
    apiMock.getRoute.mockResolvedValueOnce(sourceRoute).mockResolvedValueOnce(rebuiltRoute)
    apiMock.getRouteEditingContext.mockReturnValue(lateContext.promise)
    let trip = renderTrip()
    await trip.sendMessage('First plan')
    trip = renderTrip()
    const opening = trip.openEditor()
    trip = renderTrip()
    expect(trip.editor.status).toBe('loading')
    await trip.sendMessage('Replace the plan')
    trip = renderTrip()
    lateContext.resolve(context(ids.route))
    await opening
    trip = renderTrip()

    expect(trip.route?.id).toBe(ids.rebuilt)
    expect(trip.editor.status).toBe('closed')
    expect(trip.committedContext).toBeNull()
  })
})


it('keeps a labelled previous route and suppresses a new ready reply when readback fails', async () => {
  let trip = await startChatRoute()
  apiMock.chat.mockResolvedValue({ reply: 'Unverified new ready answer', places: [startPlace, endPlace], routeId: ids.rebuilt })
  apiMock.getRoute.mockRejectedValue(new ApiError('Readback failed', 404, 'route_not_found'))
  await trip.sendMessage('A different plan')
  trip = renderTrip()
  expect(trip.route?.id).toBe(ids.route)
  expect(trip.showingPreviousRoute).toBe(true)
  expect(trip.messages.some(item => item.text === 'Unverified new ready answer')).toBe(false)
})
