import type { ChatResponse, Place, Route, RouteRequest } from '../types'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
type JsonObject = Record<string, unknown>

export class ApiContractError extends Error {
  constructor(resource: string) {
    super(`The server returned invalid ${resource} data. Your current plan was kept; please try again.`)
    this.name = 'ApiContractError'
  }
}

export class StaleResultError extends Error {
  constructor() {
    super('The route inputs changed while this request was running. Your current route was kept; run the request again to apply the new inputs.')
    this.name = 'StaleResultError'
  }
}

const object = (value: unknown): value is JsonObject => typeof value === 'object' && value !== null && !Array.isArray(value)
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const text = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
const coordinate = (lat: unknown, lon: unknown): lat is number => finite(lat) && finite(lon) && lat >= -90 && lat <= 90 && (lon as number) >= -180 && (lon as number) <= 180

function invalid(resource: string): never {
  throw new ApiContractError(resource)
}

function parsePhoto(value: unknown, resource: string): void {
  if (!object(value) || !text(value.url) || !text(value.thumbUrl) || !text(value.author) || !text(value.license) || !text(value.sourceUrl) || !coordinate(value.lat, value.lon)) {
    invalid(resource)
  }
}

export function parsePlace(value: unknown, resource = 'place'): Place {
  if (!object(value) || typeof value.id !== 'string' || !UUID.test(value.id) || !text(value.name) || !coordinate(value.lat, value.lon) || !Array.isArray(value.tags) || !value.tags.every(text) || !Array.isArray(value.photos) || !text(value.source)) {
    invalid(resource)
  }
  value.photos.forEach((photo) => parsePhoto(photo, resource))
  return value as unknown as Place
}

function parseSegment(value: unknown, distanceKm: number): void {
  if (!object(value) || !finite(value.fromKm) || !finite(value.toKm) || value.fromKm < 0 || value.toKm < value.fromKm || value.toKm > distanceKm + 1e-6 || !Array.isArray(value.photos)) {
    invalid('route')
  }
  value.photos.forEach((photo) => parsePhoto(photo, 'route'))
}

export function parseRoute(value: unknown, expectedId?: string): Route {
  if (!object(value) || typeof value.id !== 'string' || !UUID.test(value.id) || (expectedId !== undefined && value.id !== expectedId)) invalid('route')
  if (!object(value.geojson) || value.geojson.type !== 'LineString' || !Array.isArray(value.geojson.coordinates) || value.geojson.coordinates.length < 2) invalid('route')
  for (const point of value.geojson.coordinates) {
    if (!Array.isArray(point) || point.length !== 2 || !coordinate(point[1], point[0])) invalid('route')
  }
  if (!finite(value.distanceKm) || value.distanceKm < 0 || !finite(value.ascentM) || value.ascentM < 0 || !finite(value.durationMin) || value.durationMin < 0 || !Array.isArray(value.places) || !Array.isArray(value.segments)) invalid('route')
  value.places.forEach((place) => parsePlace(place, 'route'))
  value.segments.forEach((segment) => parseSegment(segment, value.distanceKm as number))
  return value as unknown as Route
}

export function parseChatResponse(value: unknown): ChatResponse {
  if (!object(value) || !text(value.reply) || !Array.isArray(value.places) || (value.routeId !== undefined && (typeof value.routeId !== 'string' || !UUID.test(value.routeId)))) invalid('chat')
  value.places.forEach((place) => parsePlace(place, 'chat'))
  return value as unknown as ChatResponse
}

export function parseCreatedRoute(value: unknown, request: RouteRequest): Route {
  const route = parseRoute(value)
  const actualIds = route.places.map((place) => place.id)
  if (actualIds.length !== request.placeIds.length || actualIds.some((id, index) => id !== request.placeIds[index])) invalid('route')
  return route
}
