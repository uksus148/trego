import { isDirty, isValidDraft, rawEndpoint } from '../lib/routeEditing'
import type { Draft } from '../lib/routeEditing'
import type { Place } from '../types'
import type { PickMode, Trip } from '../hooks/useTrip'

const formatPoint = (point: { lat: number; lon: number }) => `${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`

interface RouteEditorPanelProps { trip: Trip }

export function RouteEditorPanel({ trip }: RouteEditorPanelProps) {
  const editor = trip.editor
  if (editor.status === 'closed') return null

  if (editor.status === 'loading') {
    return (
      <section className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4" aria-labelledby="route-editor-title">
        <h2 id="route-editor-title" className="font-display text-lg font-semibold">Edit route</h2>
        {editor.error
          ? <p role="alert" className="rounded-xl bg-trail/10 p-3 text-sm text-trail">Could not load saved route details: {editor.error}</p>
          : <p role="status" className="text-sm text-stone">Loading saved route details…</p>}
        <div className="flex gap-2">
          {editor.error && <button type="button" onClick={() => void trip.retryEditorLoad()} disabled={trip.busy} className="rounded-lg bg-trail px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Retry loading</button>}
          <button type="button" onClick={trip.cancelEditor} disabled={trip.busy} className="rounded-lg px-4 py-2 text-sm ring-1 ring-line disabled:opacity-50">Cancel</button>
        </div>
      </section>
    )
  }

  const draft = editor.draft
  const dirty = isDirty(editor.initial, draft)
  const valid = isValidDraft(draft)
  return (
    <section className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4" aria-labelledby="route-editor-title">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="route-editor-title" className="font-display text-lg font-semibold">Edit route</h2>
          <p className="text-sm text-stone">The map and distance still show the saved route until you rebuild.</p>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-1 text-xs ${dirty ? 'bg-amber-100 text-amber-900' : 'bg-moss/10 text-moss'}`}>
          {dirty ? 'Unsaved edits' : 'Saved route'}
        </span>
      </div>

      {editor.error && <p role="alert" className={`rounded-xl p-3 text-sm ${editor.uncertain ? 'bg-amber-100 text-amber-950' : 'bg-trail/10 text-trail'}`}>{editor.error}</p>}
      {editor.metadataError && (
        <div role="status" className="space-y-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-950">
          <p>Route saved, but its saved details could not be confirmed: {editor.metadataError}</p>
          <button type="button" onClick={() => void trip.retryCommittedContext()} disabled={trip.busy} className="font-medium underline disabled:opacity-50">Retry loading details</button>
        </div>
      )}

      <EndpointEditor side="start" endpoint={draft.start} places={trip.availablePlaces} trip={trip} />
      <ol className="space-y-2" aria-label="Intermediate visits">
        {draft.rows.map((row, index) => (
          <li key={row.key} className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 ring-1 ring-line">
            <span className="grid size-6 shrink-0 place-items-center rounded-full bg-trail text-xs font-semibold text-white">{index + 1}</span>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{row.place.name}</span>
            <button type="button" aria-label={`Move ${row.place.name} up`} onClick={() => trip.moveEditorVisit(row.key, -1)} disabled={trip.busy || index === 0} className="rounded px-2 py-1 text-sm ring-1 ring-line disabled:opacity-35">↑</button>
            <button type="button" aria-label={`Move ${row.place.name} down`} onClick={() => trip.moveEditorVisit(row.key, 1)} disabled={trip.busy || index === draft.rows.length - 1} className="rounded px-2 py-1 text-sm ring-1 ring-line disabled:opacity-35">↓</button>
            <button type="button" aria-label={`Remove ${row.place.name}`} onClick={() => trip.removeEditorVisit(row.key)} disabled={trip.busy} className="rounded px-2 py-1 text-lg leading-none text-stone hover:text-trail disabled:opacity-35">×</button>
          </li>
        ))}
        {draft.rows.length === 0 && <li className="rounded-xl border border-dashed border-line p-3 text-sm text-stone">No intermediate visits. Rebuild to create a direct hike.</li>}
      </ol>
      <EndpointEditor side="end" endpoint={draft.end} places={trip.availablePlaces} trip={trip} />

      <button type="button" onClick={trip.swapEditorEndpoints} disabled={trip.busy} className="w-full rounded-lg px-3 py-2 text-sm font-medium ring-1 ring-line disabled:opacity-50">Swap start and finish</button>
      <p className="text-xs text-stone">Interests are kept as descriptions and do not change the hiking route: {draft.preferences.length ? draft.preferences.join(', ') : 'none'}</p>
      {!valid && <p role="alert" className="text-sm text-trail">Check the endpoint coordinates and place selections before rebuilding.</p>}
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={trip.cancelEditor} disabled={trip.busy} className="rounded-xl px-3 py-3 text-sm font-medium ring-1 ring-line disabled:opacity-50">Cancel</button>
        <button type="button" onClick={() => void trip.rebuildRoute()} disabled={!trip.editorCanBuild || trip.busy} className="rounded-xl bg-trail px-3 py-3 text-sm font-medium text-white disabled:opacity-40">
          {trip.rebuilding ? 'Rebuilding…' : 'Rebuild route'}
        </button>
      </div>
    </section>
  )
}

interface EndpointEditorProps {
  side: 'start' | 'end'
  endpoint: Draft['start']
  places: Place[]
  trip: Trip
}
function EndpointEditor({ side, endpoint, places, trip }: EndpointEditorProps) {
  const mode: PickMode = side === 'start' ? 'edit-start' : 'edit-end'
  const picking = trip.pickMode === mode
  return (
    <div className="space-y-2 rounded-xl bg-white p-3 ring-1 ring-line">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{side === 'start' ? 'Start (A)' : 'Finish (B)'}</h3>
          <p className="text-xs text-stone">{endpoint.place?.name ?? `Unbound point · ${formatPoint(endpoint)}`}</p>
        </div>
        <button type="button" onClick={() => trip.setPickMode(picking ? null : mode)} disabled={trip.busy} className={`rounded-lg px-2.5 py-2 text-xs ring-1 disabled:opacity-50 ${picking ? 'bg-moss text-white ring-moss' : 'ring-line'}`}>
          {picking ? 'Click map…' : 'Choose on map'}
        </button>
      </div>
      <label className="block text-xs text-stone">
        Select a saved place
        <select
          aria-label={side === 'start' ? 'Start place' : 'Finish place'}
          value={endpoint.place?.id ?? ''}
          disabled={trip.busy}
          onChange={(event) => {
            const place = places.find((candidate) => candidate.id === event.target.value)
            trip.replaceEditorEndpoint(side, place
              ? { lat: place.lat, lon: place.lon, place }
              : rawEndpoint(endpoint))
          }}
          className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink disabled:opacity-50"
        >
          <option value="">Unbound point · {formatPoint(endpoint)}</option>
          {places.map((place) => <option key={place.id} value={place.id}>{place.name}</option>)}
        </select>
      </label>
    </div>
  )
}
