'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { clearAuth } from '@/lib/auth'
import WorkspaceSwitcher from './WorkspaceSwitcher'

export default function NavBar() {
  const pathname = usePathname()
  const router = useRouter()

  if (pathname === '/login') return null

  function handleLogout() {
    clearAuth()
    router.push('/login')
  }

  return (
    <nav className="bg-white border-b border-slate-200 sticky top-0 z-30">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between gap-4">
        {/* Left cluster: logo + workspace switcher */}
        <div className="flex items-center gap-4 min-w-0">
          <Link href="/dashboard" className="flex items-center gap-2.5 group shrink-0">
            <div className="w-7 h-7 bg-blue-600 rounded-lg flex items-center justify-center shadow-sm">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <span className="font-semibold text-slate-900 text-sm tracking-tight">Diligenx</span>
          </Link>
          <div className="h-5 w-px bg-slate-200 shrink-0" aria-hidden />
          <WorkspaceSwitcher />
        </div>

        {/* Right side */}
        <div className="flex items-center gap-1 shrink-0">
          <Link
            href="/dashboard"
            className="text-sm text-slate-600 hover:text-slate-900 font-medium px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors"
          >
            Dashboard
          </Link>
          <button
            onClick={handleLogout}
            className="text-sm text-slate-600 hover:text-slate-900 font-medium px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors ml-1"
          >
            Esci
          </button>
        </div>
      </div>
    </nav>
  )
}
