export type Severity = 'low' | 'medium' | 'high'

const MAP: Record<
  Severity,
  {
    label: string
    solid: string
    outlined: string
    border: string
  }
> = {
  low: {
    label: 'BASSO',
    solid: 'bg-slate-100 text-slate-600',
    outlined: 'bg-white text-slate-600 border-slate-200',
    border: 'border-l-slate-300',
  },
  medium: {
    label: 'MEDIO',
    solid: 'bg-amber-50 text-amber-700',
    outlined: 'bg-white text-amber-700 border-amber-200',
    border: 'border-l-amber-400',
  },
  high: {
    label: 'ALTO',
    solid: 'bg-orange-50 text-orange-700',
    outlined: 'bg-white text-orange-700 border-orange-200',
    border: 'border-l-orange-500',
  },
}

interface Props {
  severity: Severity
  variant?: 'solid' | 'outlined'
}

/**
 * Colored label for a red-flag Severity.
 *
 * - `solid` (default) — filled background. Used in finding lists.
 * - `outlined` — white background + colored border. Used in the risk widget
 *   where cards already have a heavy background.
 */
export default function SeverityBadge({ severity, variant = 'solid' }: Props) {
  const cfg = MAP[severity] ?? MAP.medium
  const variantCls = variant === 'outlined' ? `${cfg.outlined} border` : cfg.solid
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-bold ${variantCls}`}
    >
      {cfg.label}
    </span>
  )
}

/**
 * Returns the Tailwind class to use as a left border accent on cards
 * representing a finding of the given severity.
 *
 *   <div className={`border-l-4 ${severityLeftBorder(flag.severity)}`}>
 */
export function severityLeftBorder(severity: Severity): string {
  return (MAP[severity] ?? MAP.medium).border
}
