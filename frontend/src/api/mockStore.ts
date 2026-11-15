import { haversineKm, round1, TRAIL_WINDING_FACTOR } from '../lib/geo'
import type { LatLon, Place, Route, RouteSegment } from '../types'

// Shared in-memory state for the mock backend.

export const MOCK_LATENCY_MS = 500
const WALK_KM_PER_HOUR = 4
const CLIMB_M_PER_HOUR = 600
const SAME_POINT_KM = 0.05

let placeRegistry: ReadonlyMap<string, Place> = new Map()
let routeRegistry: ReadonlyMap<string, Route> = new Map()

export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export function registerPlace(place: Place): Place {
  placeRegistry = new Map([...placeRegistry, [place.id, place]])
  return place
}

export const getPlace = (id: string) => placeRegistry.get(id)

export function getRoute(id: string): Route {
  const route = routeRegistry.get(id)
  if (!route) throw new Error(`Route ${id} not found`)
  return route
}

/** Straight lines between waypoints; real trail geometry comes from the api service. */
export async function buildRoute(start: LatLon, end: LatLon, places: Place[], ascentM: number): Promise<Route> {
  const lastPlace = places.at(-1)
  const endIsLastPlace = lastPlace !== undefined && haversineKm(lastPlace, end) < SAME_POINT_KM
  const waypoints: LatLon[] = [start, ...places, ...(endIsLastPlace ? [] : [end])]

  const legKm = waypoints.slice(1).map((point, i) => haversineKm(waypoints[i], point) * TRAIL_WINDING_FACTOR)
  const segments: RouteSegment[] = legKm.map((km, i) => {
    const fromKm = legKm.slice(0, i).reduce((sum, d) => sum + d, 0)
    return { fromKm: round1(fromKm), toKm: round1(fromKm + km), photos: [] }
  })

  const distanceKm = round1(legKm.reduce((sum, d) => sum + d, 0))
  const route: Route = {
    id: crypto.randomUUID(),
    geojson: { type: 'LineString', coordinates: waypoints.map((p) => [p.lon, p.lat]) },
    distanceKm,
    ascentM,
    durationMin: Math.round((distanceKm / WALK_KM_PER_HOUR + ascentM / CLIMB_M_PER_HOUR) * 60),
    places,
    segments,
  }
  routeRegistry = new Map([...routeRegistry, [route.id, route]])
  return route
}
