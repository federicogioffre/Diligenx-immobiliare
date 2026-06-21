'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const LINKS = [
  { href: '/privacy',  label: 'Privacy' },
  { href: '/cookies',  label: 'Cookies' },
  { href: '/terms',    label: 'Termini' },
  { href: '/dpa',      label: 'DPA' },
  { href: '/security', label: 'Security' },
]

/**
 * Global footer for authenticated app pages.
 *
 * Hidden on:
 *   - "/"     — landing page renders its own (marketing-style) footer
 *   - "/login" — clean form, no chrome
 */
export default function AppFooter() {
  const pathname = usePathname()
  if (pathname === '/' || pathname === '/login') return null

  return (
    <footer className="mt-auto border-t border-slate-200 bg-white">
      <div className="max-w-6xl mx-auto px-6 py-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs text-slate-500">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 text-blue-700 px-2 py-0.5 font-semibold">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            Powered by AI
          </span>
          <span className="text-slate-500">
            L&apos;output non sostituisce un parere legale.
          </span>
        </div>

        <nav className="flex flex-wrap items-center gap-4">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="hover:text-slate-900 transition-colors"
            >
              {l.label}
            </Link>
          ))}
          <span className="text-slate-300">·</span>
          <span>© {new Date().getFullYear()} Diligenx</span>
        </nav>
      </div>
    </footer>
  )
}
