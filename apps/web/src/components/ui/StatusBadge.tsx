import type { DealRead } from '@/lib/api'

type Status = DealRead['status']

const MAP: Record<Status, { label: string; badge: string; dot: string }> = {
  draft:     { label: 'Bozza',       dot: 'bg-slate-400',   badge: 'bg-slate-50 text-slate-600 ring-slate-200' },
  analyzing: { label: 'Analisi',     dot: 'bg-amber-400',   badge: 'bg-amber-50 text-amber-700 ring-amber-200' },
  reviewed:  { label: 'Revisionato', dot: 'bg-emerald-500', badge: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  closed:    { label: 'Chiuso',      dot: 'bg-blue-400',    badge: 'bg-blue-50 text-blue-700 ring-blue-200' },
}

/**
 * Pill-shaped status indicator for a Deal (draft | analyzing | reviewed | closed).
 * Localized to Italian to match the rest of the UI copy.
 */
export default function StatusBadge({ status }: { status: Status }) {
  const cfg = MAP[status] ?? MAP.draft
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ring-1 ring-inset ${cfg.badge}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot} ${status === 'analyzing' ? 'animate-pulse' : ''}`} aria-hidden />
      {cfg.label}
    </span>
  )
}
