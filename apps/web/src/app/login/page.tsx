'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { safeNextPath, selectInitialWorkspace } from '@/lib/session'
import OAuthButtons from '@/components/auth/OAuthButtons'

// Codes the Microsoft/Google callback sends back in ?oauth_error=.
const OAUTH_ERRORS: Record<string, string> = {
  cancelled: 'Accesso annullato.',
  email_not_verified:
    "Il provider non conferma che l'indirizzo e-mail sia verificato. Accedi con e-mail e password, oppure chiedi all'amministratore del tuo account.",
  email_missing: 'Il tuo account non comunica un indirizzo e-mail. Accedi con e-mail e password.',
  account_disabled: 'Questo account è disattivato.',
  invalid_state: 'La richiesta di accesso è scaduta o non è valida. Riprova.',
}

type Tab = 'login' | 'register'

export default function LoginPage() {
  const router = useRouter()
  const [tab, setTab] = useState<Tab>('login')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const [regEmail, setRegEmail] = useState('')
  const [regPassword, setRegPassword] = useState('')
  const [regName, setRegName] = useState('')

  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [next, setNext] = useState('/dashboard')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    setNext(safeNextPath(params.get('next')))
    const code = params.get('oauth_error')
    if (code) setError(OAUTH_ERRORS[code] ?? 'Accesso non riuscito. Riprova, oppure accedi con e-mail e password.')
  }, [])

  async function doLogin(email: string, password: string) {
    // The backend sets the HttpOnly session cookie on this response; the
    // browser applies it before the fetch promise resolves, so the calls
    // below are already authenticated.
    await api.auth.login(email, password)
    await selectInitialWorkspace()
    router.push('/dashboard')
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await doLogin(email, password)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.auth.register({ email: regEmail, password: regPassword, full_name: regName || undefined })
      await doLogin(regEmail, regPassword)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  const inputClass =
    'w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow bg-white'

  return (
    <div className="min-h-[85vh] flex items-center justify-center">
      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-blue-600 rounded-2xl shadow-lg mb-4">
            <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Diligenx</h1>
          <p className="text-slate-500 text-sm mt-1">Piattaforma di due diligence intelligente</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
          {/* Tabs */}
          <div className="flex gap-0.5 p-1 bg-slate-100 rounded-xl mb-6">
            {(['login', 'register'] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError('') }}
                className={`flex-1 py-1.5 rounded-lg text-sm font-medium transition-all capitalize ${
                  tab === t
                    ? 'bg-white text-slate-900 shadow-sm'
                    : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {t === 'login' ? 'Accedi' : 'Registrati'}
              </button>
            ))}
          </div>

          {tab === 'login' ? (
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Email</label>
                <input
                  suppressHydrationWarning
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="nome@azienda.com"
                  className={inputClass}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Password</label>
                <input
                  suppressHydrationWarning
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className={inputClass}
                />
              </div>
              {error && (
                <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                  <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {error}
                </div>
              )}
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors shadow-sm"
              >
                {loading ? 'Accesso in corso…' : 'Accedi'}
              </button>
              <p className="text-center">
                <a
                  href="/forgot-password"
                  className="text-xs text-slate-500 hover:text-blue-600 font-medium transition-colors"
                >
                  Password dimenticata?
                </a>
              </p>
            </form>
          ) : (
            <form onSubmit={handleRegister} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Nome completo</label>
                <input
                  type="text"
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  placeholder="Mario Rossi"
                  className={inputClass}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Email</label>
                <input
                  suppressHydrationWarning
                  type="email"
                  required
                  value={regEmail}
                  onChange={(e) => setRegEmail(e.target.value)}
                  placeholder="nome@azienda.com"
                  className={inputClass}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5 uppercase tracking-wide">Password</label>
                <input
                  suppressHydrationWarning
                  type="password"
                  required
                  minLength={6}
                  value={regPassword}
                  onChange={(e) => setRegPassword(e.target.value)}
                  placeholder="Min. 6 caratteri"
                  className={inputClass}
                />
              </div>
              {error && (
                <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                  <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {error}
                </div>
              )}
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors shadow-sm"
              >
                {loading ? 'Creazione account…' : 'Crea account'}
              </button>
            </form>
          )}

          <OAuthButtons next={next} divider />
        </div>
      </div>
    </div>
  )
}
