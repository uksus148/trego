import { useRef, useState } from 'react'
import { api } from '../api/client'
import { StaleResultError } from '../lib/apiContract'
import { mergePlaces } from '../lib/places'
import type { ChatMessage, LatLon, Place, Route } from '../types'
import { useAsyncTask } from './useAsyncTask'

export type PickMode = 'start' | 'end' | 'place' | null

const message = (role: ChatMessage['role'], text: string): ChatMessage => ({ id: crypto.randomUUID(), role, text })

export function useTrip() {
  const [sessionId] = useState(() => crypto.randomUUID())
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [route, setRoute] = useState<Route | null>(null)
  const [showingPreviousRoute, setShowingPreviousRoute] = useState(false)
  const [start, setStart] = useState<LatLon | null>(null)
  const [end, setEnd] = useState<LatLon | null>(null)
  const [places, setPlaces] = useState<Place[]>([])
  // Places returned with a chat route: start, stops and finish. The route itself lists only the stops.
  const [chatPlaces, setChatPlaces] = useState<Place[]>([])
  const [pickMode, setPickMode] = useState<PickMode>(null)
  const [pendingPoint, setPendingPoint] = useState<LatLon | null>(null)
  const task = useAsyncTask()
  const inputRevision = useRef(0)
  const markInputsChanged = () => { inputRevision.current++ }

  const sendMessage = (text: string) => {
    return task.run(async () => {
      setMessages((prev) => [...prev, message('user', text)])
      markInputsChanged()
      const requestRevision = inputRevision.current
      setShowingPreviousRoute(route !== null)
      const res = await api.chat({ sessionId, message: text })
      if (requestRevision !== inputRevision.current) throw new StaleResultError()
      // Do not publish a ready answer until its referenced route has been fetched and validated.
      const nextRoute = res.routeId ? await api.getRoute(res.routeId) : null
      if (requestRevision !== inputRevision.current) throw new StaleResultError()
      setMessages((prev) => [...prev, message('assistant', res.reply)])
      if (res.routeId) {
        setRoute(nextRoute)
        setChatPlaces(res.places)
        setPlaces([])
        setShowingPreviousRoute(false)
        // The chat route replaces any start/finish picked on the map earlier, so stale points can't win.
        setStart(null)
        setEnd(null)
        return
      }
      setChatPlaces([])
      // Places without a route (allowed by the contract): show them and drop the route that answered an earlier question.
      setRoute(null)
      setShowingPreviousRoute(false)
      setPlaces((prev) => mergePlaces(prev, res.places))
    })
  }

  const handleMapClick = (point: LatLon) => {
    if (pickMode === 'start') { markInputsChanged(); setStart(point); setShowingPreviousRoute(route !== null) }
    if (pickMode === 'end') { markInputsChanged(); setEnd(point); setShowingPreviousRoute(route !== null) }
    if (pickMode === 'place') { markInputsChanged(); setPendingPoint(point); setShowingPreviousRoute(route !== null) }
    setPickMode(null)
  }

  const savePlace = (name: string, tag: string) => {
    if (!pendingPoint) return Promise.resolve()
    return task.run(async () => {
      const requestRevision = inputRevision.current
      const place = await api.addPlace({ name, tags: [tag], ...pendingPoint })
      if (requestRevision !== inputRevision.current) throw new StaleResultError()
      setPlaces((prev) => [...prev, place])
      setShowingPreviousRoute(route !== null)
      setPendingPoint(null)
    })
  }

  const removePlace = (id: string) => {
    markInputsChanged()
    setPlaces((prev) => prev.filter((p) => p.id !== id))
    setShowingPreviousRoute(route !== null)
  }

  const changeStart = (point: LatLon | null) => { markInputsChanged(); setStart(point); setShowingPreviousRoute(route !== null) }
  const changeEnd = (point: LatLon | null) => { markInputsChanged(); setEnd(point); setShowingPreviousRoute(route !== null) }
  const cancelPendingPlace = () => { markInputsChanged(); setPendingPoint(null) }

  const buildRoute = () => {
    if (!start || !end) return Promise.resolve()
    return task.run(async () => {
      const requestRevision = inputRevision.current
      setShowingPreviousRoute(route !== null)
      const nextRoute = await api.createRoute({ start, end, placeIds: places.map((p) => p.id), preferences: [] })
      if (requestRevision !== inputRevision.current) throw new StaleResultError()
      setRoute(nextRoute)
      setChatPlaces([])
      setShowingPreviousRoute(false)
    })
  }

  return {
    messages, route, showingPreviousRoute, start, end, places, chatPlaces, pickMode, pendingPoint,
    busy: task.busy, error: task.error, clearError: task.clearError,
    sendMessage, handleMapClick, savePlace, removePlace, buildRoute,
    setPickMode, setStart: changeStart, setEnd: changeEnd, cancelPendingPlace,
  }
}

export type Trip = ReturnType<typeof useTrip>
