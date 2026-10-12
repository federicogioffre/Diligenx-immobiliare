'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { clearAuth } from '@/lib/auth'
import Logo from './brand/Logo'
import WorkspaceSwitcher from './WorkspaceSwitcher'

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

  // The landing (/) and login pages render their own marketing-style
  // header — the in-app NavBar is hidden there.
  if (pathname === '/' || pathname === '/login') return null

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
            {LINKS.map((l) => {
              const active = pathname === l.href
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  aria-current={active ? 'page' : undefined}
                  className={`inline-flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-lg transition-all ${
                    active
                      ? 'bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/80'
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
          <button
            onClick={handleLogout}
            className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900 font-medium px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors ml-1"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l5-5-5-5M15 12H3" />
            </svg>
            Esci
          </button>
        </div>
      </div>
    </nav>
  )
}
