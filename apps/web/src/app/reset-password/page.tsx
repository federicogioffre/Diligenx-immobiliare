'use client'

import { Suspense, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { api } from '@/lib/api'
import ErrorAlert from '@/components/ui/ErrorAlert'

// Completion of the password-reset flow: the user lands here from the
// email link with ?token=... . useSearchParams requires a Suspense
// boundary in the App Router, hence the wrapper below.

function ResetPasswordForm() {
  const params = useSearchParams()
  const token = params.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (password !== confirm) {
      setError('Le password non coincidono')
      return
    }
    setLoading(true)
    try {
      await api.auth.resetPassword(token, password)
      setDone(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Reset fallito')
    } finally {
      setLoading(false)
    }
  }

  if (!token) {
    return (
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
        Link incompleto: manca il token di reset. Apri il link ricevuto via
        email oppure{' '}
        <Link href="/forgot-password" className="underline font-medium">
          richiedi un nuovo link
        </Link>
        .
      </div>
    )
  }

  if (done) {
    return (
      <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm text-emerald-800">
        Password aggiornata. Ora puoi{' '}
        <Link href="/login" className="underline font-medium">
          accedere con la nuova password
        </Link>
        .
      </div>
    )
  }

  return (
    <>
      <p className="text-sm text-slate-500 mb-6">
        Scegli la nuova password per il tuo account (minimo 8 caratteri).
      </p>
      <ErrorAlert error={error} className="mb-4" />
      <form onSubmit={handleSubmit} className="space-y-4">
        <input
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Nuova password"
          className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm shadow-sm focus:outline-none focus:ring-4 focus:ring-blue-500/15 focus:border-blue-500 transition-all"
          autoComplete="new-password"
        />
        <input
          type="password"
          required
          minLength={8}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          placeholder="Ripeti la nuova password"
          className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm shadow-sm focus:outline-none focus:ring-4 focus:ring-blue-500/15 focus:border-blue-500 transition-all"
          autoComplete="new-password"
        />
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors shadow-sm"
        >
          {loading ? 'Aggiornamento…' : 'Imposta nuova password'}
        </button>
      </form>
    </>
  )
}

export default function ResetPasswordPage() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-full max-w-sm">
        <h1 className="text-xl font-semibold text-slate-900 mb-2">
          Reimposta password
        </h1>
        <Suspense fallback={null}>
          <ResetPasswordForm />
        </Suspense>
        <p className="mt-6 text-sm text-slate-500 text-center">
          <Link href="/login" className="text-blue-600 hover:underline font-medium">
            Torna al login
          </Link>
        </p>
      </div>
    </div>
  )
}
