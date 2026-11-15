import { firstPhoto } from '../lib/media'
import type { MediaStates } from '../hooks/usePlaceMedia'
import type { RouteVisit } from '../lib/places'
import type { LandmarkPhoto, Place } from '../types'

interface AlongTheWayProps {
  /** Place visits in route order, repeats included, labelled like their markers. */
  visits: RouteVisit[]
  media: MediaStates
  onSelectPlace: (placeId: string) => void
  onOpenPhoto: (photo: LandmarkPhoto) => void
}

/**
 * The route's verified landmark photos in visit order — another view of the same media store as the markers,
 * not a second search. Visits without a photo are skipped rather than shown as placeholders.
 */
export function AlongTheWay({ visits, media, onSelectPlace, onOpenPhoto }: AlongTheWayProps) {
  const tiles = visits
    .map(({ place, label }, index) => ({ place, label, key: `${index}-${place.id}`, photo: firstPhoto(media.get(place.id)) }))
    .filter((tile): tile is { place: Place; label: string; key: string; photo: LandmarkPhoto } => tile.photo !== undefined)
  if (tiles.length === 0) return null
  return (
    <section className="pointer-events-none absolute inset-x-0 bottom-0 p-3 md:p-4" aria-label="What you will see along the way">
      <div className="pointer-events-auto rounded-2xl bg-paper/95 p-3 shadow-xl ring-1 ring-line backdrop-blur">
        <h2 className="mb-2 px-1 font-display text-sm font-semibold uppercase tracking-wide text-stone">What you'll see on the way</h2>
        <ol className="flex snap-x gap-3 overflow-x-auto pb-1">
          {tiles.map(({ place, label, key, photo }) => (
            <li key={key} className="w-52 shrink-0 snap-start">
              <button type="button" onClick={() => onOpenPhoto(photo)} className="group block w-full overflow-hidden rounded-xl bg-line" aria-label={`Open photo: ${photo.title}`}>
                <img src={photo.thumbUrl} alt={photo.title} loading="lazy" className="h-28 w-full object-cover transition group-hover:scale-105" />
              </button>
              <button type="button" onClick={() => onSelectPlace(place.id)} className="mt-1 block w-full truncate px-1 text-left text-sm font-medium hover:text-moss">
                <span className="text-stone">{label}</span> {place.name}
              </button>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
