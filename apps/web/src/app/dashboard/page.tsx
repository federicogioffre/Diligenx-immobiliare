'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { toast } from 'sonner'
import { api, DealRead } from '@/lib/api'
import { getWorkspaceId } from '@/lib/auth'
import EmptyState from '@/components/ui/EmptyState'
import ErrorAlert from '@/components/ui/ErrorAlert'
import Spinner from '@/components/ui/Spinner'
import StatusBadge from '@/components/ui/StatusBadge'

const inputClass =
  'w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm text-slate-900 placeholder-slate-400 shadow-sm focus:outline-none focus:ring-4 focus:ring-blue-500/15 focus:border-blue-500 transition-all bg-surface'

function loiFileError(file: File | null): string {
  if (!file) return ''
  if (!/\.(pdf|docx|txt)$/i.test(file.name)) return 'La proposta deve essere un file PDF, DOCX o TXT.'
  if (file.type && !['application/octet-stream', 'application/pdf', 'text/plain', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'].includes(file.type)) {
    return 'Il formato della proposta non è supportato. Salvala come PDF, DOCX o TXT e riprova.'
  }
  if (file.size > 50 * 1024 * 1024) return 'La proposta non può superare 50 MB.'
  if (file.size === 0) return 'Il file della proposta è vuoto.'
  return ''
}

export default function DashboardPage() {
  const [deals, setDeals] = useState<DealRead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [value, setValue] = useState('')
  const [loiFile, setLoiFile] = useState<File | null>(null)
  const [createdDeal, setCreatedDeal] = useState<DealRead | null>(null)
  const [uploadMessage, setUploadMessage] = useState('')
  const [creating, setCreating] = useState(false)
  const [formError, setFormError] = useState('')
  const creatingRef = useRef(false)
  const loiInputRef = useRef<HTMLInputElement>(null)
  const uploadControllerRef = useRef<AbortController | null>(null)

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

  useEffect(() => () => uploadControllerRef.current?.abort(), [])

  function resetCreateForm() {
    setTitle(''); setDescription(''); setValue('')
    setLoiFile(null); setCreatedDeal(null); setFormError(''); setUploadMessage('')
    if (loiInputRef.current) loiInputRef.current.value = ''
  }

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
    if (creatingRef.current) return
    setFormError('')
    if (!title.trim()) { setFormError('Indica l’immobile oggetto della pratica.'); return }
    const fileError = loiFileError(loiFile)
    if (fileError) { setFormError(fileError); return }
    creatingRef.current = true
    setCreating(true)
    let deal = createdDeal
    try {
      if (!deal) {
        deal = await api.deals.create(getWorkspaceId(), {
          title: title.trim(),
          description: description || undefined,
          value: value ? Number(value) : undefined,
        })
        setCreatedDeal(deal)
        const savedDeal = deal
        setDeals((prev) => [savedDeal, ...prev.filter((item) => item.id !== savedDeal.id)])
      }
      if (loiFile) {
        const controller = new AbortController()
        uploadControllerRef.current = controller
        setUploadMessage('Caricamento proposta…')
        await api.documents.uploadWithProgress(deal.id, loiFile, (sent, total) => {
          setUploadMessage(`Caricamento proposta: ${total > 0 ? Math.round(sent / total * 100) : 0}%`)
        }, controller.signal, (seconds) => {
          setUploadMessage(`Caricamento proposta in attesa. Nuovo tentativo tra ${seconds} secondi…`)
        }, 'loi')
      }
      setShowForm(false)
      resetCreateForm()
      toast.success(loiFile ? `Pratica "${deal.title}" creata. Proposta caricata, elaborazione in corso.` : `Pratica "${deal.title}" creata`)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Riprova tra poco.'
      setFormError(deal ? `Pratica creata. Caricamento della proposta non confermato. Riprova lo stesso file o verifica i documenti della pratica. ${message}` : `Creazione non riuscita. ${message}`)
    } finally {
      creatingRef.current = false
      uploadControllerRef.current = null
      setUploadMessage('')
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
      toast.success(`Deal "${deal.title}" eliminato`)
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
        description: editDescription || null,
        value: editValue ? Number(editValue) : null,
      })
      setDeals((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
      setEditDeal(null)
      toast.success('Modifiche salvate')
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Salvataggio fallito')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      {/* Page header */}
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Deals</h1>
          <p className="text-sm text-slate-500 mt-1">
            {!loading && `${deals.length} deal${deals.length !== 1 ? 's' : ''} nel workspace`}
          </p>
        </div>
        <button
          onClick={() => { if (showForm && createdDeal) resetCreateForm(); setShowForm((v) => !v) }}
          disabled={creating}
          className="flex items-center gap-2 bg-ink hover:bg-ink-800 dark:bg-blue-600 dark:hover:bg-blue-500 text-white px-4 py-2.5 rounded-lg text-sm font-semibold transition-all shadow-md active:scale-[0.98] disabled:opacity-50"
        >
          {showForm ? (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              {createdDeal ? 'Chiudi' : 'Annulla'}
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              Nuova pratica
            </>
          )}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="bg-surface rounded-2xl border border-slate-200 shadow-lg p-6 sm:p-7 mb-8 animate-fade-up">
          <h2 className="text-base font-semibold text-slate-900 mb-4">Nuova pratica</h2>
          <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="sm:col-span-2">
              <label htmlFor="new-deal-title" className="block text-sm font-medium text-slate-700 mb-1.5">Immobile *</label>
              <input
                id="new-deal-title"
                required
                disabled={creating || !!createdDeal}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Es. Appartamento in via Roma 1, Milano"
                className={inputClass}
              />
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="new-deal-description" className="block text-sm font-medium text-slate-700 mb-1.5">Descrizione</label>
              <textarea
                id="new-deal-description"
                disabled={creating || !!createdDeal}
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Es. acquisto prima casa, con box auto e cantina…"
                className={inputClass + ' resize-none'}
              />
            </div>
            <div>
              <label htmlFor="new-deal-value" className="block text-sm font-medium text-slate-700 mb-1.5">Prezzo (€)</label>
              <input
                id="new-deal-value"
                disabled={creating || !!createdDeal}
                type="number"
                min="0"
                step="any"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="0"
                className={inputClass}
              />
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="new-deal-loi" className="block text-sm font-medium text-slate-700 mb-1.5">Proposta d’acquisto o preliminare — facoltativo</label>
              <input
                ref={loiInputRef}
                id="new-deal-loi"
                type="file"
                accept=".pdf,.docx,.txt"
                disabled={creating || !!createdDeal}
                onChange={(e) => {
                  const file = e.target.files?.[0] ?? null
                  setLoiFile(file)
                  setFormError(loiFileError(file))
                }}
                aria-describedby="new-deal-loi-help"
                className={inputClass + ' min-w-0 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1 file:text-sm'}
              />
              <p id="new-deal-loi-help" className="text-xs text-slate-500 mt-1.5">
                PDF, DOCX o TXT, massimo 50 MB. Aiuta gli agenti a leggere prezzo, condizioni e termini dell’acquisto. L’analisi si avvia dalla pagina della pratica.
              </p>
            </div>
            <div className="sm:col-span-2 flex flex-col items-start gap-3">
              {formError && <div className="w-full"><ErrorAlert error={formError} /></div>}
              {uploadMessage && <p role="status" className="text-sm text-blue-700">{uploadMessage}</p>}
              <button
                type="submit"
                disabled={creating}
                className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors"
              >
                {creating ? (createdDeal ? 'Caricamento proposta…' : 'Creazione…') : createdDeal ? 'Riprova caricamento proposta' : 'Crea pratica'}
              </button>
              {createdDeal && !creating && <Link href={`/deals/${createdDeal.id}`} className="text-sm font-semibold text-blue-600 hover:underline">Apri pratica</Link>}
            </div>
          </form>
        </div>
      )}

      <ErrorAlert error={error} className="mb-4" />

      {loading && (
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Spinner />
          Caricamento…
        </div>
      )}

      {!loading && deals.length === 0 && !error && (
        <EmptyState
          icon={
            <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
          }
          title="Nessun deal ancora"
          subtitle="Crea il tuo primo deal per iniziare l'analisi"
        />
      )}

      {/* Deal grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {deals.map((deal) => {
          return (
            <div
              key={deal.id}
              className="group relative flex flex-col bg-surface rounded-2xl border border-slate-200 shadow-sm hover:shadow-lg hover:-translate-y-0.5 hover:border-slate-300 transition-all duration-300"
            >
              <Link href={`/deals/${deal.id}`} className="block flex-1 p-5 rounded-t-2xl">
                {/* Status + date row */}
                <div className="flex items-center justify-between mb-3">
                  <StatusBadge status={deal.status} />
                  <span className="text-xs text-slate-400 font-mono">{deal.created_at.slice(0, 10)}</span>
                </div>

                {/* Title */}
                <h2 className="font-semibold text-slate-900 text-[15px] leading-snug mb-1.5 group-hover:text-blue-600 transition-colors line-clamp-2">
                  {deal.title}
                </h2>

                {/* Description */}
                {deal.description && (
                  <p className="text-xs text-slate-500 line-clamp-2 mb-3">{deal.description}</p>
                )}

                {/* Value */}
                {deal.value != null && (
                  <div className="flex items-center gap-1 text-base font-semibold text-slate-800 tabular-nums mt-auto">
                    <span className="text-xs text-slate-400 font-normal">€</span>
                    {deal.value.toLocaleString('it-IT')}
                  </div>
                )}
              </Link>

              {/* Action strip */}
              <div className="border-t border-slate-100 bg-slate-50/50 rounded-b-2xl px-4 py-2 flex gap-1">
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4 backdrop-blur-sm animate-fade-in">
          <div className="bg-surface rounded-2xl shadow-xl w-full max-w-md p-6 border border-slate-200">
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
                <label className="block text-sm font-medium text-slate-700 mb-1.5">Titolo *</label>
                <input required value={editTitle} onChange={(e) => setEditTitle(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">Descrizione</label>
                <textarea rows={3} value={editDescription} onChange={(e) => setEditDescription(e.target.value)} className={inputClass + ' resize-none'} />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">Valore (€)</label>
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
