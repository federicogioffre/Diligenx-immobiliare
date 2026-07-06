// Auth state + JWT utilities.
//
// The session JWT lives in an HttpOnly cookie (`dm_token`) set by the
// backend at login — client JS can neither read nor delete it, which is the
// point: an XSS cannot exfiltrate the session. All API calls go through the
// same-origin /api proxy, so the browser attaches the cookie automatically.
//
// Client JS only manages two non-sensitive cookies:
//   - `dm_authed`  — a "1" flag mirroring the session lifetime, set by the
//                    backend, used purely as a UX signal (isLoggedIn()).
//   - `dm_workspace` — the currently selected workspace id.
//
// The Next.js middleware (server-side) still reads `dm_token` directly —
// HttpOnly only hides a cookie from client JS, not from the server.

const AUTHED_FLAG_KEY = 'dm_authed'
const LEGACY_TOKEN_KEY = 'dm_token'
const WORKSPACE_KEY = 'dm_workspace'
const COOKIE_MAX_AGE = 60 * 60 * 24 * 7 // 7 days (upper bound; JWT `exp` wins)

// ── Cookie helpers (client-side only) ──────────────────────────────────────

function setCookie(name: string, value: string, maxAge: number): void {
  if (typeof document === 'undefined') return
  const secure = location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAge}; SameSite=Lax${secure}`
}

function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return match ? decodeURIComponent(match[1]) : null
}

function deleteCookie(name: string): void {
  if (typeof document === 'undefined') return
  document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Lax`
}

// ── JWT helpers (edge-safe: only atob + JSON.parse) ────────────────────────

/**
 * Parse a JWT payload. Returns null if the token is NOT a well-formed JWT
 * (wrong number of segments, invalid base64, invalid JSON). A JWT without
 * an `exp` claim is still considered "parseable" and returns the payload.
 *
 * Safe to call from Next.js edge runtime (middleware).
 */
function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const json = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'))
    const parsed = JSON.parse(json)
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}

/**
 * Decode the `exp` claim of a JWT and return it in milliseconds.
 * Returns null if the token is malformed OR has no numeric `exp`.
 *
 * Exposed so the edge middleware can read expiry without importing
 * the rest of this module's browser-only helpers.
 */
export function decodeJwtExpiry(token: string): number | null {
  const payload = parseJwtPayload(token)
  if (!payload) return null
  return typeof payload.exp === 'number' ? (payload.exp as number) * 1000 : null
}

/**
 * A token is considered expired when:
 *   - it is missing, empty, or not a well-formed JWT (→ treat as invalid)
 *   - it has an `exp` claim in the past
 * A well-formed JWT without `exp` is treated as non-expiring.
 */
export function isTokenExpired(token: string | null): boolean {
  if (!token) return true
  const payload = parseJwtPayload(token)
  if (!payload) return true // malformed ⇒ invalid ⇒ expired
  const exp = payload.exp
  if (typeof exp !== 'number') return false // well-formed, no exp ⇒ valid
  return Date.now() >= exp * 1000
}

// ── Public API ──────────────────────────────────────────────────────────────

export function getWorkspaceId(): number {
  return Number(getCookie(WORKSPACE_KEY) ?? '0')
}

export function setWorkspaceId(id: number): void {
  setCookie(WORKSPACE_KEY, String(id), COOKIE_MAX_AGE)
}

/**
 * End the session. MUST be awaited before navigating: only the backend can
 * delete the HttpOnly session cookie, and navigating away can abort the
 * in-flight request, leaving the browser "still logged in".
 */
export async function clearAuth(): Promise<void> {
  try {
    await fetch('/api/auth/logout', { method: 'POST' })
  } catch {
    // Network failure: fall through — the JS-visible cookies are cleared
    // below and the middleware will bounce once the session cookie expires.
  }
  deleteCookie(AUTHED_FLAG_KEY)
  deleteCookie(WORKSPACE_KEY)
}

/**
 * UX-only signal — the real gate is the backend (and the middleware for
 * page routing). The legacy check covers sessions created before the
 * HttpOnly migration, whose `dm_token` is still JS-readable.
 */
export function isLoggedIn(): boolean {
  if (getCookie(AUTHED_FLAG_KEY) === '1') return true
  const legacy = getCookie(LEGACY_TOKEN_KEY)
  return !!legacy && !isTokenExpired(legacy)
}
