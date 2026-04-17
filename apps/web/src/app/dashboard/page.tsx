'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { api, DealRead } from '@/lib/api'
import { getWorkspaceId } from '@/lib/auth'

const STATUS_CONFIG: Record<string, { label: string; dot: string; badge: string }> = {
  draft:     { label: 'Bozza',     dot: 'bg-slate-400',   badge: 'bg-slate-100 text-slate-600' },
  analyzing: { label: 'Analisi',   dot: 'bg-amber-400',   badge: 'bg-amber-50 text-amber-700' },
  reviewed:  { label: 'Revisionato', dot: 'bg-emerald-500', badge: 'bg-emerald-50 text-emerald-700' },
  closed:    { label: 'Chiuso',    dot: 'bg-blue-400',    badge: 'bg-blue-50 text-blue-700' },
}

const inputClass =
  'w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow bg-white'

export default function DashboardPage() {
  const [deals, setDeals] = useState<DealRead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [value, setValue] = useState('')
  const [creating, setCreating] = useState(false)
  const [formError, setFormError] = useState('')

  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [editDeal, setEditDeal] = useState<DealRead | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState('')

  useEffect(() => {
    // Auth guard is enforced by middleware.ts; 401 responses from api.ts
    // trigger an automatic redirect. No client-side check needed here.
    fetchDeals()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function fetchDeals() {
    setLoading(true)
    try {
      const data = await api.deals.list(getWorkspaceId())
      setDeals(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Errore nel caricamento')
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError('')
    setCreating(true)
    try {
      const deal = await api.deals.create(getWorkspaceId(), {
        title,
        description: description || undefined,
        value: value ? Number(value) : undefined,
      })
      setDeals((prev) => [deal, ...prev])
      setShowForm(false)
      setTitle(''); setDescription(''); setValue('')
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Errore nella creazione')
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(deal: DealRead, e: React.MouseEvent) {
    e.preventDefault(); e.stopPropagation()
    if (!confirm(`Eliminare "${deal.title}"? L'azione è irreversibile.`)) return
    setDeletingId(deal.id)
    try {
      await api.deals.delete(deal.id)
      setDeals((prev) => prev.filter((d) => d.id !== deal.id))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Eliminazione fallita')
    } finally {
      setDeletingId(null)
    }
  }

  function openEdit(deal: DealRead, e: React.MouseEvent) {
    e.preventDefault(); e.stopPropagation()
    setEditDeal(deal)
    setEditTitle(deal.title)
    setEditDescription(deal.description ?? '')
    setEditValue(deal.value != null ? String(deal.value) : '')
    setEditError('')
  }

  async function handleSaveEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editDeal) return
    setEditError(''); setSaving(true)
    try {
      const updated = await api.deals.update(editDeal.id, {
        title: editTitle,
        description: editDescription || undefined,
        value: editValue ? Number(editValue) : undefined,
      })
      setDeals((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
      setEditDeal(null)
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Salvataggio fallito')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      {/* Page header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Deals</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {!loading && `${deals.length} deal${deals.length !== 1 ? 's' : ''} nel workspace`}
          </p>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-semibold transition-colors shadow-sm"
        >
          {showForm ? (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              Annulla
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              Nuovo Deal
            </>
          )}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-6">
          <h2 className="text-base font-semibold text-slate-900 mb-4">Nuovo Deal</h2>
          <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Titolo *</label>
              <input
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Es. Acquisizione Azienda XYZ"
                className={inputClass}
              />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Descrizione</label>
              <textarea
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Breve descrizione dell'operazione…"
                className={inputClass + ' resize-none'}
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Valore deal (€)</label>
              <input
                type="number"
                min="0"
                step="any"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="0"
                className={inputClass}
              />
            </div>
            <div className="flex flex-col justify-end">
              {formError && <p className="text-red-600 text-xs mb-2">{formError}</p>}
              <button
                type="submit"
                disabled={creating}
                className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors"
              >
                {creating ? 'Creazione…' : 'Crea Deal'}
              </button>
            </div>
          </form>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-4 py-3 mb-4">
          <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
          Caricamento…
        </div>
      )}

      {!loading && deals.length === 0 && !error && (
        <div className="text-center py-20 bg-white rounded-2xl border border-slate-200 border-dashed">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-slate-100 rounded-xl mb-4">
            <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
          </div>
          <p className="text-slate-600 font-medium mb-1">Nessun deal ancora</p>
          <p className="text-slate-400 text-sm">Crea il tuo primo deal per iniziare l&apos;analisi</p>
        </div>
      )}

      {/* Deal grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {deals.map((deal) => {
          const cfg = STATUS_CONFIG[deal.status] ?? STATUS_CONFIG.draft
          return (
            <div
              key={deal.id}
              className="group bg-white rounded-2xl border border-slate-200 shadow-sm hover:shadow-md hover:border-slate-300 transition-all"
            >
              <Link href={`/deals/${deal.id}`} className="block p-5">
                {/* Status + date row */}
                <div className="flex items-center justify-between mb-3">
                  <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${cfg.badge}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
                    {cfg.label}
                  </span>
                  <span className="text-xs text-slate-400">{deal.created_at.slice(0, 10)}</span>
                </div>

                {/* Title */}
                <h2 className="font-semibold text-slate-900 text-sm leading-snug mb-1.5 group-hover:text-blue-600 transition-colors line-clamp-2">
                  {deal.title}
                </h2>

                {/* Description */}
                {deal.description && (
                  <p className="text-xs text-slate-500 line-clamp-2 mb-3">{deal.description}</p>
                )}

                {/* Value */}
                {deal.value != null && (
                  <div className="flex items-center gap-1 text-sm font-semibold text-slate-700 mt-auto">
                    <span className="text-xs text-slate-400 font-normal">€</span>
                    {deal.value.toLocaleString('it-IT')}
                  </div>
                )}
              </Link>

              {/* Action strip */}
              <div className="border-t border-slate-100 px-5 py-2.5 flex gap-2">
                <button
                  onClick={(e) => openEdit(deal, e)}
                  className="text-xs text-slate-500 hover:text-slate-800 font-medium flex items-center gap-1 hover:bg-slate-50 px-2 py-1 rounded-md transition-colors"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                  Modifica
                </button>
                <button
                  onClick={(e) => handleDelete(deal, e)}
                  disabled={deletingId === deal.id}
                  className="text-xs text-red-400 hover:text-red-600 font-medium flex items-center gap-1 hover:bg-red-50 px-2 py-1 rounded-md transition-colors disabled:opacity-40"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                  {deletingId === deal.id ? 'Eliminando…' : 'Elimina'}
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Edit modal */}
      {editDeal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 border border-slate-200">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-base font-semibold text-slate-900">Modifica Deal</h2>
              <button
                onClick={() => setEditDeal(null)}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <form onSubmit={handleSaveEdit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Titolo *</label>
                <input required value={editTitle} onChange={(e) => setEditTitle(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Descrizione</label>
                <textarea rows={3} value={editDescription} onChange={(e) => setEditDescription(e.target.value)} className={inputClass + ' resize-none'} />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Valore (€)</label>
                <input type="number" min="0" step="any" value={editValue} onChange={(e) => setEditValue(e.target.value)} className={inputClass} />
              </div>
              {editError && <p className="text-red-600 text-sm">{editError}</p>}
              <div className="flex gap-3 pt-1">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors"
                >
                  {saving ? 'Salvataggio…' : 'Salva modifiche'}
                </button>
                <button
                  type="button"
                  onClick={() => setEditDeal(null)}
                  className="flex-1 bg-slate-100 hover:bg-slate-200 text-slate-700 py-2.5 rounded-lg text-sm font-medium transition-colors"
                >
                  Annulla
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
