import type { LatLon } from '../types'

const EARTH_RADIUS_KM = 6371

/** Real paths are longer than straight lines; used to estimate walking distance. */
export const TRAIL_WINDING_FACTOR = 1.35

/** Round to 0.1 — the precision we show for kilometres everywhere. */
export const round1 = (n: number) => Math.round(n * 10) / 10

const toRad = (deg: number) => (deg * Math.PI) / 180

export function haversineKm(a: LatLon, b: LatLon): number {
  const dLat = toRad(b.lat - a.lat)
  const dLon = toRad(b.lon - a.lon)
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(h))
}

export function boundsOf(coords: [number, number][]): [[number, number], [number, number]] {
  const lons = coords.map((c) => c[0])
  const lats = coords.map((c) => c[1])
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ]
}
