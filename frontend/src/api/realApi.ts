import { parsePlaceMedia } from '../lib/media'
import { isUuid, parseEditingContext, parseRoute } from '../lib/routeEditing'
import type { ApiClient } from '../types'

const API_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8080'
const AGENT_URL = import.meta.env.VITE_AGENT_BASE_URL ?? 'http://localhost:8000'

/** A failed API call with a message fit to show the user and, for API Problem Details, its stable `code`. */
export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  constructor(message: string, status: number, code?: string) {
    super(message); this.name = 'ApiError'; this.status = status; this.code = code
  }
}

/** A POST may have committed even though its response was lost or unusable. */
export class UncertainRouteSaveError extends Error {
  constructor(message = 'The route may have been saved. Submitting again can create another route.') {
    super(message); this.name = 'UncertainRouteSaveError'
  }
}
const MAX_MESSAGE_LENGTH = 300
type ErrorBody = { detail?: unknown; code?: unknown }

function readableDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (!Array.isArray(detail)) return undefined
  const messages = detail.map((item: unknown) => (typeof item === 'object' && item !== null ? (item as { msg?: unknown }).msg : undefined))
    .filter((msg): msg is string => typeof msg === 'string' && msg.trim() !== '')
  return messages.length > 0 ? messages.join('; ') : undefined
}
async function errorFrom(res: Response): Promise<ApiError> {
  let body: ErrorBody | undefined
  try { body = (await res.json()) as ErrorBody } catch { body = undefined }
  const message = readableDetail(body?.detail)?.slice(0, MAX_MESSAGE_LENGTH) ?? `Request failed (${res.status}). Please try again.`
  return new ApiError(message, res.status, typeof body?.code === 'string' ? body.code : undefined)
}
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) throw await errorFrom(res)
  return (await res.json()) as T
}
const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const realApi: ApiClient = {
  chat: (req) => request(`${AGENT_URL}/api/chat`, post(req)),
  addPlace: (place) => request(`${API_URL}/api/places`, post(place)),
  async createRoute(req, sourceRouteId) {
    let res: Response
    try { res = await fetch(`${API_URL}/api/routes`, post(req)) }
    catch { throw new UncertainRouteSaveError() }
    if (!res.ok) throw await errorFrom(res)
    if (res.status !== 201) throw new UncertainRouteSaveError('The route response was not a confirmed 201. The route may have been saved; submitting again can create another route.')
    try { return parseRoute(await res.json() as unknown, req, sourceRouteId) }
    catch { throw new UncertainRouteSaveError() }
  },
  async getRoute(id) {
    if (!isUuid(id)) throw new ApiError('Route ID must be a UUID.', 400, 'invalid_request')
    return parseRoute(await request<unknown>(`${API_URL}/api/routes/${encodeURIComponent(id)}`))
  },
  async getRouteEditingContext(routeId) {
    if (!isUuid(routeId)) throw new ApiError('Route ID must be a UUID.', 400, 'invalid_request')
    return parseEditingContext(await request<unknown>(`${API_URL}/api/routes/${encodeURIComponent(routeId)}/editing-context`), routeId)
  },
  // No query parameters: the API rejects unknown ones, including cache-busters.
  getPlaceMedia: async (placeId) => parsePlaceMedia(placeId, await request<unknown>(`${API_URL}/api/places/${encodeURIComponent(placeId)}/media`)),
}
