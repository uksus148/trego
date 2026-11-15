import { useEffect, useRef, useState } from 'react'
import { api, USE_MOCKS } from '../api/client'
import { ApiError, UncertainRouteSaveError } from '../api/realApi'
import { getErrorMessage } from '../lib/errors'
import { mergePlaces } from '../lib/places'
import { canOpenRouteEditor, fromContext, isDirty, isValidDraft, parseEditingContext, parseRoute, rawEndpoint, toRequest, type Draft } from '../lib/routeEditing'
import type { ChatMessage, LatLon, Place, Route, RouteEditingContext } from '../types'

export type PickMode = 'start' | 'end' | 'place' | 'edit-start' | 'edit-end' | null
export const ROUTE_EDITOR_ENABLED = USE_MOCKS || import.meta.env.VITE_ENABLE_ROUTE_EDITOR === 'true'

type EditorState =
  | { status: 'closed' }
  | { status: 'loading'; routeId: string; error?: string }
  | { status: 'ready'; routeId: string; initial: Draft; draft: Draft; error?: string; uncertain: boolean; metadataError?: string }

const message = (role: ChatMessage['role'], text: string): ChatMessage => ({ id: crypto.randomUUID(), role, text })
function routeError(error: unknown): string {
  if (error instanceof UncertainRouteSaveError) return error.message
  if (error instanceof ApiError) {
    const messages: Record<string, string> = {
      invalid_request: 'Some route details are invalid. Check the selected points and places.',
      route_not_found: 'The source route is no longer available.',
      unknown_place: 'A selected place is no longer available. Choose it again before rebuilding.',
      no_hiking_route: 'No verified walking path connects these points with the current options. Choose different points or stops.',
      waypoint_not_routable: 'A point cannot be matched to the available walking network. Inspect or choose another point.',
      routing_provider_error: 'The routing service could not complete the request. Your current route and edits are still available.',
      storage_unavailable: 'Route storage is unavailable. Your current route and edits are still available.',
      cache_unavailable: 'Route cache is unavailable. Your current route and edits are still available.',
      routing_timeout: 'The routing request timed out. Your current route and edits are still available.',
    }
    return messages[error.code ?? ''] ?? error.message
  }
  return getErrorMessage(error)
}
const readStoredId = (): string | null => {
  try { return window.sessionStorage.getItem('trego.activeRouteId') } catch { return null }
}
const storeId = (id: string | null) => {
  try {
    if (id) window.sessionStorage.setItem('trego.activeRouteId', id)
    else window.sessionStorage.removeItem('trego.activeRouteId')
  } catch { /* Best-effort convenience only. */ }
}

