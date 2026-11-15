import { useCallback, useEffect, useRef, useState } from 'react'
import { AlongTheWay } from './components/AlongTheWay'
import { MapView } from './components/MapView'
import { PhotoViewer } from './components/PhotoViewer'
import { PlaceCard } from './components/PlaceCard'
import { Sidebar } from './components/Sidebar'
import { usePlaceMedia } from './hooks/usePlaceMedia'
import { useTrip } from './hooks/useTrip'
import { firstPhoto } from './lib/media'
import { routeVisits, uniqueById } from './lib/places'
import type { LandmarkPhoto, Place } from './types'

const PREVIEW_CLOSE_DELAY_MS = 250
type RoutePhoto = { routeId: string | null; photo: LandmarkPhoto }
type RoutePlaceSelection = { routeId: string | null; placeId: string }

export default function App() {
  const trip = useTrip()
  const routeId = trip.route?.id ?? null
  const [openPhoto, setOpenPhoto] = useState<RoutePhoto | null>(null)
  const [pinnedPlace, setPinnedPlace] = useState<RoutePlaceSelection | null>(null)
  const [previewPlace, setPreviewPlace] = useState<RoutePlaceSelection | null>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const context = trip.route && trip.committedContext?.routeId === trip.route.id ? trip.committedContext : null
  const contextVisits = context ? [
    ...(context.start.place ? [{ place: context.start.place, label: 'A' }] : []),
    ...context.stops.map((place, index) => ({
      place,
      label: String([...new Set(context.stops.slice(0, index + 1).map((item) => item.id))].indexOf(place.id) + 1),
    })),
    ...(context.end.place ? [{ place: context.end.place, label: 'B' }] : []),
  ] : null
  const visits = trip.route ? (contextVisits ?? routeVisits(trip.route, trip.chatPlaces)) : trip.places.map((place, i) => ({ place, label: String(i + 1) }))
  const knownPlaces: Place[] = [
    ...visits.map((visit) => visit.place), ...trip.chatPlaces, ...trip.places,
    ...(context?.start.place ? [context.start.place] : []), ...(context?.end.place ? [context.end.place] : []),
  ]
  const pinnedPlaceId = pinnedPlace?.routeId === routeId ? pinnedPlace.placeId : null
  const previewPlaceId = previewPlace?.routeId === routeId ? previewPlace.placeId : null
  const activePlaceId = previewPlaceId ?? pinnedPlaceId
  const activePlace = knownPlaces.find((place) => place.id === activePlaceId) ?? null
  const activePhoto = openPhoto?.routeId === routeId ? openPhoto.photo : null
  const mediaPlaceIds = uniqueById(visits.map((visit) => visit.place)).map((place) => place.id)
  const media = usePlaceMedia(mediaPlaceIds, activePlace?.id ?? null)
  const thumbnails = new Map(
    [...media.states].flatMap(([id, state]): [string, string][] => {
      const photo = firstPhoto(state)
      return photo ? [[id, photo.thumbUrl]] : []
    }),
  )

  const keepPreview = useCallback(() => clearTimeout(closeTimer.current), [])
  const preview = useCallback((placeId: string | null) => {
    clearTimeout(closeTimer.current)
    if (placeId) setPreviewPlace({ routeId, placeId })
    else closeTimer.current = setTimeout(() => setPreviewPlace((current) => current?.routeId === routeId ? null : current), PREVIEW_CLOSE_DELAY_MS)
  }, [routeId])
  const pinPlace = useCallback((placeId: string) => {
    clearTimeout(closeTimer.current)
    setPreviewPlace(null)
    setPinnedPlace({ routeId, placeId })
  }, [routeId])
  const showPhoto = useCallback((photo: LandmarkPhoto) => setOpenPhoto({ routeId, photo }), [routeId])
  const closePhoto = useCallback(() => setOpenPhoto(null), [])
  useEffect(() => () => clearTimeout(closeTimer.current), [])
  useEffect(() => { clearTimeout(closeTimer.current) }, [routeId])

  const draftEndpoints = trip.editor.status === 'ready'
    ? { start: trip.editor.draft.start, end: trip.editor.draft.end }
    : null
  return (
    <div className="flex h-dvh flex-col md:flex-row">
      <Sidebar trip={trip} />
      <main className="relative min-h-0 flex-1">
        <MapView route={trip.route} start={trip.start} end={trip.end} places={trip.places} chatPlaces={trip.chatPlaces}
          committedContext={context} draftEndpoints={draftEndpoints} pendingPoint={trip.pendingPoint} pickMode={trip.pickMode}
          onMapClick={trip.handleMapClick} onSelectPlace={pinPlace} onPreviewPlace={preview} thumbnails={thumbnails} />
        {activePlace && <PlaceCard key={activePlace.id} place={activePlace} media={media.states.get(activePlace.id)}
          isPinned={activePlace.id === pinnedPlaceId} onClose={() => setPinnedPlace(null)} onOpenPhoto={showPhoto}
          onRetryMedia={() => media.retry(activePlace.id)} onPointerEnter={keepPreview} onPointerLeave={() => preview(null)} />}
        {trip.route && <AlongTheWay visits={visits} media={media.states} onSelectPlace={pinPlace} onOpenPhoto={showPhoto} />}
      </main>
      {activePhoto && <PhotoViewer photo={activePhoto} onClose={closePhoto} />}
    </div>
  )
}
