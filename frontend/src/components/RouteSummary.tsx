import { formatAscent, formatDistance, formatDuration } from '../lib/format'
import type { Route } from '../types'

interface RouteSummaryProps {
  route: Route
  showingPrevious?: boolean
}

export function RouteSummary({ route, showingPrevious = false }: RouteSummaryProps) {
  const stats = [
    { label: 'Distance', value: formatDistance(route.distanceKm) },
    { label: 'Ascent', value: formatAscent(route.ascentM) },
    { label: 'Walking', value: formatDuration(route.durationMin) },
  ]
  return (
    <div className="border-t border-line">
      {showingPrevious && <p role="status" className="px-5 pt-3 text-sm text-trail">Showing a previous route. The latest request or point changes have not been verified.</p>}
      <dl className="grid grid-cols-3 gap-2 px-5 py-3">
      {stats.map((s) => (
        <div key={s.label}>
          <dt className="text-xs uppercase tracking-wide text-stone">{s.label}</dt>
          <dd className="font-display text-lg font-semibold">{s.value}</dd>
        </div>
      ))}
      </dl>
    </div>
  )
}
