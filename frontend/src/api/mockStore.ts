import { ApiError } from './realApi'
import { haversineKm, round1, TRAIL_WINDING_FACTOR } from '../lib/geo'
import type { LatLon, Place, Route, RouteEditingContext, RouteSegment } from '../types'

// Shared in-memory state for the mock backend.
export const MOCK_LATENCY_MS = 500
const WALK_KM_PER_HOUR = 4
const CLIMB_M_PER_HOUR = 600
const SAME_POINT_KM = 0.05

let placeRegistry: ReadonlyMap<string, Place> = new Map()
let routeRegistry: ReadonlyMap<string, Route> = new Map()
let editingContextRegistry: ReadonlyMap<string, RouteEditingContext> = new Map()
export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const copyPlace = (place: Place): Place => ({
  ...place, tags: [...place.tags], photos: place.photos.map((photo) => ({ ...photo })),
})
export function registerPlace(place: Place): Place {
  const saved = copyPlace(place)
  placeRegistry = new Map([...placeRegistry, [saved.id, saved]])
  return copyPlace(saved)
}
export const getPlace = (id: string) => placeRegistry.get(id)

export function getRoute(id: string): Route {
  const route = routeRegistry.get(id)
  if (!route) throw new ApiError('The saved route does not exist.', 404, 'route_not_found')
  return {
    ...route,
    geojson: { type: 'LineString', coordinates: route.geojson.coordinates.map(([lon, lat]) => [lon, lat]) },
    places: route.places.map(copyPlace),
    segments: route.segments.map((segment) => ({ ...segment, photos: segment.photos.map((photo) => ({ ...photo })) })),
  }
}
export function getEditingContext(routeId: string): RouteEditingContext {
  const context = editingContextRegistry.get(routeId)
  if (!context) throw new ApiError('The saved route does not exist.', 404, 'route_not_found')
  const copy = (place: Place) => copyPlace(place)
  return {
    routeId: context.routeId,
    start: { ...context.start, place: context.start.place && copy(context.start.place) },
    end: { ...context.end, place: context.end.place && copy(context.end.place) },
    stops: context.stops.map(copy),
    preferences: [...context.preferences],
  }
}
export function saveEditingContext(routeId: string, context: Omit<RouteEditingContext, 'routeId'>) {
  const copy = (place: Place) => copyPlace(place)
  const saved: RouteEditingContext = {
    routeId,
    start: { ...context.start, place: context.start.place && copy(context.start.place) },
    end: { ...context.end, place: context.end.place && copy(context.end.place) },
    stops: context.stops.map(copy),
    preferences: [...context.preferences],
  }
  editingContextRegistry = new Map([...editingContextRegistry, [routeId, saved]])
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
    distanceKm, ascentM,
    durationMin: Math.round((distanceKm / WALK_KM_PER_HOUR + ascentM / CLIMB_M_PER_HOUR) * 60),
    places: places.map(copyPlace), segments,
  }
  routeRegistry = new Map([...routeRegistry, [route.id, route]])
  return getRoute(route.id)
}
