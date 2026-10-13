'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LogoMark } from './brand/Logo'

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
    <footer className="mt-auto border-t border-slate-200/70 bg-surface/60 backdrop-blur">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs text-slate-500">
        <div className="flex items-center gap-2.5">
          <LogoMark className="w-5 h-5" />
          <span className="inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-blue-50 to-violet-50 text-blue-700 px-2 py-0.5 font-semibold ring-1 ring-inset ring-blue-100">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2} aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />
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