export function useTrip() {
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
  const sessionRef = useRef(sessionId)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [history, setHistory] = useState<ChatMessage[][]>([])
  const [route, setRoute] = useState<Route | null>(null)
  const [showingPreviousRoute, setShowingPreviousRoute] = useState(false)
  const activeRouteId = useRef<string | null>(null)
  const [committedContext, setCommittedContext] = useState<RouteEditingContext | null>(null)
  const [start, setStart] = useState<LatLon | null>(null)
  const [end, setEnd] = useState<LatLon | null>(null)
  const [places, setPlaces] = useState<Place[]>([])
  const [chatPlaces, setChatPlaces] = useState<Place[]>([])
  const [pickMode, setPickModeState] = useState<PickMode>(null)
  const [pendingPoint, setPendingPoint] = useState<LatLon | null>(null)
  const [editor, setEditor] = useState<EditorState>({ status: 'closed' })
  const [busy, setBusy] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [restoreLoading, setRestoreLoading] = useState(() => readStoredId() !== null)
  const [metadataError, setMetadataError] = useState<string | null>(null)
  const lock = useRef<number | null>(null)
  const sequence = useRef(0)
  const generation = useRef(0)
  const editorGeneration = useRef(0)
  const editorLoad = useRef<number | null>(null)
  const mounted = useRef(false)

  const acquire = () => {
    if (lock.current !== null) return null
    const token = ++sequence.current
    lock.current = token
    generation.current++
    setRestoreLoading(false)
    setBusy(true)
    setError(null)
    return token
  }
  const release = (token: number) => {
    if (lock.current === token) { lock.current = null; setBusy(false) }
  }
  const activate = (next: Route | null) => {
    generation.current++
    editorGeneration.current++
    editorLoad.current = null
    activeRouteId.current = next?.id ?? null
    setRoute(next)
    setShowingPreviousRoute(false)
    setEditor({ status: 'closed' })
    setPickModeState(null)
    setCommittedContext(null)
    setMetadataError(null)
    storeId(next?.id ?? null)
  }
  const closeEditor = () => {
    editorGeneration.current++
    editorLoad.current = null
    setEditor({ status: 'closed' })
    setPickModeState(null)
  }
  const leaveEditor = () => {
    if (editor.status === 'closed') return true
    const dirty = editor.status === 'ready' && isDirty(editor.initial, editor.draft)
    if (dirty && typeof window !== 'undefined' && !window.confirm('Discard the unsaved route edits and continue?')) return false
    closeEditor()
    return true
  }

  useEffect(() => {
    mounted.current = true
    let alive = true
    const savedId = readStoredId()
    if (savedId) {
      const expectedGeneration = generation.current
      void Promise.allSettled([
        api.getRoute(savedId),
        ROUTE_EDITOR_ENABLED ? api.getRouteEditingContext(savedId) : Promise.resolve(null),
      ]).then(([routeResult, contextResult]) => {
        if (!alive || !mounted.current || generation.current !== expectedGeneration || activeRouteId.current !== null) return
        if (routeResult.status === 'fulfilled') {
          activeRouteId.current = routeResult.value.id
          setRoute(routeResult.value)
          if (contextResult.status === 'fulfilled' && contextResult.value?.routeId === routeResult.value.id) {
            setCommittedContext(contextResult.value)
          } else if (ROUTE_EDITOR_ENABLED) {
            setMetadataError('Saved route details could not be verified. Retry loading route details before editing.')
          }
        } else {
          setError(getErrorMessage(routeResult.reason))
          if (contextResult.status === 'rejected') setMetadataError(getErrorMessage(contextResult.reason))
        }
        setRestoreLoading(false)
      })
    }
    return () => {
      alive = false
      mounted.current = false
    }
  }, [])

  const refreshContext = async (routeId: string, submitted: Draft, rowKeys: string[]) => {
    try {
      const context = parseEditingContext(await api.getRouteEditingContext(routeId), routeId)
      const refreshed = fromContext(context)
      if (JSON.stringify(toRequest(refreshed)) !== JSON.stringify(toRequest(submitted))) throw new Error('Saved route details do not match the submitted edits.')
      refreshed.rows = refreshed.rows.map((row, index) => ({ ...row, key: rowKeys[index] ?? row.key }))
      if (!mounted.current || activeRouteId.current !== routeId) return
      setCommittedContext(context)
      setMetadataError(null)
      setEditor((current) => {
        if (current.status !== 'ready' || current.routeId !== routeId) return current
        return isDirty(current.initial, current.draft)
          ? { ...current, metadataError: undefined }
          : { status: 'ready', routeId, initial: refreshed, draft: refreshed, uncertain: false }
      })
    } catch (cause) {
      if (!mounted.current || activeRouteId.current !== routeId) return
      const detail = getErrorMessage(cause)
      setMetadataError(detail)
      setEditor((current) => current.status === 'ready' && current.routeId === routeId ? { ...current, metadataError: detail } : current)
    }
  }

  const retryCommittedContext = async () => {
    if (editor.status !== 'ready' || busy || lock.current !== null) return
    setMetadataError(null)
    setEditor({ ...editor, metadataError: 'Refreshing saved route details…' })
    await refreshContext(editor.routeId, editor.initial, editor.initial.rows.map((row) => row.key))
  }

  const loadEditor = async (routeId: string) => {
    if (editorLoad.current !== null) return
    const requestGeneration = ++editorGeneration.current
    editorLoad.current = requestGeneration
    generation.current++
    setRestoreLoading(false)
    setPickModeState(null)
    setEditor({ status: 'loading', routeId })
    try {
      const context = parseEditingContext(await api.getRouteEditingContext(routeId), routeId)
      if (!mounted.current || editorGeneration.current !== requestGeneration || activeRouteId.current !== routeId) return
      const draft = fromContext(context)
      setCommittedContext(context)
      setMetadataError(null)
      setEditor({ status: 'ready', routeId, initial: draft, draft, uncertain: false })
    } catch (cause) {
      if (mounted.current && editorGeneration.current === requestGeneration && activeRouteId.current === routeId) {
        setEditor({ status: 'loading', routeId, error: getErrorMessage(cause) })
      }
    } finally {
      if (editorLoad.current === requestGeneration) editorLoad.current = null
    }
  }
  const openEditor = () => {
    const routeId = activeRouteId.current
    if (routeId === null || !canOpenRouteEditor({
      enabled: ROUTE_EDITOR_ENABLED, status: editor.status, requestPending: editorLoad.current !== null,
      tripBusy: busy || lock.current !== null, activeRouteId: routeId,
    })) return Promise.resolve()
    return loadEditor(routeId)
  }
  const retryEditorLoad = () => editor.status === 'loading' && editor.error ? loadEditor(editor.routeId) : Promise.resolve()
  const cancelEditor = () => {
    if (busy || lock.current !== null) return
    const dirty = editor.status === 'ready' && isDirty(editor.initial, editor.draft)
    if (dirty && typeof window !== 'undefined' && !window.confirm('Discard the unsaved route edits?')) return
    closeEditor()
  }
  const updateDraft = (update: (draft: Draft) => Draft) => {
    if (busy || lock.current !== null) return
    setEditor((current) => current.status === 'ready' ? { ...current, draft: update(current.draft), error: undefined } : current)
  }

  const sendMessage = (text: string) => {
    const value = text.trim()
    if (!value || busy || lock.current !== null || !leaveEditor()) return Promise.resolve()
    const token = acquire()
    if (token === null) return Promise.resolve()
    setMessages((previous) => [...previous, message('user', value)])
    setShowingPreviousRoute(route !== null)
    const requestSessionId = sessionRef.current
    return (async () => {
      try {
        const response = await api.chat({ sessionId: requestSessionId, message: value })
        const saved = response.routeId ? await api.getRoute(response.routeId) : null
        setMessages((previous) => [...previous, message('assistant', response.reply)])
        if (saved) {
          activate(saved)
          setChatPlaces(response.places)
          setPlaces([])
          setStart(null); setEnd(null)
        } else {
          activate(null)
          setChatPlaces([])
          setPlaces((previous) => mergePlaces(previous, response.places))
        }
      } catch (cause) { setError(getErrorMessage(cause)) }
      finally { release(token) }
    })()
  }

  const handleMapClick = (point: LatLon) => {
    if (busy || lock.current !== null) return
    if (pickMode === 'edit-start') updateDraft((draft) => ({ ...draft, start: rawEndpoint(point) }))
    else if (pickMode === 'edit-end') updateDraft((draft) => ({ ...draft, end: rawEndpoint(point) }))
    else if (pickMode === 'start') { setStart(point); setShowingPreviousRoute(route !== null) }
    else if (pickMode === 'end') { setEnd(point); setShowingPreviousRoute(route !== null) }
    else if (pickMode === 'place') {
      setPendingPoint(point)
      setShowingPreviousRoute(route !== null)
    }
    setPickModeState(null)
  }
  const setPickMode = (mode: PickMode) => {
    if (busy || lock.current !== null) return
    if (editor.status === 'ready' && mode !== 'edit-start' && mode !== 'edit-end' && mode !== null) return
    if (editor.status !== 'ready' && (mode === 'edit-start' || mode === 'edit-end')) return
    setPickModeState(mode)
  }

  const savePlace = (name: string, tag: string) => {
    if (!pendingPoint || busy || lock.current !== null || !leaveEditor()) return Promise.resolve()
    const token = acquire(), point = pendingPoint
    if (token === null) return Promise.resolve()
    return (async () => {
      try {
        const place = await api.addPlace({ name, tags: [tag], ...point })
        setPlaces((previous) => [...previous, place])
        setPendingPoint(null)
        setShowingPreviousRoute(route !== null)
      } catch (cause) { setError(getErrorMessage(cause)) }
      finally { release(token) }
    })()
  }
  const removePlace = (id: string) => {
    if (busy || lock.current !== null || !places.some((place) => place.id === id)) return
    setPlaces((previous) => previous.filter((place) => place.id !== id))
    setShowingPreviousRoute(route !== null)
  }

  const buildRoute = () => {
    if (!start || !end || busy || lock.current !== null || !leaveEditor()) return Promise.resolve()
    const token = acquire()
    if (token === null) return Promise.resolve()
    const request = { start: { ...start }, end: { ...end }, placeIds: places.map((place) => place.id), preferences: [] as string[] }
    setShowingPreviousRoute(route !== null)
    const stopPlaces = [...places]
    return (async () => {
      try {
        const saved = parseRoute(await api.createRoute(request), request)
        activate(saved)
        setCommittedContext({ routeId: saved.id, start: { ...request.start, place: null }, end: { ...request.end, place: null }, stops: stopPlaces, preferences: [] })
        setChatPlaces([])
      } catch (cause) { setError(getErrorMessage(cause)) }
      finally { release(token) }
    })()
  }

  const moveVisit = (key: string, delta: -1 | 1) => updateDraft((draft) => {
    const from = draft.rows.findIndex((row) => row.key === key), to = from + delta
    if (from < 0 || to < 0 || to >= draft.rows.length) return draft
    const rows = [...draft.rows]
    ;[rows[from], rows[to]] = [rows[to], rows[from]]
    return { ...draft, rows }
  })
  const removeVisit = (key: string) => updateDraft((draft) => ({ ...draft, rows: draft.rows.filter((row) => row.key !== key) }))
  const replaceEndpoint = (side: 'start' | 'end', endpoint: Draft['start']) => updateDraft((draft) => ({ ...draft, [side]: endpoint }))
  const swapEndpoints = () => updateDraft((draft) => ({ ...draft, start: draft.end, end: draft.start }))

  const rebuildRoute = () => {
    const current = editor
    if (current.status !== 'ready' || busy || lock.current !== null || !isValidDraft(current.draft) || !isDirty(current.initial, current.draft)) return Promise.resolve()
    if (current.uncertain && typeof window !== 'undefined' &&
      !window.confirm('The route may have been saved. Submitting again can create another route. Submit a new route anyway?')) return Promise.resolve()
    const token = acquire()
    if (token === null) return Promise.resolve()
    setRebuilding(true)
    const sourceId = current.routeId, submitted = current.draft
    const payload = toRequest(submitted), rowKeys = submitted.rows.map((row) => row.key)
    return (async () => {
      let saved: Route | null = null
      try {
        saved = parseRoute(await api.createRoute(payload, sourceId), payload, sourceId)
        if (!mounted.current || activeRouteId.current !== sourceId) return
        generation.current++
        editorGeneration.current++
        activeRouteId.current = saved.id
        setRoute(saved)
        setShowingPreviousRoute(false)
        storeId(saved.id)
        setChatPlaces([]); setStart(null); setEnd(null); setPendingPoint(null); setPickModeState(null)
        if (messages.length) setHistory((previous) => [...previous, messages])
        setMessages([])
        const freshSession = crypto.randomUUID()
        sessionRef.current = freshSession
        setSessionId(freshSession)
        const context: RouteEditingContext = {
          routeId: saved.id, start: submitted.start, end: submitted.end,
          stops: submitted.rows.map((row) => row.place), preferences: [...submitted.preferences],
        }
        setCommittedContext(context)
        setMetadataError(null)
        setEditor({ status: 'ready', routeId: saved.id, initial: submitted, draft: submitted, uncertain: false, metadataError: 'Refreshing saved route details…' })
      } catch (cause) {
        if (activeRouteId.current === sourceId) {
          setEditor((latest) => latest.status === 'ready' && latest.routeId === sourceId
            ? { ...latest, error: routeError(cause), uncertain: cause instanceof UncertainRouteSaveError }
            : latest)
        }
      } finally {
        setRebuilding(false)
        release(token)
      }
      if (saved && activeRouteId.current === saved.id) void refreshContext(saved.id, submitted, rowKeys)
    })()
  }

  const availablePlaces = [...new Map([
    ...places, ...chatPlaces, ...(route?.places ?? []), ...(committedContext?.stops ?? []),
    ...(committedContext?.start.place ? [committedContext.start.place] : []),
    ...(committedContext?.end.place ? [committedContext.end.place] : []),
  ].map((place) => [place.id, place])).values()]
  const editorCanBuild = editor.status === 'ready' && isValidDraft(editor.draft) && isDirty(editor.initial, editor.draft)

  return {
    sessionId, messages, history, route, showingPreviousRoute, start, end, places, chatPlaces, pickMode, pendingPoint,
    committedContext, availablePlaces, editor, editorCanBuild, editorEnabled: ROUTE_EDITOR_ENABLED,
    restoreLoading, metadataError, busy, rebuilding, error, clearError: () => setError(null),
    sendMessage, handleMapClick, savePlace, removePlace, buildRoute, setPickMode,
    cancelPendingPlace: () => setPendingPoint(null), openEditor, retryEditorLoad, retryCommittedContext, cancelEditor,
    moveEditorVisit: moveVisit, removeEditorVisit: removeVisit, replaceEditorEndpoint: replaceEndpoint,
    swapEditorEndpoints: swapEndpoints, rebuildRoute, updateEditorDraft: updateDraft,
  }
}
export type Trip = ReturnType<typeof useTrip>
