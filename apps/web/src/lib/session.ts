import { api } from './api'
import { setWorkspaceId } from './auth'

/** After a sign-in: select the first workspace, creating one for a new account. */
export async function selectInitialWorkspace(): Promise<void> {
  const workspaces = await api.workspaces.list()
  if (workspaces.length > 0) {
    setWorkspaceId(workspaces[0].id)
  } else {
    const ws = await api.workspaces.create({ name: 'My Workspace' })
    setWorkspaceId(ws.id)
  }
}

/** A path on this site to continue to after sign-in; anything else → dashboard. */
export function safeNextPath(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) {
    return '/dashboard'
  }
  return value
}
