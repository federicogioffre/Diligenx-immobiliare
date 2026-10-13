'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { api, CreditLedger, UserRead } from '@/lib/api'
import { creditReason, formatCredits } from '@/lib/credits'

/** Account page: balance and the latest movements of the ledger. */
export default function CreditsSection({ user }: { user: UserRead }) {
  const [ledger, setLedger] = useState<CreditLedger | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    api.users.credits().then(setLedger).catch(() => setFailed(true))
  }, [])

  if (!user.credits_enabled && !user.is_admin) return null
  const balance = ledger?.balance ?? user.credit_balance

  return (
    <section id="crediti" className="bg-surface rounded-2xl border border-slate-200 shadow-sm p-6 mb-6 scroll-mt-24">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Crediti</h2>
          <p className="text-sm text-slate-500 mt-1">
            1 credito = 1 pagina analizzata. Una domanda sui documenti e la rigenerazione del report
            costano pochi crediti; un’analisi interrotta si riprende gratis.
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-2xl font-semibold text-slate-900 tabular-nums">
            {user.credits_unlimited ? '∞' : balance.toLocaleString('it-IT')}
          </p>
          <p className="text-xs text-slate-500">{user.credits_unlimited ? 'illimitati' : 'disponibili'}</p>
        </div>
      </div>

      {user.is_admin && (
        <Link href="/admin/credits" className="inline-block text-sm font-medium text-blue-600 hover:text-blue-700 mb-4">
          Assegna crediti agli utenti →
        </Link>
      )}

      {failed && <p className="text-sm text-slate-500">Movimenti non disponibili al momento.</p>}
      {ledger && ledger.transactions.length === 0 && (
        <p className="text-sm text-slate-500">Nessun movimento.</p>
      )}
      {ledger && ledger.transactions.length > 0 && (
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="font-medium px-2 py-1.5">Data</th>
                <th className="font-medium px-2 py-1.5">Movimento</th>
                <th className="font-medium px-2 py-1.5 text-right">Crediti</th>
                <th className="font-medium px-2 py-1.5 text-right">Saldo</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {ledger.transactions.map((t, i) => (
                <tr key={i}>
                  <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap">
                    {t.created_at ? new Date(t.created_at).toLocaleDateString('it-IT') : '—'}
                  </td>
                  <td className="px-2 py-1.5 text-slate-700">
                    {creditReason(t)}
                    {t.deal_id !== null && (
                      <Link href={`/deals/${t.deal_id}`} className="text-slate-400 hover:text-blue-600"> · deal {t.deal_id}</Link>
                    )}
                  </td>
                  <td className={`px-2 py-1.5 text-right tabular-nums font-medium ${t.delta < 0 ? 'text-slate-700' : 'text-emerald-600'}`}>
                    {t.delta > 0 ? '+' : ''}{t.delta.toLocaleString('it-IT')}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-500">{t.balance_after.toLocaleString('it-IT')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!user.credits_unlimited && balance <= 0 && (
        <p className="text-sm text-red-600 mt-4">
          Hai esaurito i crediti ({formatCredits(balance)}). Contatta l’amministratore per una ricarica.
        </p>
      )}
    </section>
  )
}
