'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api, oauthStartUrl, UserRead } from '@/lib/api'
import { providerName } from '@/components/auth/OAuthButtons'
import { clearAuth } from '@/lib/auth'
import ErrorAlert from '@/components/ui/ErrorAlert'
import Spinner from '@/components/ui/Spinner'

// Account self-service: profile info, GDPR data export (art. 20) and
// account deletion (art. 17). The deletion flow requires re-typing the
// password and an explicit textual confirmation — this is the most
// destructive action in the product. An account that signs in only with
// Microsoft or Google confirms by signing in again, which brings the person
// back here with ?confirm=delete and a fresh session.
export default function AccountPage() {
  const [user, setUser] = useState<UserRead | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [exporting, setExporting] = useState(false)

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [reauthenticated, setReauthenticated] = useState(false)

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('confirm') === 'delete') {
      setReauthenticated(true)
      setConfirmOpen(true)
    }
  }, [])

  useEffect(() => {
    api.users
      .me()
      .then(setUser)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Errore')
      )
      .finally(() => setLoading(false))
  }, [])

  async function handleExport() {
    setExporting(true)
    setError('')
    try {
      const blob = await api.users.exportData()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `diligenx_export_${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast.success('Export scaricato')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Export fallito')
    } finally {
      setExporting(false)
    }
  }

  async function handleDelete() {
    setDeleting(true)
    setDeleteError('')
    try {
      await api.users.deleteAccount(user?.has_password === false ? null : password)
      await clearAuth()
      window.location.href = '/'
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Eliminazione fallita'
      // The ten-minute window passed: offer the sign-in again.
      if (message.startsWith('Accesso scaduto')) setReauthenticated(false)
      setDeleteError(message)
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-slate-500 text-sm py-12">
        <Spinner />
        Caricamento…
      </div>
    )
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-xl font-semibold text-slate-900 mb-6">Account</h1>

      <ErrorAlert error={error} className="mb-4" />

      {/* Profile */}
      {user && (
        <section className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-6">
          <h2 className="text-sm font-semibold text-slate-900 mb-4">Profilo</h2>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Email</dt>
              <dd className="text-slate-900 font-medium">{user.email}</dd>
            </div>
            {user.auth_providers.length > 0 && (
              <div className="flex justify-between">
                <dt className="text-slate-500">Accesso con</dt>
                <dd className="text-slate-900 font-medium">
                  {user.auth_providers.map(providerName).join(', ')}
                </dd>
              </div>
            )}
            {user.full_name && (
              <div className="flex justify-between">
                <dt className="text-slate-500">Nome</dt>
                <dd className="text-slate-900 font-medium">{user.full_name}</dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-slate-500">Registrato il</dt>
              <dd className="text-slate-900 font-medium">
                {new Date(user.created_at).toLocaleDateString('it-IT')}
              </dd>
            </div>
          </dl>
        </section>
      )}

      {/* Data export */}
      <section className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-6">
        <h2 className="text-sm font-semibold text-slate-900 mb-2">
          Esporta i tuoi dati
        </h2>
        <p className="text-sm text-slate-500 mb-4">
          Scarica una copia completa dei tuoi dati in formato JSON: workspace,
          deal, metadati dei documenti, red flag, report generati. Conforme al
          diritto alla portabilità (art. 20 GDPR).
        </p>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="inline-flex items-center gap-2 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 hover:border-slate-300 px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors"
        >
          {exporting ? <Spinner size="sm" tone="slate" /> : (
            <svg className="w-4 h-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
          )}
          Scarica export JSON
        </button>
      </section>

      {/* Danger zone */}
      <section className="bg-white rounded-2xl border border-red-200 shadow-sm p-6">
        <h2 className="text-sm font-semibold text-red-700 mb-2">
          Elimina account
        </h2>
        <p className="text-sm text-slate-500 mb-4">
          Elimina definitivamente il tuo account e tutti i dati associati:
          workspace, deal, documenti caricati (inclusi i file), analisi e
          report. L&apos;operazione è irreversibile (art. 17 GDPR).
        </p>

        {!confirmOpen ? (
          <button
            onClick={() => setConfirmOpen(true)}
            className="bg-white hover:bg-red-50 text-red-600 border border-red-200 hover:border-red-300 px-4 py-2 rounded-lg text-sm font-semibold transition-colors"
          >
            Elimina il mio account…
          </button>
        ) : (
          <div className="space-y-3 border-t border-slate-100 pt-4">
            <ErrorAlert error={deleteError} />
            {user?.has_password === false ? (
              reauthenticated ? (
                <p className="text-sm text-slate-600">
                  Identità confermata. Hai dieci minuti per completare l&apos;eliminazione.
                </p>
              ) : (
                <div className="space-y-2">
                  <p className="text-sm text-slate-600">
                    Per confermare che sei tu, accedi di nuovo.
                  </p>
                  {user.auth_providers.map((p) => (
                    <a
                      key={p}
                      href={oauthStartUrl(p, '/account?confirm=delete')}
                      className="inline-flex items-center bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 px-4 py-2 rounded-lg text-sm font-semibold mr-2"
                    >
                      Accedi di nuovo con {providerName(p)}
                    </a>
                  ))}
                </div>
              )
            ) : (
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Conferma la tua password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-4 focus:ring-red-500/15 focus:border-red-400 transition-all"
                  autoComplete="current-password"
                />
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Scrivi <span className="font-mono font-semibold">ELIMINA</span>{' '}
                per confermare
              </label>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-4 focus:ring-red-500/15 focus:border-red-400 transition-all"
              />
            </div>
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={handleDelete}
                disabled={
                  deleting ||
                  confirmText !== 'ELIMINA' ||
                  (user?.has_password === false ? !reauthenticated : !password)
                }
                className="inline-flex items-center gap-2 bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors"
              >
                {deleting && <Spinner size="sm" tone="white" />}
                Elimina definitivamente
              </button>
              <button
                onClick={() => {
                  setConfirmOpen(false)
                  setPassword('')
                  setConfirmText('')
                  setDeleteError('')
                }}
                disabled={deleting}
                className="text-sm text-slate-600 hover:text-slate-900 font-medium px-3 py-2"
              >
                Annulla
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
