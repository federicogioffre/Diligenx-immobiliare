'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { api, WorkspaceRead } from '@/lib/api'
import { getWorkspaceId, setWorkspaceId } from '@/lib/auth'

// ── Types ──────────────────────────────────────────────────────────────────

type Mode =
  | { kind: 'list' }
  | { kind: 'creating' }
  | { kind: 'renaming'; id: number }

// ── Component ──────────────────────────────────────────────────────────────

export default function WorkspaceSwitcher() {
  const [workspaces, setWorkspaces] = useState<WorkspaceRead[]>([])
  const [activeId, setActiveId] = useState<number>(0)
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>({ kind: 'list' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [draftName, setDraftName] = useState('')

  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // ── Initial load ────────────────────────────────────────────────────────

  useEffect(() => {
    let alive = true
    api.workspaces
      .list()
      .then((list) => {
        if (!alive) return
        setWorkspaces(list)
        const stored = getWorkspaceId()
        // Recover gracefully if the cookie points to a workspace that no
        // longer exists (deleted in another tab, etc.)
        const active = list.find((w) => w.id === stored) ?? list[0]
        if (active) {
          setActiveId(active.id)
          if (active.id !== stored) setWorkspaceId(active.id)
        }
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : 'Errore')
      })
    return () => {
      alive = false
    }
  }, [])

  // ── Click outside to close ──────────────────────────────────────────────

  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setMode({ kind: 'list' })
        setError('')
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  // ── Autofocus inline input when entering create/rename mode ─────────────

  useEffect(() => {
    if (mode.kind !== 'list') inputRef.current?.focus()
  }, [mode])

  // ── Actions ─────────────────────────────────────────────────────────────

  const switchTo = useCallback((id: number) => {
    if (id === activeId) return
    setWorkspaceId(id)
    // Full reload: ensures the dashboard (and any other page that reads the
    // workspace cookie) refetches against the new workspace cleanly.
    window.location.reload()
  }, [activeId])

  async function handleCreate() {
    const name = draftName.trim()
    if (!name || busy) return
    setBusy(true)
    setError('')
    try {
      const ws = await api.workspaces.create({ name })
      setWorkspaces((prev) => [...prev, ws])
      setDraftName('')
      setMode({ kind: 'list' })
      toast.success(`Workspace "${ws.name}" creato`)
      switchTo(ws.id) // triggers reload
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Errore')
    } finally {
      setBusy(false)
    }
  }

  async function handleRename(id: number) {
    const name = draftName.trim()
    if (!name || busy) return
    setBusy(true)
    setError('')
    try {
      const updated = await api.workspaces.update(id, { name })
      setWorkspaces((prev) => prev.map((w) => (w.id === id ? updated : w)))
      setDraftName('')
      setMode({ kind: 'list' })
      toast.success('Workspace rinominato')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Errore')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(ws: WorkspaceRead) {
    if (busy) return
    if (!confirm(`Eliminare "${ws.name}"? L'azione è irreversibile.`)) return
    setBusy(true)
    setError('')
    try {
      await api.workspaces.delete(ws.id)
      const remaining = workspaces.filter((w) => w.id !== ws.id)
      setWorkspaces(remaining)
      toast.success(`Workspace "${ws.name}" eliminato`)
      // If the deleted one was active, switch to the first remaining and reload
      if (ws.id === activeId && remaining.length > 0) {
        switchTo(remaining[0].id) // triggers reload
      }
    } catch (err: unknown) {
      // Parse a few common backend errors to Italian
      const raw = err instanceof Error ? err.message : 'Errore'
      let msg = raw
      try {
        const parsed = JSON.parse(raw) as { detail?: string }
        if (parsed.detail) msg = parsed.detail
      } catch {
        /* raw message */
      }
      if (msg.toLowerCase().includes('last workspace')) {
        msg = 'Non puoi eliminare il tuo ultimo workspace.'
      } else if (msg.toLowerCase().includes('deal')) {
        msg = `Il workspace contiene deal. Eliminali prima di eliminare il workspace.`
      }
      setError(msg)
    } finally {
      setBusy(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────

  const active = workspaces.find((w) => w.id === activeId)
  const inputClass =
    'w-full border border-slate-200 rounded-md px-2.5 py-1.5 text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white'

  // While still loading, render a placeholder so the NavBar layout doesn't jump
  if (workspaces.length === 0 && !error) {
    return <div className="w-40 max-w-full h-8" aria-hidden />
  }

  return (
    <div className="relative min-w-0" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-sm text-slate-700 hover:text-slate-900 font-medium px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors border border-slate-200 bg-white shadow-sm w-full max-w-[16rem]"
      >
        <svg className="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
        <span className="truncate">{active?.name ?? 'Seleziona workspace'}</span>
        <svg className={`w-3.5 h-3.5 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 md:left-0 md:right-auto top-full mt-2 w-72 max-w-[calc(100vw-2rem)] bg-white rounded-xl border border-slate-200 shadow-lg z-40 overflow-hidden">
          {/* List */}
          <ul className="py-1 max-h-72 overflow-y-auto">
            {workspaces.map((ws) => {
              const isActive = ws.id === activeId
              const renaming = mode.kind === 'renaming' && mode.id === ws.id
              return (
                <li key={ws.id} className="group">
                  {renaming ? (
                    <div className="px-3 py-2 flex items-center gap-2">
                      <input
                        ref={inputRef}
                        value={draftName}
                        onChange={(e) => setDraftName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleRename(ws.id)
                          if (e.key === 'Escape') {
                            setMode({ kind: 'list' })
                            setDraftName('')
                            setError('')
                          }
                        }}
                        disabled={busy}
                        className={inputClass}
                      />
                      <button
                        onClick={() => handleRename(ws.id)}
                        disabled={busy}
                        className="text-xs text-blue-600 hover:text-blue-700 font-semibold disabled:opacity-50"
                      >
                        {busy ? '…' : 'Salva'}
                      </button>
                    </div>
                  ) : (
                    <div
                      className={`flex items-center gap-2 px-3 py-2 text-sm cursor-pointer ${
                        isActive ? 'bg-blue-50' : 'hover:bg-slate-50'
                      }`}
                      onClick={() => switchTo(ws.id)}
                    >
                      <span className={`flex-1 truncate ${isActive ? 'font-semibold text-slate-900' : 'text-slate-700'}`}>
                        {ws.name}
                      </span>
                      {isActive && (
                        <svg className="w-4 h-4 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setDraftName(ws.name)
                          setMode({ kind: 'renaming', id: ws.id })
                          setError('')
                        }}
                        className="opacity-0 group-hover:opacity-100 text-xs text-slate-400 hover:text-slate-700 px-1.5 py-0.5 rounded transition-opacity"
                        title="Rinomina"
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDelete(ws)
                        }}
                        className="opacity-0 group-hover:opacity-100 text-xs text-slate-400 hover:text-red-600 px-1.5 py-0.5 rounded transition-opacity"
                        title="Elimina"
                      >
                        🗑
                      </button>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>

          {/* Create */}
          <div className="border-t border-slate-100 p-2">
            {mode.kind === 'creating' ? (
              <div className="flex items-center gap-2">
                <input
                  ref={inputRef}
                  value={draftName}
                  onChange={(e) => setDraftName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleCreate()
                    if (e.key === 'Escape') {
                      setMode({ kind: 'list' })
                      setDraftName('')
                      setError('')
                    }
                  }}
                  placeholder="Nome nuovo workspace"
                  disabled={busy}
                  className={inputClass}
                />
                <button
                  onClick={handleCreate}
                  disabled={busy || !draftName.trim()}
                  className="text-xs text-blue-600 hover:text-blue-700 font-semibold disabled:opacity-50"
                >
                  {busy ? '…' : 'Crea'}
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setDraftName('')
                  setMode({ kind: 'creating' })
                  setError('')
                }}
                className="flex items-center gap-2 w-full px-2 py-1.5 text-sm text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-md transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                Nuovo workspace
              </button>
            )}
          </div>

          {error && (
            <div className="border-t border-red-100 px-3 py-2 text-xs text-red-600 bg-red-50">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
