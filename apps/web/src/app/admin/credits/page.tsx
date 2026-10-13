'use client'

import { FormEvent, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { AdminAccount, api, UserRead } from '@/lib/api'
import { formatCredits } from '@/lib/credits'
import ErrorAlert from '@/components/ui/ErrorAlert'
import Spinner from '@/components/ui/Spinner'

const PRESETS = [100, 300, 1000]

// Grant or remove credits for any account. The server checks the role on
// every call; this page only hides itself from accounts that lack it.
export default function AdminCreditsPage() {
  const [me, setMe] = useState<UserRead | null>(null)
  const [loading, setLoading] = useState(true)
  const [accounts, setAccounts] = useState<AdminAccount[]>([])
  const [query, setQuery] = useState('')
  const [email, setEmail] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.users.me().then(setMe).catch(() => {}).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!me?.is_admin) return
    const timer = setTimeout(() => {
      api.admin.accounts(query.trim()).then(setAccounts)
        .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Errore'))
    }, 250)
    return () => clearTimeout(timer)
  }, [me, query])

  async function submit(e: FormEvent, sign: 1 | -1) {
    e.preventDefault()
    const value = Number(amount)
    if (!email.trim() || !Number.isInteger(value) || value <= 0) {
      setError('Indica un’email e un numero intero di crediti maggiore di zero.')
      return
    }
    setSaving(true); setError('')
    try {
      const updated = await api.admin.grantCredits(email.trim(), sign * value, note.trim())
      setAccounts((list) => list.map((a) => (a.id === updated.id ? updated : a)))
      toast.success(`${updated.email}: ${formatCredits(updated.credit_balance)}`)
      setAmount(''); setNote('')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Operazione non riuscita')
    } finally { setSaving(false) }
  }

  if (loading) {
    return <div className="flex items-center gap-2 text-slate-500 text-sm py-12"><Spinner />Caricamento…</div>
  }
  if (!me?.is_admin) {
    return (
      <div className="max-w-2xl">
        <h1 className="text-xl font-semibold text-slate-900 mb-2">Accesso riservato</h1>
        <p className="text-sm text-slate-500">Questa pagina è riservata agli amministratori.</p>
      </div>
    )
  }

  const input = 'w-full rounded-lg border border-slate-200 bg-surface px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500'

  return (
    <div className="max-w-3xl">
      <h1 className="text-xl font-semibold text-slate-900 mb-1">Crediti</h1>
      <p className="text-sm text-slate-500 mb-6">
        Assegna o togli crediti a qualsiasi account. 1 credito = 1 pagina analizzata.
      </p>

      <ErrorAlert error={error} className="mb-4" />

      <form onSubmit={(e) => submit(e, 1)} className="bg-surface rounded-2xl border border-slate-200 shadow-sm p-6 mb-6 space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-slate-600">Email dell’account</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={`${input} mt-1`} placeholder="nome@studio.it" required />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Crediti</span>
            <input type="number" min={1} step={1} value={amount} onChange={(e) => setAmount(e.target.value)} className={`${input} mt-1`} placeholder="300" required />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((n) => (
            <button key={n} type="button" onClick={() => setAmount(String(n))}
              className="text-xs font-medium px-2.5 py-1 rounded-lg bg-slate-100 text-slate-600 hover:text-slate-900">
              {n.toLocaleString('it-IT')}
            </button>
          ))}
        </div>
        <label className="block text-sm">
          <span className="text-slate-600">Nota (facoltativa)</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} className={`${input} mt-1`} placeholder="es. beta test studio X" />
        </label>
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={saving}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50">
            {saving ? 'Salvataggio…' : 'Aggiungi crediti'}
          </button>
          <button type="button" disabled={saving} onClick={(e) => submit(e, -1)}
            className="px-4 py-2 rounded-lg text-sm font-semibold text-red-700 bg-red-50 hover:bg-red-100 disabled:opacity-50">
            Togli crediti
          </button>
        </div>
      </form>

      <section className="bg-surface rounded-2xl border border-slate-200 shadow-sm p-6">
        <div className="flex items-center justify-between gap-4 mb-4">
          <h2 className="text-sm font-semibold text-slate-900">Account</h2>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cerca per email o nome" className={`${input} max-w-xs`} />
        </div>
        {accounts.length === 0 ? (
          <p className="text-sm text-slate-500">Nessun account trovato.</p>
        ) : (
          <div className="overflow-x-auto -mx-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500">
                  <th className="font-medium px-2 py-1.5">Email</th>
                  <th className="font-medium px-2 py-1.5">Registrato</th>
                  <th className="font-medium px-2 py-1.5 text-right">Saldo</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {accounts.map((a) => (
                  <tr key={a.id} onClick={() => setEmail(a.email)} className="cursor-pointer hover:bg-slate-50" title="Usa questa email nel modulo">
                    <td className="px-2 py-1.5 text-slate-900">
                      {a.email}
                      {a.full_name && <span className="text-slate-400"> · {a.full_name}</span>}
                    </td>
                    <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap">
                      {a.created_at ? new Date(a.created_at).toLocaleDateString('it-IT') : '—'}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums font-medium text-slate-900">
                      {a.credits_unlimited ? 'illimitati' : a.credit_balance.toLocaleString('it-IT')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
