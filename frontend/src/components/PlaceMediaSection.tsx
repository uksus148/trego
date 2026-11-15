import { safeUrl } from '../lib/errors'
import type { MediaState } from '../lib/media'
import type { LandmarkPhoto } from '../types'

interface PlaceMediaSectionProps {
  state: MediaState | undefined
  onOpenPhoto: (photo: LandmarkPhoto) => void
  onRetry: () => void
}

/** Photo and sourced description for a place card. Absent photos leave no image area; errors stay local. */
export function PlaceMediaSection({ state, onOpenPhoto, onRetry }: PlaceMediaSectionProps) {
  if (!state || state.status === 'loading') {
    return <div className="mt-3 h-36 animate-pulse rounded-xl bg-line/70" aria-label="Loading photo" role="status" />
  }
  if (state.status === 'error') {
    return (
      <p className="mt-3 flex items-center justify-between gap-2 rounded-xl bg-line/50 px-3 py-2 text-xs text-stone" role="status">
        Photo unavailable right now.
        <button type="button" onClick={onRetry} className="font-medium text-moss hover:underline">
          Retry
        </button>
      </p>
    )
  }
  const { placeDescription, photos } = state.media
  const photo = photos[0]
  const descriptionLink = placeDescription && safeUrl(placeDescription.sourceUrl)
  return (
    <>
      {photo && (
        <button
          type="button"
          onClick={() => onOpenPhoto(photo)}
          className="group mt-3 block w-full overflow-hidden rounded-xl bg-line text-left"
          aria-label={`Open photo: ${photo.title}`}
        >
          <img src={photo.thumbUrl} alt={photo.title} loading="lazy" className="h-36 w-full object-cover transition group-hover:scale-[1.03]" />
          <span className="block truncate bg-ink/80 px-3 py-1 text-[11px] text-paper">
            © {photo.author} · {photo.license}
          </span>
        </button>
      )}
      {placeDescription && (
        <p className="mt-3 text-sm leading-snug">
          {placeDescription.text}{' '}
          {descriptionLink && (
            <a href={descriptionLink} target="_blank" rel="noopener noreferrer" className="text-xs font-medium text-moss hover:underline">
              Description source ↗
            </a>
          )}
        </p>
      )}
    </>
  )
}
