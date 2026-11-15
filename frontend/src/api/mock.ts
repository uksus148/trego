import { DEMO_ASCENT_M, DEMO_END, DEMO_PLACES, DEMO_START, DEMO_START_PLACE } from '../data/tatras'
import type { ApiClient, Place } from '../types'
import { mockPlaceMedia } from './mockMedia'
import { buildRoute, delay, getPlace, getRoute, MOCK_LATENCY_MS, registerPlace } from './mockStore'

// In-browser stand-in for api + agent so the frontend works before the backends exist.

// "Find …" / "Where is …" exercise the contract case where chat returns places without a route.
const FIND_ONLY_REQUEST = /^\s*(?:find|where|locate|show me)\b/i

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
    // Like the agreed handoff: the route lists only intermediate stops; chat returns start, stops and finish.
    const startPlace = registerPlace({ ...DEMO_START_PLACE, photos: [] })
    const route = await buildRoute(DEMO_START, DEMO_END, places.slice(0, -1), DEMO_ASCENT_M)
    return {
      reply:
        'Here is a route from Štrbské Pleso past Skok waterfall to Popradské pleso. ' +
        'Hover or tap a marker to see the place and its photo. (Demo data: the AI agent is not connected yet.)',
      places: [startPlace, ...places],
      routeId: route.id,
    }
  },

  async addPlace(newPlace) {
    await delay(MOCK_LATENCY_MS)
    const place: Place = { ...newPlace, id: crypto.randomUUID(), source: 'manual', photos: [] }
    return registerPlace(place)
  },

  async createRoute(request) {
    await delay(MOCK_LATENCY_MS)
    const places = request.placeIds.map(getPlace).filter((place): place is Place => place !== undefined)
    return buildRoute(request.start, request.end, places, 0)
  },

  async getRoute(id) {
    return getRoute(id)
  },

  async getPlaceMedia(placeId) {
    await delay(MOCK_LATENCY_MS)
    return mockPlaceMedia(placeId, getPlace(placeId) !== undefined)
  },
}
