// Auth storage + JWT utilities.
//
// Storage lives in cookies (not localStorage) so the Next.js middleware —
// which runs on the edge and cannot read localStorage — can read the token
// and guard protected routes server-side before any content is rendered.
//
// Cookies are intentionally NOT HttpOnly because the JS still needs to read
// the token to set the `Authorization: Bearer` header on API calls. The
// backend is unchanged.

const TOKEN_KEY = 'dm_token'
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

// ── Public API (unchanged signatures) ──────────────────────────────────────

export function getToken(): string | null {
  return getCookie(TOKEN_KEY)
}

export function setToken(token: string): void {
  setCookie(TOKEN_KEY, token, COOKIE_MAX_AGE)
}

export function clearToken(): void {
  deleteCookie(TOKEN_KEY)
}

export function getWorkspaceId(): number {
  return Number(getCookie(WORKSPACE_KEY) ?? '0')
}

export function setWorkspaceId(id: number): void {
  setCookie(WORKSPACE_KEY, String(id), COOKIE_MAX_AGE)
}

export function clearAuth(): void {
  deleteCookie(TOKEN_KEY)
  deleteCookie(WORKSPACE_KEY)
}

export function isLoggedIn(): boolean {
  const t = getToken()
  return !!t && !isTokenExpired(t)
}
