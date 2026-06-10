// Edge middleware: server-side auth guard.
//
// Reads the `dm_token` cookie and redirects before any page is rendered.
// This eliminates the client-side flash of private content that would
// otherwise appear while React waits for a useEffect guard to fire.

import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { isTokenExpired } from '@/lib/auth'

const PUBLIC_PATHS = ['/', '/login']
const IGNORED_PREFIXES = ['/_next', '/api', '/favicon']

function isPublic(path: string): boolean {
  return (
    PUBLIC_PATHS.includes(path) ||
    IGNORED_PREFIXES.some((p) => path.startsWith(p))
  )
}

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl
  const token = req.cookies.get('dm_token')?.value ?? null
  const invalid = isTokenExpired(token) // covers missing, malformed, expired
  const loggedIn = !!token && !invalid

  // Already-authenticated users shouldn't see the login page.
  if (pathname === '/login' && loggedIn) {
    return NextResponse.redirect(new URL('/dashboard', req.url))
  }

  // Protected route + no valid token → send to login.
  if (!isPublic(pathname) && !loggedIn) {
    const loginUrl = new URL('/login', req.url)
    loginUrl.searchParams.set('next', pathname)
    const res = NextResponse.redirect(loginUrl)
    // Kill any stale/garbage cookie so the browser doesn't keep sending it.
    if (token) res.cookies.delete('dm_token')
    return res
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
