import type { EditingEndpoint, LatLon, Place, Photo, Route, RouteEditingContext, RouteRequest } from '../types'

type Row = { key: string; place: Place }
export type Draft = { start: EditingEndpoint; end: EditingEndpoint; rows: Row[]; preferences: string[] }

export function canOpenRouteEditor(input: {
  enabled: boolean
  status: 'closed' | 'loading' | 'ready'
  requestPending: boolean
  tripBusy: boolean
  activeRouteId: string | null
}): boolean {
  return input.enabled && input.status === 'closed' && !input.requestPending && !input.tripBusy && input.activeRouteId !== null
}

export class RoutePayloadError extends Error {
  constructor(message: string) { super(message); this.name = 'RoutePayloadError' }
}

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export const isUuid = (value: unknown): value is string => typeof value === 'string' && UUID_PATTERN.test(value)
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const wgs84 = (value: unknown): value is LatLon =>
  isRecord(value) && finite(value.lat) && value.lat >= -90 && value.lat <= 90 && finite(value.lon) && value.lon >= -180 && value.lon <= 180
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string')

function parsePhoto(value: unknown): Photo {
  if (!isRecord(value) || !['url', 'thumbUrl', 'author', 'license', 'sourceUrl'].every((key) => typeof value[key] === 'string') ||
    !wgs84({ lat: value.lat, lon: value.lon })) throw new RoutePayloadError('Route contains an invalid photo.')
  return value as unknown as Photo
}

export function parsePlace(value: unknown): Place {
  if (!isRecord(value) || !isUuid(value.id) || typeof value.name !== 'string' || !value.name.trim() ||
    typeof value.source !== 'string' || !wgs84({ lat: value.lat, lon: value.lon }) ||
    !strings(value.tags) || !Array.isArray(value.photos)) throw new RoutePayloadError('Route contains an invalid place.')
  return { ...value, photos: value.photos.map(parsePhoto) } as unknown as Place
}

function parseEndpoint(value: unknown): EditingEndpoint {
  if (!isRecord(value) || !Object.keys(value).every((key) => ['lat', 'lon', 'place'].includes(key)) ||
    !['lat', 'lon', 'place'].every((key) => Object.prototype.hasOwnProperty.call(value, key)) ||
    !wgs84({ lat: value.lat, lon: value.lon })) throw new RoutePayloadError('Editing context contains an invalid endpoint.')
  const place = value.place === null ? null : parsePlace(value.place)
  if (place && (place.lat !== value.lat || place.lon !== value.lon)) throw new RoutePayloadError('Endpoint coordinates do not match the bound place.')
  return { lat: value.lat as number, lon: value.lon as number, place }
}

export function parseEditingContext(value: unknown, requestedRouteId: string): RouteEditingContext {
  const keys = ['routeId', 'start', 'end', 'stops', 'preferences']
  if (!isUuid(requestedRouteId) || !isRecord(value) || Object.keys(value).some((key) => !keys.includes(key)) ||
    keys.some((key) => !Object.prototype.hasOwnProperty.call(value, key)) || value.routeId !== requestedRouteId ||
    !Array.isArray(value.stops) || value.stops.length > 5 || !strings(value.preferences)) {
    throw new RoutePayloadError('The route editing context is invalid.')
  }
  return {
    routeId: requestedRouteId, start: parseEndpoint(value.start), end: parseEndpoint(value.end),
    stops: value.stops.map(parsePlace), preferences: [...value.preferences],
  }
}

