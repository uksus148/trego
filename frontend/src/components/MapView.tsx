import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource, MapMouseEvent } from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useEffect, useRef, useState } from 'react'
import { boundsOf } from '../lib/geo'
import { routeEndpoints, uniqueById } from '../lib/places'
import type { EditingEndpoint, LatLon, Place, Route, RouteEditingContext } from '../types'
import type { PickMode } from '../hooks/useTrip'

// Bundlers move MapLibre's module, so its self-relative worker lookup fails — point it at the worker explicitly.
maplibregl.setWorkerUrl(maplibreWorkerUrl)

const MAP_STYLE ='https://tiles.openfreemap.org/styles/liberty'
const DEFAULT_CENTER: [number, number] = [20.07, 49.15]
const DEFAULT_ZOOM = 11
const FIT_PADDING = { top: 60, bottom: 280, left: 60, right: 60 }
const EMPTY_LINE = { type: 'Feature' as const, properties: {}, geometry: { type: 'LineString' as const, coordinates: [] } }

interface MapViewProps {
  route: Route | null
  start: LatLon | null
  end: LatLon | null
  places: Place[]
  chatPlaces: Place[]
  committedContext: RouteEditingContext | null
  draftEndpoints: { start: EditingEndpoint; end: EditingEndpoint } | null
  pendingPoint: LatLon | null
  pickMode: PickMode
  onMapClick: (point: LatLon) => void
  /** Pin a place's card (click, tap, Enter). */
  onSelectPlace: (placeId: string) => void
  /** Preview a place's card while hovered or focused; null when the pointer or focus leaves. */
  onPreviewPlace: (placeId: string | null) => void
  /** First verified photo thumbnail per place UUID, shown on the marker. */
  thumbnails: ReadonlyMap<string, string>
}

type MarkerSpec = {
  point: LatLon
  label: string
  title: string
  variant: 'start' | 'end' | 'place' | 'pending' | 'draft-start' | 'draft-end'
  placeId?: string
  thumbUrl?: string
}

type MarkerHandlers = { select: (placeId: string) => void; preview: (placeId: string | null) => void }

const MARKER_CLASSES: Record<MarkerSpec['variant'], string> = {
  start: 'bg-moss text-white',
  end: 'bg-ink text-white',
  place: 'bg-trail text-white',
  pending: 'bg-white text-trail border-2 border-dashed border-trail',
  'draft-start': 'bg-white text-moss border-2 border-dashed border-moss',
  'draft-end': 'bg-white text-ink border-2 border-dashed border-ink',
}

const RING_CLASSES: Record<MarkerSpec['variant'], string> = {
  start: 'ring-moss',
  end: 'ring-ink',
  place: 'ring-trail',
  pending: 'ring-trail',
  'draft-start': 'ring-moss',
  'draft-end': 'ring-ink',
}

function markerBody(spec: MarkerSpec): HTMLElement {
  const el = document.createElement('div')
  // No transition/transform utilities here: MapLibre positions markers with `transform`, and animating it
  // makes the marker slide away between mousedown and mouseup, so the click never lands.
  if (!spec.thumbUrl) {
    el.className = `grid size-8 place-items-center rounded-full text-sm font-semibold shadow-lg ring-2 ring-white ${MARKER_CLASSES[spec.variant]}`
    el.textContent = spec.label
    return el
  }
  // A verified photo replaces the dot; the visit label stays as a badge so order is still readable.
  el.className = `size-12 rounded-full bg-white p-0.5 shadow-lg ring-3 ${RING_CLASSES[spec.variant]}`
  const img = document.createElement('img')
  img.src = spec.thumbUrl
  img.alt = ''
  img.className = 'size-full rounded-full object-cover'
  img.addEventListener('error', () => img.remove()) // a broken image affects this marker only
  const badge = document.createElement('span')
  badge.className = `absolute -top-1 -right-1 grid size-5 place-items-center rounded-full text-[11px] font-semibold ring-2 ring-white ${MARKER_CLASSES[spec.variant]}`
  badge.textContent = spec.label
  el.append(img, badge)
  return el
}

function markerElement(spec: MarkerSpec, handlers: MarkerHandlers): HTMLElement {
  const el = markerBody(spec)
  el.title = spec.title
  const { placeId } = spec
  if (!placeId) return el
  el.classList.add('cursor-pointer', 'hover:brightness-110')
  el.setAttribute('role', 'button')
  el.setAttribute('aria-label', `${spec.title}: show details`)
  el.tabIndex = 0
  el.addEventListener('click', (event) => {
    event.stopPropagation() // don't also count as a map click while picking points
    handlers.select(placeId)
  })
  el.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    handlers.select(placeId)
  })
  el.addEventListener('mouseenter', () => handlers.preview(placeId))
  el.addEventListener('focus', () => handlers.preview(placeId))
  el.addEventListener('mouseleave', () => handlers.preview(null))
  el.addEventListener('blur', () => handlers.preview(null))
  return el
}

/** With a route, A and B sit on the track ends; before one exists, they show the points picked on the map. */
function endpointSpecs(props: MapViewProps): MarkerSpec[] {
  const endpoints = props.route
    ? routeEndpoints(props.route, props.chatPlaces, props.committedContext)
    : { start: props.start && { point: props.start }, end: props.end && { point: props.end } }
  const { start, end } = endpoints
  return [
    ...(start ? [{ point: start.point, label: 'A', title: start.place?.name ?? 'Start', variant: 'start' as const, placeId: start.place?.id }] : []),
    ...(end ? [{ point: end.point, label: 'B', title: end.place?.name ?? 'Finish', variant: 'end' as const, placeId: end.place?.id }] : []),
  ]
}

