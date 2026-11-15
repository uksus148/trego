import { parsePlaceMedia } from '../lib/media'
import { ApiContractError, parseChatResponse, parseCreatedRoute, parsePlace, parseRoute } from '../lib/apiContract'
import type { ApiClient } from '../types'

const API_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8080'
const AGENT_URL = import.meta.env.VITE_AGENT_BASE_URL ?? 'http://localhost:8000'

/** A failed API call with a message fit to show the user and, for API Problem Details, its stable `code`. */
export class ApiError extends Error {
  readonly status: number
  readonly code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

const MAX_MESSAGE_LENGTH = 300

type ErrorBody = { detail?: unknown; code?: unknown }

/** API Problem Details and FastAPI both put the human-readable text in `detail`; FastAPI validation uses a list of `{msg}`. */
function readableDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (!Array.isArray(detail)) return undefined
  const messages = detail
    .map((item: unknown) => (typeof item === 'object' && item !== null ? (item as { msg?: unknown }).msg : undefined))
    .filter((msg): msg is string => typeof msg === 'string' && msg.trim() !== '')
  return messages.length > 0 ? messages.join('; ') : undefined
}

async function errorFrom(res: Response): Promise<ApiError> {
  const fallback = `Request failed (${res.status}). Please try again.`
  let body: ErrorBody | undefined
  try {
    body = (await res.json()) as ErrorBody // non-JSON bodies (e.g. a proxy's HTML page) fall back below
  } catch {
    body = undefined
  }
  const message = readableDetail(body?.detail)?.slice(0, MAX_MESSAGE_LENGTH) ?? fallback
  const code = typeof body?.code === 'string' ? body.code : undefined
  return new ApiError(message, res.status, code)
}

async function request<T>(url: string, init?: RequestInit, expectedStatus?: number): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) throw await errorFrom(res)
  if (expectedStatus !== undefined && res.status !== expectedStatus) throw new ApiError(`Unexpected success response (${res.status}). Please try again.`, res.status)
  try {
    return (await res.json()) as T
  } catch {
    throw new ApiContractError('response')
  }
}

// Only requests with a body declare JSON; bodiless GETs stay "simple" CORS requests with no preflight.
const post = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const realApi: ApiClient = {
  chat: async (req) => parseChatResponse(await request<unknown>(`${AGENT_URL}/api/chat`, post(req), 200)),
  addPlace: async (place) => parsePlace(await request<unknown>(`${API_URL}/api/places`, post(place), 201)),
  createRoute: async (req) => parseCreatedRoute(await request<unknown>(`${API_URL}/api/routes`, post(req), 201), req),
  getRoute: async (id) => parseRoute(await request<unknown>(`${API_URL}/api/routes/${encodeURIComponent(id)}`, undefined, 200), id),
  // No query parameters: the API rejects unknown ones, including cache-busters.
  getPlaceMedia: async (placeId) =>
    parsePlaceMedia(placeId, await request<unknown>(`${API_URL}/api/places/${encodeURIComponent(placeId)}/media`)),
}
