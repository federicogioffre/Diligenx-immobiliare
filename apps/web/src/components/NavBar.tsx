'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import type { UserRead } from '@/lib/api'
import { clearAuth, isLoggedIn } from '@/lib/auth'
import CreditBadge from './CreditBadge'
import Logo from './brand/Logo'
import WorkspaceSwitcher from './WorkspaceSwitcher'
import ThemeToggle from './theme/ThemeToggle'

const ADMIN_LINK = {
  href: '/admin/credits',
  label: 'Admin',
  icon: 'M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6l7-3z',
}

const LINKS = [
  {
    href: '/dashboard',
    label: 'Dashboard',
    icon: 'M4 5a1 1 0 011-1h4a1 1 0 011 1v5a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm10 0a1 1 0 011-1h4a1 1 0 011 1v2a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zm10-3a1 1 0 011-1h4a1 1 0 011 1v7a1 1 0 01-1 1h-4a1 1 0 01-1-1v-7z',
  },
  {
    href: '/dashboard/insights',
    label: 'Insights',
    icon: 'M3 3v18h18M7 15l3.5-4 3 3L19 8',
  },
  {
    href: '/account',
    label: 'Account',
    icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
  },
]

export default function NavBar() {
  const pathname = usePathname()
  const router = useRouter()
  const [user, setUser] = useState<UserRead | null>(null)
  // null until mounted: the session flag is a browser cookie, unknown during
  // server rendering.
  const [authed, setAuthed] = useState<boolean | null>(null)
  const hidden = pathname === '/' || pathname === '/login'

  useEffect(() => {
    setAuthed(isLoggedIn())
  }, [pathname])

  // Re-read on navigation: an analysis or a top-up changes the balance.
  // A plain fetch, not api.users.me(): the bar also shows on the public
  // legal pages, where a 401 must not send the visitor to /login.
  useEffect(() => {
    if (hidden || !isLoggedIn()) return
    let cancelled = false
    fetch('/api/users/me')
      .then((res) => (res.ok ? res.json() : null))
      .then((me: UserRead | null) => { if (!cancelled) setUser(me) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [pathname, hidden])

  // The landing (/) and login pages render their own marketing-style
  // header — the in-app NavBar is hidden there.
  if (hidden) return null
  // Signed-out visitors reach the public pages (legal, password reset) too.
  // The in-app bar must not render for them: its workspace switcher calls an
  // authenticated endpoint, and the 401 sent them to /login instead of the
  // page they had opened.
  if (authed === null) return <nav className="glass sticky top-0 z-30 h-16 border-b border-slate-200/70" aria-hidden />
  if (!authed) return <PublicNavBar />
  const links = user?.is_admin ? [...LINKS, ADMIN_LINK] : LINKS

  async function handleLogout() {
    // Await: only the backend can delete the HttpOnly session cookie, and
    // navigating first can abort the request, leaving the user logged in.
    await clearAuth()
    router.push('/login')
  }

  return (
    <nav className="glass sticky top-0 z-30 border-b border-slate-200/70">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 lg:h-16 lg:py-0 flex flex-wrap items-center justify-between gap-3">
        {/* Left cluster: logo + workspace switcher */}
        <div className="flex items-center gap-2 sm:gap-4 min-w-0 w-full lg:w-auto">
          <Link href="/dashboard" className="shrink-0 rounded-lg">
            <Logo />
          </Link>
          <svg className="w-4 h-4 text-slate-300 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden>
            <path strokeLinecap="round" d="M16 3L8 21" />
          </svg>
          <WorkspaceSwitcher />
        </div>

        {/* Right side */}
        <div className="flex items-center justify-between gap-1 w-full lg:w-auto shrink-0">
          <div className="flex items-center gap-0.5 rounded-xl bg-slate-100/80 p-1 ring-1 ring-inset ring-slate-200/60">
            {links.map((l) => {
              const active = pathname === l.href
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  aria-current={active ? 'page' : undefined}
                  className={`inline-flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-lg transition-all ${
                    active
                      ? 'bg-surface text-slate-900 shadow-sm ring-1 ring-slate-200/80'
                      : 'text-slate-500 hover:text-slate-900'
                  }`}
                >
                  <svg
                    className={`w-3.5 h-3.5 hidden sm:block ${active ? 'text-blue-600' : 'text-slate-400'}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                    aria-hidden
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d={l.icon} />
                  </svg>
                  {l.label}
                </Link>
              )
            })}
          </div>
          <div className="flex items-center gap-0.5 ml-1">
          <CreditBadge user={user} />
          <ThemeToggle />
          <button
            onClick={handleLogout}
            aria-label="Esci"
            className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900 font-medium px-2.5 sm:px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l5-5-5-5M15 12H3" />
            </svg>
            <span className="hidden sm:inline">Esci</span>
          </button>
          </div>
        </div>
      </div>
    </nav>
  )
}

/** Header for signed-out visitors on the public pages outside the landing. */
function PublicNavBar() {
  return (
    <nav className="glass sticky top-0 z-30 border-b border-slate-200/70">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-3">
        <Link href="/" className="shrink-0 rounded-lg">
          <Logo />
        </Link>
        <div className="flex items-center gap-1">
          <Link
            href="/login"
            className="text-sm font-medium text-slate-500 hover:text-slate-900 px-3 py-1.5 rounded-lg transition-colors"
          >
            Accedi
          </Link>
          <Link
            href="/login"
            className="text-sm font-semibold bg-ink text-white hover:bg-slate-800 dark:bg-blue-600 dark:hover:bg-blue-500 px-3.5 py-1.5 rounded-lg transition-colors"
          >
            Inizia gratis
          </Link>
        </div>
      </div>
    </nav>
  )
}
