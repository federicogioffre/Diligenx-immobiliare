const TOKEN_KEY = 'dm_token'
const WORKSPACE_KEY = 'dm_workspace'

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function getWorkspaceId(): number {
  if (typeof window === 'undefined') return 0
  return Number(localStorage.getItem(WORKSPACE_KEY) ?? '0')
}

export function setWorkspaceId(id: number): void {
  localStorage.setItem(WORKSPACE_KEY, String(id))
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(WORKSPACE_KEY)
}

export function isLoggedIn(): boolean {
  return !!getToken()
}
