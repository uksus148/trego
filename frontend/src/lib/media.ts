import type { LandmarkPhoto, LatLon, PlaceMedia, SourcedText } from '../types'

// Client-side checks for GET /api/places/{id}/media (docs/LANDMARK_PHOTOS_CONTRACT.md, section 5).
// A response that breaks the contract becomes a gallery error; the route and place card stay usable.

export class MediaContractError extends Error {
  constructor(reason: string) {
    super(`Photo data was invalid: ${reason}`)
    this.name = 'MediaContractError'
  }
}

// Exact hosts from the contract (section 5): originals only on upload, thumbnails on upload or thumb. No wildcards.
const IMAGE_HOSTS = ['upload.wikimedia.org'] as const
const THUMB_HOSTS = ['upload.wikimedia.org', 'thumb.wikimedia.org'] as const
const COMMONS_ID = /^commons:[1-9]\d*$/
const MAX_TITLE = 300
const MAX_TEXT = 1000
const MAX_AUTHOR = 500

type Json = Record<string, unknown>

const isObject = (value: unknown): value is Json => typeof value === 'object' && value !== null && !Array.isArray(value)

function fail(reason: string): never {
  throw new MediaContractError(reason)
}

function text(value: unknown, field: string, max: number): string {
  if (typeof value !== 'string' || value.trim() === '' || value.length > max) fail(`${field} must be nonblank text up to ${max} characters`)
  return value
}

/** HTTPS only, no embedded credentials or explicit port, optionally limited to exact hosts. */
function httpsUrl(value: unknown, field: string, hosts?: readonly string[]): string {
  if (typeof value !== 'string') fail(`${field} must be a URL`)
  let url: URL
  try {
    url = new URL(value)
  } catch {
    return fail(`${field} must be a URL`)
  }
  const safe = url.protocol === 'https:' && url.username === '' && url.password === '' && url.port === ''
  if (!safe || (hosts !== undefined && !hosts.includes(url.hostname))) fail(`${field} is not an allowed HTTPS URL`)
  return value
}

function sourcedText(value: unknown, field: string): SourcedText | null {
  if (value === null) return null
  if (!isObject(value)) fail(`${field} must be null or an object`)
  return { text: text(value.text, `${field}.text`, MAX_TEXT), sourceUrl: httpsUrl(value.sourceUrl, `${field}.sourceUrl`) }
}

function location(value: unknown): LatLon | null {
  if (value === null) return null
  if (!isObject(value)) fail('photoLocation must be null or an object')
  const { lat, lon } = value
  const valid = typeof lat === 'number' && typeof lon === 'number' && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
  if (!valid) fail('photoLocation must hold WGS84 coordinates')
  return { lat, lon }
}

function photo(value: unknown): LandmarkPhoto {
  if (!isObject(value)) fail('photo must be an object')
  if (typeof value.id !== 'string' || !COMMONS_ID.test(value.id)) fail('photo id must be commons:<page id>')
  if (value.provider !== 'wikimedia_commons') fail('provider must be wikimedia_commons')
  if (!('description' in value)) fail('description key is required')
  return {
    id: value.id,
    provider: 'wikimedia_commons',
    url: httpsUrl(value.url, 'url', IMAGE_HOSTS),
    thumbUrl: httpsUrl(value.thumbUrl, 'thumbUrl', THUMB_HOSTS),
    title: text(value.title, 'title', MAX_TITLE),
    description: sourcedText(value.description, 'description'),
    author: text(value.author, 'author', MAX_AUTHOR),
    license: text(value.license, 'license', MAX_TITLE),
    licenseUrl: httpsUrl(value.licenseUrl, 'licenseUrl'),
    sourceUrl: httpsUrl(value.sourceUrl, 'sourceUrl'),
    associationSourceUrl: httpsUrl(value.associationSourceUrl, 'associationSourceUrl'),
    photoLocation: location(value.photoLocation),
  }
}

/** Validate a media response for the requested place; throws MediaContractError on any violation. */
export function parsePlaceMedia(placeId: string, body: unknown): PlaceMedia {
  if (!isObject(body)) fail('response must be an object')
  if (body.placeId !== placeId) fail('placeId does not match the requested place')
  if (!Array.isArray(body.photos)) fail('photos must be a list')
  const expectedCount = body.status === 'ready' ? 1 : body.status === 'empty' ? 0 : fail('status must be ready or empty')
  if (body.photos.length !== expectedCount) fail(`status ${String(body.status)} contradicts ${body.photos.length} photos`)
  if (body.fetchedAt !== null && (typeof body.fetchedAt !== 'string' || Number.isNaN(Date.parse(body.fetchedAt)))) {
    fail('fetchedAt must be null or an RFC3339 time')
  }
  if (!('placeDescription' in body)) fail('placeDescription key is required')
  return {
    placeId,
    status: body.status as PlaceMedia['status'],
    fetchedAt: body.fetchedAt as string | null,
    placeDescription: sourcedText(body.placeDescription, 'placeDescription'),
    photos: body.photos.map(photo),
  }
}

export type MediaState =
  | { status: 'loading' }
  | { status: 'ready'; media: PlaceMedia }
  | { status: 'error'; message: string }

export const MAX_CONCURRENT_MEDIA = 2

/**
 * Which places to request next: the selected place first, then the rest in visit order,
 * skipping places already loading or loaded, and never exceeding the concurrency limit.
 */
export function nextMediaRequests(wanted: string[], selected: string | null, states: ReadonlyMap<string, MediaState>): string[] {
  const loading = [...states.values()].filter((state) => state.status === 'loading').length
  const free = MAX_CONCURRENT_MEDIA - loading
  if (free <= 0) return []
  const ordered = selected && wanted.includes(selected) ? [selected, ...wanted] : wanted
  return [...new Set(ordered)].filter((id) => !states.has(id)).slice(0, free)
}

/** The first verified photo of a place, if its media has loaded. */
export function firstPhoto(state: MediaState | undefined): LandmarkPhoto | undefined {
  return state?.status === 'ready' ? state.media.photos[0] : undefined
}
