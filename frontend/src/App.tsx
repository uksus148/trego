import { useCallback, useEffect, useRef, useState } from 'react'
import { AlongTheWay } from './components/AlongTheWay'
import { MapView } from './components/MapView'
import { PhotoViewer } from './components/PhotoViewer'
import { PlaceCard } from './components/PlaceCard'
import { Sidebar } from './components/Sidebar'
import { usePlaceMedia } from './hooks/usePlaceMedia'
import { useTrip } from './hooks/useTrip'
import { firstPhoto } from './lib/media'
import { routeVisits } from './lib/places'
import type { LandmarkPhoto } from './types'

// Long enough to move the pointer from a marker onto the card without it closing.
const PREVIEW_CLOSE_DELAY_MS = 250

export default function App() {
  const trip = useTrip()
  const [openPhoto, setOpenPhoto] = useState<LandmarkPhoto | null>(null)
  const [pinnedPlaceId, setPinnedPlaceId] = useState<string | null>(null)
  const [previewPlaceId, setPreviewPlaceId] = useState<string | null>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const visits = trip.route ? routeVisits(trip.route, trip.chatPlaces) : trip.places.map((place, i) => ({ place, label: String(i + 1) }))
  const knownPlaces = [...visits.map((v) => v.place), ...trip.chatPlaces, ...trip.places]
  const activePlaceId = previewPlaceId ?? pinnedPlaceId
  const activePlace = knownPlaces.find((p) => p.id === activePlaceId) ?? null

  const media = usePlaceMedia(visits.map((v) => v.place.id), activePlace?.id ?? null)
  const thumbnails = new Map(
    [...media.states].flatMap(([id, state]): [string, string][] => {
      const photo = firstPhoto(state)
      return photo ? [[id, photo.thumbUrl]] : []
    }),
  )

  const keepPreview = useCallback(() => clearTimeout(closeTimer.current), [])
  const previewPlace = useCallback((placeId: string | null) => {
    clearTimeout(closeTimer.current)
    if (placeId) setPreviewPlaceId(placeId)
    else closeTimer.current = setTimeout(() => setPreviewPlaceId(null), PREVIEW_CLOSE_DELAY_MS)
  }, [])
  const pinPlace = useCallback((placeId: string) => {
    clearTimeout(closeTimer.current)
    setPreviewPlaceId(null)
    setPinnedPlaceId(placeId)
  }, [])
  const closePhoto = useCallback(() => setOpenPhoto(null), [])
  useEffect(() => () => clearTimeout(closeTimer.current), [])

  return (
    <div className="flex h-dvh flex-col md:flex-row">
      <Sidebar trip={trip} />
      <main className="relative min-h-0 flex-1">
        <MapView
          route={trip.route}
          start={trip.start}
          end={trip.end}
          places={trip.places}
          chatPlaces={trip.chatPlaces}
          pendingPoint={trip.pendingPoint}
          pickMode={trip.pickMode}
          onMapClick={trip.handleMapClick}
          onSelectPlace={pinPlace}
          onPreviewPlace={previewPlace}
          thumbnails={thumbnails}
        />
        {activePlace && (
          <PlaceCard
            key={activePlace.id}
            place={activePlace}
            media={media.states.get(activePlace.id)}
            isPinned={activePlace.id === pinnedPlaceId}
            onClose={() => setPinnedPlaceId(null)}
            onOpenPhoto={setOpenPhoto}
            onRetryMedia={() => media.retry(activePlace.id)}
            onPointerEnter={keepPreview}
            onPointerLeave={() => previewPlace(null)}
          />
        )}
        {trip.route && <AlongTheWay visits={visits} media={media.states} onSelectPlace={pinPlace} onOpenPhoto={setOpenPhoto} />}
      </main>
      {openPhoto && <PhotoViewer photo={openPhoto} onClose={closePhoto} />}
    </div>
  )
}
