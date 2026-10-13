import type { ReactNode } from 'react'

interface Props {
  /** Custom icon. Defaults to a document icon matching the app aesthetic. */
  icon?: ReactNode
  title: string
  subtitle?: string
  /** Optional CTA (typically a button). */
  action?: ReactNode
  /** Extra padding control — use `sm` for tight spaces inside cards. */
  size?: 'sm' | 'md'
}

const DEFAULT_ICON = (
  <svg
    className="w-6 h-6 text-slate-400"
    fill="none"
    viewBox="0 0 24 24"
    stroke="currentColor"
    strokeWidth={1.5}
    aria-hidden
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
    />
  </svg>
)

/**
 * Reusable "nothing here yet" block.
 *
 *   <EmptyState title="Nessun deal ancora"
 *               subtitle="Crea il tuo primo deal per iniziare l'analisi" />
 */
export default function EmptyState({ icon, title, subtitle, action, size = 'md' }: Props) {
  const pad = size === 'sm' ? 'py-10' : 'py-16'
  return (
    <div className={`relative overflow-hidden text-center ${pad} bg-surface rounded-2xl border border-slate-200 border-dashed`}>
      <div className="absolute inset-0 bg-grid-light mask-radial opacity-70 pointer-events-none" aria-hidden />
      <div className="relative inline-flex items-center justify-center w-12 h-12 bg-surface rounded-xl mb-4 shadow-md ring-1 ring-slate-200">
        {icon ?? DEFAULT_ICON}
      </div>
      <p className="relative text-slate-800 font-semibold mb-1">{title}</p>
      {subtitle && <p className="relative text-slate-500 text-sm">{subtitle}</p>}
      {action && <div className="relative mt-4">{action}</div>}
    </div>
  )
}
