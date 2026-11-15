import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { getErrorMessage } from '../lib/errors'
import { nextMediaRequests, type MediaState } from '../lib/media'

export type MediaStates = ReadonlyMap<string, MediaState>

const LOADING: MediaState = { status: 'loading' }

/**
 * One media store keyed by canonical Place UUID, shared by markers, the place card and the strip.
 * Requests each place once (selected first, two at a time); a failure stays local to that place until retried.
 * A place with no entry yet is shown as loading.
 */
export function usePlaceMedia(wanted: string[], selected: string | null) {
  const [states, setStates] = useState<MediaStates>(new Map())
  const inFlight = useRef<ReadonlySet<string>>(new Set())
  const wantedKey = wanted.join('|')

  useEffect(() => {
    const pending = new Map([...states, ...[...inFlight.current].map((id): [string, MediaState] => [id, LOADING])])
    const ids = nextMediaRequests(wantedKey ? wantedKey.split('|') : [], selected, pending)
    if (ids.length === 0) return
    inFlight.current = new Set([...inFlight.current, ...ids])
    const settle = (id: string, state: MediaState) => {
      inFlight.current = new Set([...inFlight.current].filter((key) => key !== id))
      setStates((prev) => new Map([...prev, [id, state]]))
    }
    for (const id of ids) {
      api
        .getPlaceMedia(id)
        .then((media) => settle(id, { status: 'ready', media }))
        .catch((error: unknown) => settle(id, { status: 'error', message: getErrorMessage(error) }))
    }
  }, [wantedKey, selected, states])

  /** Repeat only this place's media GET; never the chat or route request. */
  const retry = useCallback((id: string) => {
    setStates((prev) => new Map([...prev].filter(([key]) => key !== id)))
  }, [])

  return { states, retry }
}