function markerSpecs(props: MapViewProps): MarkerSpec[] {
  const routePlaces = uniqueById(props.route?.places ?? props.places)
  const committed = props.route && props.committedContext?.routeId === props.route.id ? props.committedContext : null
  const changed = (side: 'start' | 'end') => {
    const draft = props.draftEndpoints?.[side], saved = committed?.[side]
    return draft && saved && (draft.lat !== saved.lat || draft.lon !== saved.lon || draft.place?.id !== saved.place?.id)
  }
  const previews: MarkerSpec[] = []
  if (props.draftEndpoints && changed('start')) {
    const p = props.draftEndpoints.start
    previews.push({ point: p, label: 'A′', title: `Unbuilt start · ${p.place?.name ?? p.lat.toFixed(5) + ', ' + p.lon.toFixed(5)}`, variant: 'draft-start' })
  }
  if (props.draftEndpoints && changed('end')) {
    const p = props.draftEndpoints.end
    previews.push({ point: p, label: 'B′', title: `Unbuilt finish · ${p.place?.name ?? p.lat.toFixed(5) + ', ' + p.lon.toFixed(5)}`, variant: 'draft-end' })
  }
  const specs: MarkerSpec[] = [
    ...endpointSpecs(props),
    ...routePlaces.map((p, i) => ({ point: p, label: String(i + 1), title: p.name, variant: 'place' as const, placeId: p.id })),
    ...previews,
    ...(props.pendingPoint ? [{ point: props.pendingPoint, label: '+', title: 'New place', variant: 'pending' as const }] : []),
  ]
  return specs.map((spec) => {
    const thumbUrl = spec.placeId ? props.thumbnails.get(spec.placeId) : undefined
    return thumbUrl ? { ...spec, thumbUrl } : spec
  })
}

const LINE_LAYOUT = { 'line-join': 'round', 'line-cap': 'round' } as const

function addRouteLayers(map: maplibregl.Map) {
  map.addSource('route', { type: 'geojson', data: EMPTY_LINE })
  map.addLayer({ id: 'route-casing', type: 'line', source: 'route', paint: { 'line-color': '#ffffff', 'line-width': 9 }, layout: LINE_LAYOUT })
  map.addLayer({ id: 'route-line', type: 'line', source: 'route', paint: { 'line-color': '#e4572e', 'line-width': 5 }, layout: LINE_LAYOUT })
}

const lineFeature = (coordinates: [number, number][]) => ({ ...EMPTY_LINE, geometry: { type: 'LineString' as const, coordinates } })

export function MapView(props: MapViewProps) {
  const { route, places, pickMode, onMapClick } = props
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const clickRef = useRef(onMapClick)
  const selectRef = useRef(props.onSelectPlace)
  const previewRef = useRef(props.onPreviewPlace)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    selectRef.current = props.onSelectPlace
    previewRef.current = props.onPreviewPlace
  }, [props.onSelectPlace, props.onPreviewPlace])

  useEffect(() => {
    clickRef.current = onMapClick
  }, [onMapClick])

  useEffect(() => {
    if (!containerRef.current) return
    const map = new maplibregl.Map({ container: containerRef.current, style: MAP_STYLE, center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.on('load', () => {
      addRouteLayers(map)
      setLoaded(true)
    })
    map.on('click', (e: MapMouseEvent) => clickRef.current({ lat: e.lngLat.lat, lon: e.lngLat.lng }))
    mapRef.current = map
    return () => map.remove()
  }, [])

  useEffect(() => {
    if (mapRef.current) mapRef.current.getCanvas().style.cursor = pickMode ? 'crosshair' : ''
  }, [pickMode])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    const coords = route?.geojson.coordinates ?? []
    ;(map.getSource('route') as GeoJSONSource).setData(lineFeature(coords))
    if (coords.length > 1) map.fitBounds(boundsOf(coords), { padding: FIT_PADDING, duration: 900 })
  }, [route, loaded])

  // Without a route, bring chosen places into view — but only when some are off-screen, so manual clicks don't move the map.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded || route || places.length === 0) return
    const coords = places.map((p): [number, number] => [p.lon, p.lat])
    const bounds = map.getBounds()
    if (coords.every((c) => bounds.contains(c))) return
    map.fitBounds(boundsOf(coords), { padding: FIT_PADDING, duration: 700, maxZoom: 13 })
  }, [places, route, loaded])

  // Markers carry only plain data, so a JSON key is a cheap way to re-create them only when they change.
  const specsKey = JSON.stringify(markerSpecs(props).map(({ point, ...rest }) => ({ ...rest, point: { lat: point.lat, lon: point.lon } })))
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const markers = (JSON.parse(specsKey) as MarkerSpec[]).map((spec) =>
      new maplibregl.Marker({
        element: markerElement(spec, { select: (id) => selectRef.current(id), preview: (id) => previewRef.current(id) }),
      })
        .setLngLat([spec.point.lon, spec.point.lat])
        .addTo(map),
    )
    return () => markers.forEach((m) => m.remove())
  }, [specsKey])

  // MapLibre's own CSS forces position:relative on the map element, so size it via a wrapper.
  return (
    <div className="absolute inset-0">
      <div ref={containerRef} className="size-full" aria-label="Route map" />
    </div>
  )
}
