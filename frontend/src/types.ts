// Shared API contract — the agreed baseline from the root CLAUDE.md ("API contract").
// Change only together with the api and agent owners.

export type LatLon = { lat: number; lon: number }
export type Photo = { url: string; thumbUrl: string; author: string; license: string; sourceUrl: string; lat: number; lon: number }
export type Place = { id: string; name: string; lat: number; lon: number; tags: string[]; photos: Photo[]; source: string }
export type LineString = { type: 'LineString'; coordinates: [number, number][] } // [lon, lat]
export type RouteSegment = { fromKm: number; toKm: number; photos: Photo[] }
export type Route = {
  id: string
  geojson: LineString
  distanceKm: number
  ascentM: number
  durationMin: number
  places: Place[]
  segments: RouteSegment[]
}
export type ChatRequest = { sessionId: string; message: string }
export type ChatResponse = { reply: string; places: Place[]; routeId?: string }
export type NewPlace = { name: string; lat: number; lon: number; tags: string[] }
export type RouteRequest = {
  start: LatLon
  end: LatLon
  placeIds: string[]
  preferences: string[]
  startPlaceId?: string | null
  endPlaceId?: string | null
}
export type EditingEndpoint = LatLon & { place: Place | null }
export type RouteEditingContext = {
  routeId: string
  start: EditingEndpoint
  end: EditingEndpoint
  stops: Place[]
  preferences: string[]
}
export type ChatMessage = { id: string; role: 'user' | 'assistant'; text: string }
export type SourcedText = { text: string; sourceUrl: string }
export type LandmarkPhoto = {
  id: string
  provider: 'wikimedia_commons'
  url: string
  thumbUrl: string
  title: string
  description: SourcedText | null
  author: string
  license: string
  licenseUrl: string
  sourceUrl: string
  associationSourceUrl: string
  photoLocation: LatLon | null
}
export type PlaceMedia = {
  placeId: string
  status: 'ready' | 'empty'
  fetchedAt: string | null
  placeDescription: SourcedText | null
  photos: LandmarkPhoto[]
}
export interface ApiClient {
  chat(request: ChatRequest): Promise<ChatResponse>
  addPlace(place: NewPlace): Promise<Place>
  createRoute(request: RouteRequest, sourceRouteId?: string): Promise<Route>
  getRoute(id: string): Promise<Route>
  getRouteEditingContext(routeId: string): Promise<RouteEditingContext>
  getPlaceMedia(placeId: string): Promise<PlaceMedia>
}
