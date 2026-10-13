'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { safeNextPath, selectInitialWorkspace } from '@/lib/session'
import OAuthButtons from '@/components/auth/OAuthButtons'
import Logo from '@/components/brand/Logo'
import Link from 'next/link'

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
    'w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm text-slate-900 placeholder-slate-400 shadow-sm focus:outline-none focus:ring-4 focus:ring-blue-500/15 focus:border-blue-500 transition-all bg-white'
  const labelClass = 'block text-sm font-medium text-slate-700 mb-1.5'
  const submitClass =
    'group w-full inline-flex items-center justify-center gap-2 bg-ink hover:bg-ink-800 text-white py-2.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition-all shadow-md active:scale-[0.99]'

  const errorBanner = error && (
    <div role="alert" className="flex items-start gap-2 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2.5">
      <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      {error}
    </div>
  )

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-white">
      {/* Brand panel */}
      <aside className="relative isolate hidden lg:flex flex-col justify-between overflow-hidden bg-ink p-12 text-white">
        <div className="absolute inset-0 bg-grid mask-radial -z-10" aria-hidden />
        <div
          className="absolute -left-40 -top-40 h-[560px] w-[560px] rounded-full blur-3xl opacity-60 -z-10"
          style={{ background: 'radial-gradient(closest-side, rgb(74 85 232 / 0.6), transparent)' }}
          aria-hidden
        />
        <div
          className="absolute -bottom-48 -right-32 h-[520px] w-[520px] rounded-full blur-3xl opacity-50 -z-10"
          style={{ background: 'radial-gradient(closest-side, rgb(139 92 246 / 0.5), transparent)' }}
          aria-hidden
        />

        <Link href="/" className="w-fit rounded-lg">
          <Logo tone="dark" />
        </Link>

        <div className="max-w-md">
          <h2 className="text-4xl xl:text-5xl font-semibold tracking-tight leading-[1.1]">
            La due diligence,
            <br />
            <span className="font-display font-normal italic text-gradient pr-1">in ore.</span>
          </h2>
          <p className="mt-5 text-slate-400 leading-relaxed">
            Carica la data room e lascia che gli agenti AI leggano contratti,
            atti societari, bilanci e documenti fiscali per te.
          </p>
          <ul className="mt-10 space-y-4">
            {[
              'Red flag con citazione di documento e pagina',
              'Report bilingue, export PDF e DOCX',
              'Provider AI in modalità no-training',
            ].map((t) => (
              <li key={t} className="flex items-center gap-3 text-sm text-slate-300">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/15 text-blue-300 ring-1 ring-inset ring-blue-400/30">
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3} aria-hidden>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </span>
                {t}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-slate-500">
          © {new Date().getFullYear()} Diligenx · L&apos;output non sostituisce un parere legale.
        </p>
      </aside>

      {/* Form */}
      <div className="relative flex flex-col items-center justify-center px-4 sm:px-6 py-12">
        <div className="absolute inset-0 bg-grid-light mask-radial opacity-60 -z-0 lg:hidden" aria-hidden />
        <div className="relative w-full max-w-sm animate-fade-up">
          <Link href="/" className="lg:hidden mb-10 flex justify-center rounded-lg">
            <Logo />
          </Link>

          <div className="mb-8">
            <h1 className="text-2xl font-semibold text-slate-900 tracking-tight">
              {tab === 'login' ? 'Accedi a Diligenx' : 'Crea il tuo account'}
            </h1>
            <p className="text-slate-500 text-sm mt-1.5">
              {tab === 'login'
                ? 'Accedi per riprendere le tue operazioni.'
                : 'Inizia la tua prima due diligence in pochi minuti.'}
            </p>
          </div>

          {/* Tabs */}
          <div className="relative grid grid-cols-2 p-1 bg-slate-100 rounded-xl mb-6 ring-1 ring-inset ring-slate-200/60">
            <span
              className={`absolute inset-y-1 left-1 w-[calc(50%-0.25rem)] rounded-lg bg-white shadow-sm ring-1 ring-slate-200/80 transition-transform duration-300 ease-out ${
                tab === 'register' ? 'translate-x-full' : ''
              }`}
              aria-hidden
            />
            {(['login', 'register'] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError('') }}
                className={`relative py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  tab === t ? 'text-slate-900' : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {t === 'login' ? 'Accedi' : 'Registrati'}
              </button>
            ))}
          </div>

          {tab === 'login' ? (
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className={labelClass}>Email</label>
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
                <div className="flex items-center justify-between mb-1.5">
                  <label className="block text-sm font-medium text-slate-700">Password</label>
                  <a
                    href="/forgot-password"
                    className="text-xs text-slate-500 hover:text-blue-600 font-medium transition-colors"
                  >
                    Password dimenticata?
                  </a>
                </div>
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
              {errorBanner}
              <button type="submit" disabled={loading} className={submitClass}>
                {loading ? 'Accesso in corso…' : 'Accedi'}
                {!loading && <Arrow />}
              </button>
            </form>
          ) : (
            <form onSubmit={handleRegister} className="space-y-4">
              <div>
                <label className={labelClass}>Nome completo</label>
                <input
                  type="text"
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  placeholder="Mario Rossi"
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Email</label>
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
                <label className={labelClass}>Password</label>
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
              {errorBanner}
              <button type="submit" disabled={loading} className={submitClass}>
                {loading ? 'Creazione account…' : 'Crea account'}
                {!loading && <Arrow />}
              </button>
            </form>
          )}

          <OAuthButtons next={next} divider />

          <nav className="mt-10 flex items-center justify-center gap-4 text-xs text-slate-400">
            {[
              { href: '/terms', label: 'Termini' },
              { href: '/privacy', label: 'Privacy' },
              { href: '/security', label: 'Sicurezza' },
            ].map((l) => (
              <Link key={l.href} href={l.href} className="hover:text-slate-600 transition-colors">
                {l.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </div>
  )
}

function Arrow() {
  return (
    <svg className="w-4 h-4 transition-transform group-hover:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14m-6-6l6 6-6 6" />
    </svg>
  )
}
