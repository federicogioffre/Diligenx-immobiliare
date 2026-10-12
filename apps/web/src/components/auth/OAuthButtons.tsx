'use client'

import { useEffect, useState } from 'react'
import { api, oauthStartUrl, OAuthProvider } from '@/lib/api'

const LABELS: Record<OAuthProvider, string> = {
  microsoft: 'Accedi con Microsoft',
  google: 'Accedi con Google',
}

function MicrosoftLogo() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 21 21" aria-hidden="true">
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  )
}

function GoogleLogo() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  )
}

/** One button per sign-in provider the deployment offers; nothing when none. */
export default function OAuthButtons({
  next,
  label,
  divider = false,
}: {
  next?: string
  label?: (p: OAuthProvider) => string
  divider?: boolean
}) {
  const [providers, setProviders] = useState<OAuthProvider[]>([])

  useEffect(() => {
    // Microsoft first: it is what most firms run on.
    api.auth.oauthProviders().then((list) =>
      setProviders([...list].sort((a, b) => Number(b === 'microsoft') - Number(a === 'microsoft'))),
    )
  }, [])

  if (providers.length === 0) return null

  return (
    <div className="space-y-2">
      {divider && (
        <div className="flex items-center gap-3 pt-3 pb-2 text-xs text-slate-400">
          <span className="h-px flex-1 bg-slate-200" />
          oppure
          <span className="h-px flex-1 bg-slate-200" />
        </div>
      )}
      {providers.map((p) => (
        <a
          key={p}
          href={oauthStartUrl(p, next)}
          className="w-full inline-flex items-center justify-center gap-2.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 hover:border-slate-300 py-2.5 rounded-lg text-sm font-semibold transition-colors"
        >
          {p === 'microsoft' ? <MicrosoftLogo /> : <GoogleLogo />}
          {label ? label(p) : LABELS[p]}
        </a>
      ))}
    </div>
  )
}

export function providerName(p: OAuthProvider): string {
  return p === 'microsoft' ? 'Microsoft' : 'Google'
}
