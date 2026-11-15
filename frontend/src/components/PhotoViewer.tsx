import { useEffect, useRef } from 'react'
import { safeUrl } from '../lib/errors'
import type { LandmarkPhoto } from '../types'

interface PhotoViewerProps {
  photo: LandmarkPhoto
  onClose: () => void
}

const LINK = 'font-medium text-moss hover:underline'

/** Full-size photo with title, caption and credits. Escape closes it and focus returns to whatever opened it. */
export function PhotoViewer({ photo, onClose }: PhotoViewerProps) {
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      opener?.focus()
    }
  }, [onClose])

  const source = safeUrl(photo.sourceUrl)
  const license = safeUrl(photo.licenseUrl)
  const association = photo.associationSourceUrl !== photo.sourceUrl ? safeUrl(photo.associationSourceUrl) : undefined
  const captionSource = photo.description && safeUrl(photo.description.sourceUrl)

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-ink/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={photo.title}
      onClick={onClose}
    >
      <figure className="flex max-h-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-paper shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <img src={photo.url} alt={photo.title} className="max-h-[65vh] min-h-0 w-full bg-ink object-contain" />
        <figcaption className="space-y-2 px-5 py-4 text-sm">
          <div className="flex items-start justify-between gap-4">
            <h2 className="font-display text-base font-semibold">{photo.title}</h2>
            <button ref={closeRef} type="button" onClick={onClose} className="shrink-0 font-medium text-ink hover:underline">
              Close
            </button>
          </div>
          {photo.description ? (
            <p>
              {photo.description.text}{' '}
              {captionSource && (
                <a href={captionSource} target="_blank" rel="noopener noreferrer" className={`text-xs ${LINK}`}>
                  Caption source ↗
                </a>
              )}
            </p>
          ) : (
            <p className="text-stone italic">The source provides no caption for this photo.</p>
          )}
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-stone">
            <span>© {photo.author}</span>
            {license ? (
              <a href={license} target="_blank" rel="noopener noreferrer" className={LINK}>
                {photo.license} ↗
              </a>
            ) : (
              <span>{photo.license}</span>
            )}
            {source && (
              <a href={source} target="_blank" rel="noopener noreferrer" className={LINK}>
                Image source ↗
              </a>
            )}
            {association && (
              <a href={association} target="_blank" rel="noopener noreferrer" className={LINK}>
                Why this is the place ↗
              </a>
            )}
          </p>
        </figcaption>
      </figure>
    </div>
  )
}