export function parseRoute(value: unknown, request?: RouteRequest, sourceRouteId?: string): Route {
  if (!isRecord(value) || !isUuid(value.id) || (sourceRouteId !== undefined && value.id === sourceRouteId) ||
    !isRecord(value.geojson) || value.geojson.type !== 'LineString' || !Array.isArray(value.geojson.coordinates) ||
    value.geojson.coordinates.length < 2 ||
    !value.geojson.coordinates.every((p) => Array.isArray(p) && p.length === 2 && finite(p[0]) && p[0] >= -180 && p[0] <= 180 && finite(p[1]) && p[1] >= -90 && p[1] <= 90) ||
    !finite(value.distanceKm) || value.distanceKm < 0 || !finite(value.ascentM) || value.ascentM < 0 ||
    !finite(value.durationMin) || value.durationMin < 0 || !Array.isArray(value.places) || !Array.isArray(value.segments)) {
    throw new RoutePayloadError('The saved route response is invalid.')
  }
  const places = value.places.map(parsePlace)
  if (request && (places.length !== request.placeIds.length || places.some((p, i) => p.id !== request.placeIds[i]))) {
    throw new RoutePayloadError('The saved route does not preserve the submitted stop order.')
  }
  const segments = value.segments.map((s) => {
    if (!isRecord(s) || !finite(s.fromKm) || !finite(s.toKm) || s.fromKm < 0 || s.toKm < s.fromKm || !Array.isArray(s.photos)) {
      throw new RoutePayloadError('The saved route contains an invalid segment.')
    }
    return { fromKm: s.fromKm, toKm: s.toKm, photos: s.photos.map(parsePhoto) }
  })
  return {
    id: value.id, geojson: { type: 'LineString', coordinates: value.geojson.coordinates as [number, number][] },
    distanceKm: value.distanceKm, ascentM: value.ascentM, durationMin: value.durationMin, places, segments,
  }
}

export function fromContext(c: RouteEditingContext): Draft {
  return { start: { ...c.start }, end: { ...c.end }, rows: c.stops.map((place) => ({ key: crypto.randomUUID(), place })), preferences: [...c.preferences] }
}
export function rawEndpoint({ lat, lon }: LatLon): EditingEndpoint { return { lat, lon, place: null } }
export function boundEndpoint(place: Place): EditingEndpoint { return { lat: place.lat, lon: place.lon, place } }
export function removeVisit(draft: Draft, key: string): Draft { return { ...draft, rows: draft.rows.filter((row) => row.key !== key) } }
export function moveVisit(draft: Draft, key: string, delta: -1 | 1): Draft {
  const from = draft.rows.findIndex((row) => row.key === key), to = from + delta
  if (from < 0 || to < 0 || to >= draft.rows.length) return draft
  const rows = [...draft.rows]
  ;[rows[from], rows[to]] = [rows[to], rows[from]]
  return { ...draft, rows }
}
export function swapEndpoints(draft: Draft): Draft { return { ...draft, start: draft.end, end: draft.start } }
export function toRequest(draft: Draft): RouteRequest {
  return {
    start: { lat: draft.start.lat, lon: draft.start.lon }, end: { lat: draft.end.lat, lon: draft.end.lon },
    placeIds: draft.rows.map((row) => row.place.id), preferences: [...draft.preferences],
    startPlaceId: draft.start.place?.id ?? null, endPlaceId: draft.end.place?.id ?? null,
  }
}
export function isDirty(initial: Draft, current: Draft): boolean { return JSON.stringify(toRequest(initial)) !== JSON.stringify(toRequest(current)) }
export function isValidDraft(draft: Draft): boolean {
  const request = toRequest(draft)
  return draft.rows.length <= 5 && wgs84(request.start) && wgs84(request.end) && request.placeIds.every(isUuid) &&
    strings(request.preferences) && draft.rows.every((row) => isUuid(row.key) && isUuid(row.place.id)) &&
    (!draft.start.place || (draft.start.lat === draft.start.place.lat && draft.start.lon === draft.start.place.lon)) &&
    (!draft.end.place || (draft.end.lat === draft.end.place.lat && draft.end.lon === draft.end.place.lon))
}
export function cloneDraft(draft: Draft): Draft {
  const copy = (place: Place): Place => ({ ...place, tags: [...place.tags], photos: place.photos.map((photo) => ({ ...photo })) })
  return {
    start: { ...draft.start, place: draft.start.place && copy(draft.start.place) },
    end: { ...draft.end, place: draft.end.place && copy(draft.end.place) },
    rows: draft.rows.map((row) => ({ key: row.key, place: copy(row.place) })), preferences: [...draft.preferences],
  }
}
export function visitsFromDraft(draft: Draft) {
  const uniqueStopIds = [...new Set(draft.rows.map((row) => row.place.id))]
  return [
    ...(draft.start.place ? [{ place: draft.start.place, label: 'A' }] : []),
    ...draft.rows.map((row) => ({ place: row.place, label: String(uniqueStopIds.indexOf(row.place.id) + 1) })),
    ...(draft.end.place ? [{ place: draft.end.place, label: 'B' }] : []),
  ]
}
