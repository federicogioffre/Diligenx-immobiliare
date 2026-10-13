'use client'

import { useState } from 'react'
import Link from 'next/link'
import { api } from '@/lib/api'
import ErrorAlert from '@/components/ui/ErrorAlert'

// Start of the password-reset flow. The backend always answers 202 —
// whether or not the email exists — so the UI shows the same neutral
// confirmation in every case (no user enumeration).
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.auth.forgotPassword(email)
      setSent(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Richiesta fallita')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-full max-w-sm">
        <h1 className="text-xl font-semibold text-slate-900 mb-2">
          Password dimenticata
        </h1>

        {sent ? (
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm text-emerald-800 mt-4">
            Se l&apos;indirizzo è registrato, riceverai un&apos;email con il
            link per reimpostare la password. Il link è valido 30 minuti.
          </div>
        ) : (
          <>
            <p className="text-sm text-slate-500 mb-6">
              Inserisci l&apos;email del tuo account: ti invieremo un link per
              scegliere una nuova password.
            </p>
            <ErrorAlert error={error} className="mb-4" />
            <form onSubmit={handleSubmit} className="space-y-4">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="email@studio.it"
                className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm shadow-sm focus:outline-none focus:ring-4 focus:ring-blue-500/15 focus:border-blue-500 transition-all"
                autoComplete="email"
              />
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors shadow-sm"
              >
                {loading ? 'Invio in corso…' : 'Invia link di reset'}
              </button>
            </form>
          </>
        )}

        <p className="mt-6 text-sm text-slate-500 text-center">
          <Link href="/login" className="text-blue-600 hover:underline font-medium">
            Torna al login
          </Link>
        </p>
      </div>
    </div>
  )
}
