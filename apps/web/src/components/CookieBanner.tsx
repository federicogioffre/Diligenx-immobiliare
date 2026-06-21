'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

const STORAGE_KEY = 'dm_cookie_notice_dismissed'

/**
 * Cookie information banner.
 *
 * Today Diligenx only sets technical session cookies (``dm_token``,
 * ``dm_workspace``) that are strictly necessary for the service to work,
 * so we render an *informative* banner (per the Italian Garante's May 2021
 * guidelines), not a consent-based one. There is no "Reject" path because
 * the cookies cannot be refused without breaking authentication.
 *
 * If we ever add non-essential trackers (analytics, marketing) this banner
 * must be replaced with a real consent layer (opt-in, granular categories).
 */
export default function CookieBanner() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    try {
      if (localStorage.getItem(STORAGE_KEY) !== '1') {
        setVisible(true)
      }
    } catch {
      // SSR / privacy mode — fail open (don't show), no harm done.
    }
  }, [])

  function dismiss() {
    try {
      localStorage.setItem(STORAGE_KEY, '1')
    } catch {
      /* ignore */
    }
    setVisible(false)
  }

  if (!visible) return null

  return (
    <div className="fixed bottom-4 inset-x-4 sm:inset-x-auto sm:right-6 sm:left-auto sm:max-w-md z-50">
      <div className="rounded-2xl border border-slate-200 bg-white shadow-xl p-4 text-sm text-slate-700">
        <div className="flex items-start gap-3">
          <div className="shrink-0 w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="flex-1">
            <p className="font-medium text-slate-900 mb-1">Cookie tecnici</p>
            <p className="text-slate-600 leading-relaxed">
              Usiamo solo cookie tecnici di sessione, necessari al funzionamento
              dell&apos;app. Nessun tracker, nessuna profilazione.{' '}
              <Link href="/cookies" className="text-blue-600 hover:underline">
                Dettagli
              </Link>
              .
            </p>
            <div className="mt-3">
              <button
                onClick={dismiss}
                className="px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition-colors"
              >
                Ho capito
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
