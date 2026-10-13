// Edge middleware: server-side auth guard.
//
// Reads the `dm_token` cookie and redirects before any page is rendered.
// This eliminates the client-side flash of private content that would
// otherwise appear while React waits for a useEffect guard to fire.

import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { isTokenExpired } from '@/lib/auth'

const PUBLIC_PATHS = [
  '/',         // public marketing landing
  '/login',
  // Password reset — reached from an email link, necessarily unauthenticated.
  '/forgot-password',
  '/reset-password',
  // Compliance / legal pages — publicly accessible without auth.
  '/privacy',
  '/cookies',
  '/terms',
  '/dpa',
  '/security',
]
const IGNORED_PREFIXES = ['/_next', '/api', '/favicon', '/.well-known']
// Well-known crawler/SEO endpoints must stay publicly reachable — otherwise
// the auth guard redirects them to /login and reputation scanners see a
// login wall instead of the file.
const PUBLIC_FILES = ['/robots.txt', '/sitemap.xml']

function isPublic(path: string): boolean {
  return (
    PUBLIC_PATHS.includes(path) ||
    PUBLIC_FILES.includes(path) ||
    IGNORED_PREFIXES.some((p) => path.startsWith(p))
  )
}

// Rate limits on the API key on the client's address, but every /api call
// reaches the API from this server through the platform proxy, so the API
// would see one address for everybody. Tell it the browser's address, with a
// secret only this server and the API share (app/core/limiter.py); whatever a
// client sent under these names is dropped first.
const CLIENT_IP_HEADER = 'x-diligenx-client-ip'
const PROXY_SECRET_HEADER = 'x-diligenx-proxy-secret'

function forwardClientIp(req: NextRequest) {
  const headers = new Headers(req.headers)
  headers.delete(CLIENT_IP_HEADER)
  headers.delete(PROXY_SECRET_HEADER)
  const secret = process.env.PROXY_SHARED_SECRET
  // The edge in front of this server puts the peer it accepted the
  // connection from last, whether it appends or replaces, so the LAST entry
  // is the browser's address: earlier ones are whatever the client sent.
  const ip = (req.headers.get('x-forwarded-for') ?? '').split(',').pop()?.trim()
  if (secret && ip) {
    headers.set(CLIENT_IP_HEADER, ip)
    headers.set(PROXY_SECRET_HEADER, secret)
  }
  return NextResponse.next({ request: { headers } })
}

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl
  if (pathname.startsWith('/api/')) return forwardClientIp(req)
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
    // Kill any stale/garbage cookies so the browser doesn't keep sending
    // them (dm_authed too, or the landing-page CTA shows a ghost session).
    if (token) {
      res.cookies.delete('dm_token')
      res.cookies.delete('dm_authed')
    }
    return res
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
