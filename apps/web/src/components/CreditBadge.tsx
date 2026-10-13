'use client'

import Link from 'next/link'
import type { UserRead } from '@/lib/api'
import { formatCredits } from '@/lib/credits'

/** The balance in the nav bar; nothing while credits are off. */
export default function CreditBadge({ user }: { user: UserRead | null }) {
  if (!user?.credits_enabled) return null
  const label = user.credits_unlimited ? 'Crediti illimitati' : formatCredits(user.credit_balance)
  const empty = !user.credits_unlimited && user.credit_balance <= 0
  return (
    <Link
      href="/account#crediti"
      title="Saldo crediti: 1 credito = 1 pagina analizzata"
      className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-lg ring-1 ring-inset transition-colors ${
        empty
          ? 'text-red-700 bg-red-50 ring-red-200 hover:bg-red-100'
          : 'text-slate-600 bg-slate-100/80 ring-slate-200/60 hover:text-slate-900'
      }`}
    >
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden>
        <circle cx="12" cy="12" r="8" />
        <path strokeLinecap="round" d="M12 8v8M9.5 10.5h4a1.5 1.5 0 010 3h-3a1.5 1.5 0 000 3h4" />
      </svg>
      {label}
    </Link>
  )
}
