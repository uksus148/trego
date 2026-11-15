import { DEMO_ASCENT_M, DEMO_END, DEMO_PLACES, DEMO_START, DEMO_START_PLACE } from '../data/tatras'
import { boundEndpoint } from '../lib/routeEditing'
import type { ApiClient, Place, RouteRequest } from '../types'
import { ApiError } from './realApi'
import { mockPlaceMedia } from './mockMedia'
import {
  buildRoute, delay, getEditingContext, getPlace, getRoute, MOCK_LATENCY_MS, registerPlace, saveEditingContext,
} from './mockStore'

const FIND_ONLY_REQUEST = /^\s*(?:find|where|locate|show me)\b/i

function resolvePlaces(request: RouteRequest): Place[] {
  const places = request.placeIds.map((id) => getPlace(id))
  if (places.some((place) => !place)) throw new ApiError('A referenced place does not exist.', 422, 'unknown_place')
  return places as Place[]
}
function endpoint(request: RouteRequest, side: 'start' | 'end') {
  const point = request[side]
  const id = request[side === 'start' ? 'startPlaceId' : 'endPlaceId']
  if (id == null) return { ...point, place: null }
  const place = getPlace(id)
  if (!place) throw new ApiError('A referenced place does not exist.', 422, 'unknown_place')
  if (point.lat !== place.lat || point.lon !== place.lon) throw new ApiError('Endpoint coordinates must match the referenced place.', 400, 'invalid_request')
  return boundEndpoint(place)
}

export const mockApi: ApiClient = {
  async chat(request) {
    await delay(MOCK_LATENCY_MS)
    const places = DEMO_PLACES.map((place) => registerPlace({ ...place, photos: [] }))
    if (FIND_ONLY_REQUEST.test(request.message)) {
      return {
        reply: `Found ${places.length} places. Set a start and a finish in "Plan on map" to build a route through them. (Demo data.)`,
        places,
      }
    }
    const startPlace = registerPlace({ ...DEMO_START_PLACE, photos: [] })
    const start = { lat: DEMO_START.lat, lon: DEMO_START.lon, place: null }
    const end = { ...DEMO_END, place: null }
    const stops = places.slice(0, -1)
    const route = await buildRoute(start, end, stops, DEMO_ASCENT_M)
    saveEditingContext(route.id, { start, end, stops, preferences: [] })
    return {
      reply: 'Here is a route from Štrbské Pleso past Skok waterfall to Popradské pleso. ' +
        'Hover or tap a marker to see the place and its photo. (Demo data: the AI agent is not connected yet.)',
      places: [startPlace, ...places],
      routeId: route.id,
    }
  },
  async addPlace(newPlace) {
    await delay(MOCK_LATENCY_MS)
    return registerPlace({ ...newPlace, id: crypto.randomUUID(), source: 'manual', photos: [] })
  },
  async createRoute(request) {
    await delay(MOCK_LATENCY_MS)
    if (request.placeIds.length > 5) throw new ApiError('At most five intermediate places are supported.', 400, 'invalid_request')
    const places = resolvePlaces(request)
    const start = endpoint(request, 'start')
    const end = endpoint(request, 'end')
    const route = await buildRoute(request.start, request.end, places, 0)
    saveEditingContext(route.id, { start, end, stops: places, preferences: [...request.preferences] })
    return route
  },
  async getRoute(id) {
    await delay(MOCK_LATENCY_MS)
    return getRoute(id)
  },
  async getRouteEditingContext(routeId) {
    await delay(MOCK_LATENCY_MS)
    return getEditingContext(routeId)
  },
  async getPlaceMedia(placeId) {
    await delay(MOCK_LATENCY_MS)
    return mockPlaceMedia(placeId, getPlace(placeId) !== undefined)
  },
}
