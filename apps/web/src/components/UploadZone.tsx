'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'

// ── Config ─────────────────────────────────────────────────────────────────

const ALLOWED_EXTENSIONS = /\.(pdf|txt|docx)$/i
const MAX_SIZE_BYTES = 50 * 1024 * 1024 // 50MB — matches backend MAX_UPLOAD_SIZE_MB
const CONCURRENCY = 3

// ── Types ──────────────────────────────────────────────────────────────────

type ItemStatus = 'queued' | 'uploading' | 'success' | 'failed' | 'invalid'

interface QueueItem {
  id: string
  file: File
  status: ItemStatus
  bytesSent: number
  bytesTotal: number
  error?: string
}

interface Props {
  dealId: number
  existingNames: string[]
  onUploaded: () => void
}

// ── Helpers ────────────────────────────────────────────────────────────────

function newId(): string {
  // crypto.randomUUID is available in all modern browsers
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function mkItem(file: File, status: ItemStatus, error?: string): QueueItem {
  return {
    id: newId(),
    file,
    status,
    bytesSent: 0,
    bytesTotal: file.size,
    error,
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Recursively walk a FileSystemEntry yielding every File inside it. */
async function* walkEntry(entry: FileSystemEntry): AsyncGenerator<File> {
  if (entry.isFile) {
    const fileEntry = entry as FileSystemFileEntry
    yield await new Promise<File>((resolve, reject) =>
      fileEntry.file(resolve, reject),
    )
    return
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    // readEntries returns max ~100 entries per call → loop until empty
    while (true) {
      const batch: FileSystemEntry[] = await new Promise((res, rej) =>
        reader.readEntries(res, rej),
      )
      if (batch.length === 0) break
      for (const child of batch) {
        yield* walkEntry(child)
      }
    }
  }
}

/** Flatten a DataTransfer into a list of Files, descending into directories. */
async function extractFiles(dt: DataTransfer): Promise<File[]> {
  const out: File[] = []
  const items = Array.from(dt.items)
  for (const item of items) {
    const entry = item.webkitGetAsEntry?.()
    if (entry) {
      for await (const file of walkEntry(entry)) out.push(file)
    } else if (item.kind === 'file') {
      const f = item.getAsFile()
      if (f) out.push(f)
    }
  }
  return out
}

// ── Component ──────────────────────────────────────────────────────────────

export default function UploadZone({ dealId, onUploaded }: Props) {
  const [items, setItems] = useState<QueueItem[]>([])
  const [isDragOver, setIsDragOver] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const runningRef = useRef(0) // concurrent uploads in flight — not in state to avoid re-renders

  const activeRef = useRef(new Map<string, AbortController>())

  const startUpload = useCallback(async (id: string, file: File, controller: AbortController) => {
    try {
      await api.documents.uploadWithProgress(dealId, file, (sent, total) => {
        setItems((prev) => prev.map((it) => it.id === id
          ? { ...it, bytesSent: sent, bytesTotal: total, error: undefined } : it))
      }, controller.signal, (seconds) => {
        setItems((prev) => prev.map((it) => it.id === id
          ? { ...it, error: `Attesa del server, nuovo tentativo tra ${seconds} secondi…` } : it))
      })
      setItems((prev) => prev.map((it) => it.id === id
        ? { ...it, status: 'success', bytesSent: it.bytesTotal, error: undefined } : it))
      onUploaded()
    } catch (err) {
      setItems((prev) => prev.map((it) => it.id === id
        ? { ...it, status: 'failed', error: err instanceof Error ? err.message : 'Upload fallito' } : it))
    } finally {
      runningRef.current--
      activeRef.current.delete(id)
    }
  }, [dealId, onUploaded])

  // Launch network work outside React state updater functions, which may be
  // evaluated more than once. The ref reserves slots before starting requests.
  useEffect(() => {
    for (const item of items) {
      if (runningRef.current >= CONCURRENCY) break
      if (item.status !== 'queued' || activeRef.current.has(item.id)) continue
      const controller = new AbortController()
      activeRef.current.set(item.id, controller)
      runningRef.current++
      setItems((prev) => prev.map((it) => it.id === item.id
        ? { ...it, status: 'uploading', bytesSent: 0, error: undefined } : it))
      void startUpload(item.id, item.file, controller)
    }
  }, [items, startUpload])

  useEffect(() => {
    const active = activeRef.current
    return () => { active.forEach((controller) => controller.abort()) }
  }, [])

  // ── Enqueue with validation ─────────────────────────────────────────────

  const enqueue = useCallback(
    (incoming: File[]) => {
      if (incoming.length === 0) return

      setItems((prev) => {
        const additions: QueueItem[] = []
        for (const file of incoming) {
          if (!ALLOWED_EXTENSIONS.test(file.name)) {
            additions.push(mkItem(file, 'invalid', 'Tipo non supportato'))
            continue
          }
          if (file.size > MAX_SIZE_BYTES) {
            additions.push(
              mkItem(file, 'invalid', `File troppo grande (>${MAX_SIZE_BYTES / 1024 / 1024}MB)`),
            )
            continue
          }
          // Names alone are not document identities (folders commonly repeat
          // them). The API deduplicates named content and safely resumes files
          // whose previous response or queue dispatch was interrupted.
          additions.push(mkItem(file, 'queued'))
        }
        return [...prev, ...additions]
      })

    },
    [],
  )

  // ── Event handlers ──────────────────────────────────────────────────────

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
  }
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    extractFiles(e.dataTransfer).then((files) => enqueue(files))
  }

  const handleFilePicker = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) enqueue(Array.from(e.target.files))
    e.target.value = '' // reset so picking the same file again re-fires change
  }

  const retry = (id: string) => {
    setItems((prev) =>
      prev.map((it) =>
        it.id === id && it.status === 'failed'
          ? { ...it, status: 'queued' as const, bytesSent: 0, error: undefined }
          : it,
      ),
    )
  }

  const remove = (id: string) => {
    setItems((prev) => prev.filter((it) => it.id !== id))
  }

  const clearCompleted = () => {
    setItems((prev) => prev.filter((it) => it.status !== 'success'))
  }

  // ── Derived stats ───────────────────────────────────────────────────────

  const stats = items.reduce(
    (acc, it) => {
      acc[it.status]++
      return acc
    },
    { queued: 0, uploading: 0, success: 0, failed: 0, invalid: 0 },
  )

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="mb-3">
      {/* Dropzone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`relative rounded-2xl border-2 border-dashed px-6 py-8 text-center transition-colors ${
          isDragOver
            ? 'border-blue-500 bg-blue-50'
            : 'border-slate-300 bg-white hover:border-slate-400'
        }`}
      >
        <svg
          className={`w-10 h-10 mx-auto mb-3 ${isDragOver ? 'text-blue-500' : 'text-slate-400'}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
          />
        </svg>
        <p className="text-sm text-slate-700 font-medium mb-1">
          {isDragOver
            ? 'Rilascia per caricare'
            : 'Trascina file o cartelle qui'}
        </p>
        <p className="text-xs text-slate-400 mb-4">
          oppure seleziona manualmente · PDF, DOCX, TXT · max 50 MB per file
        </p>

        <div className="flex items-center justify-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            Seleziona file
          </button>
          <button
            type="button"
            onClick={() => folderInputRef.current?.click()}
            className="inline-flex items-center gap-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 hover:border-slate-300 px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors"
          >
            <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
            Cartella
          </button>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.txt"
          multiple
          onChange={handleFilePicker}
          className="hidden"
        />
        <input
          ref={folderInputRef}
          type="file"
          multiple
          // @ts-expect-error non-standard attribute supported in all evergreen browsers
          webkitdirectory=""
          onChange={handleFilePicker}
          className="hidden"
        />
      </div>

      {/* Queue list */}
      {items.length > 0 && (
        <div className="mt-4 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-100">
            <div className="text-xs text-slate-500">
              {stats.uploading > 0 && <span>{stats.uploading} in caricamento · </span>}
              {stats.queued > 0 && <span>{stats.queued} in coda · </span>}
              {stats.success > 0 && <span className="text-emerald-600">{stats.success} caricati · </span>}
              {stats.failed > 0 && <span className="text-red-600">{stats.failed} falliti · </span>}
              {stats.invalid > 0 && <span className="text-slate-500">{stats.invalid} ignorati</span>}
            </div>
            {stats.success > 0 && (
              <button
                onClick={clearCompleted}
                className="text-xs text-slate-500 hover:text-slate-800 font-medium hover:bg-slate-50 px-2 py-1 rounded transition-colors"
              >
                Pulisci completati
              </button>
            )}
          </div>
          <ul>
            {items.map((it) => (
              <QueueRow key={it.id} item={it} onRetry={retry} onRemove={remove} />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ── Queue row ──────────────────────────────────────────────────────────────

function QueueRow({
  item,
  onRetry,
  onRemove,
}: {
  item: QueueItem
  onRetry: (id: string) => void
  onRemove: (id: string) => void
}) {
  const pct =
    item.bytesTotal > 0 ? Math.round((item.bytesSent / item.bytesTotal) * 100) : 0

  return (
    <li className="border-b border-slate-100 last:border-b-0 px-4 py-2.5">
      <div className="flex items-center gap-3">
        {/* Status icon */}
        <div className="shrink-0">
          {item.status === 'success' && (
            <svg className="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
          {item.status === 'failed' && (
            <svg className="w-4 h-4 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          )}
          {item.status === 'invalid' && (
            <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
            </svg>
          )}
          {(item.status === 'uploading' || item.status === 'queued') && (
            <div className={`w-4 h-4 rounded-full border-2 ${item.status === 'uploading' ? 'border-blue-500 border-t-transparent animate-spin' : 'border-slate-300'}`} />
          )}
        </div>

        {/* Name + meta */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-900 truncate">{item.file.name}</span>
            <span className="text-xs text-slate-400 shrink-0">{formatSize(item.file.size)}</span>
          </div>

          {item.status === 'uploading' && (
            <div className="mt-1.5 h-1 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-600 transition-all duration-150"
                style={{ width: `${pct}%` }}
              />
            </div>
          )}

          {(item.status === 'failed' || (item.status === 'uploading' && item.error)) && (
            <p className="text-xs text-red-600 mt-0.5 truncate" title={item.error}>
              {item.error}
            </p>
          )}

          {item.status === 'invalid' && (
            <p className="text-xs text-slate-500 mt-0.5 truncate">{item.error}</p>
          )}
        </div>

        {/* Right-hand actions / labels */}
        <div className="shrink-0 flex items-center gap-2">
          {item.status === 'uploading' && (
            <span className="text-xs font-medium text-blue-600 tabular-nums">{pct}%</span>
          )}
          {item.status === 'queued' && (
            <span className="text-xs text-slate-400">in coda</span>
          )}
          {item.status === 'failed' && (
            <button
              onClick={() => onRetry(item.id)}
              className="text-xs text-blue-600 hover:text-blue-700 font-semibold px-2 py-0.5 rounded hover:bg-blue-50 transition-colors"
            >
              Riprova
            </button>
          )}
          {(item.status === 'success' || item.status === 'failed' || item.status === 'invalid') && (
            <button
              onClick={() => onRemove(item.id)}
              className="text-slate-300 hover:text-slate-600 p-1 rounded hover:bg-slate-100 transition-colors"
              title="Rimuovi dalla lista"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </li>
  )
}
