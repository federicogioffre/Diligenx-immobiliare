export interface BlockedDocument {
  id: number
  filename: string
  status: string
  reason: string
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public detail?: unknown) {
    super(message)
    this.name = 'ApiError'
  }

  get code(): string | undefined {
    return isRecord(this.detail) && typeof this.detail.code === 'string' ? this.detail.code : undefined
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** Keep API diagnostics structured, and server JSON/HTML out of user messages. */
export function parseApiError(body: string, status: number): ApiError {
  let detail: unknown
  let message = `Richiesta non riuscita (HTTP ${status}). Riprova.`
  try {
    const parsed: unknown = JSON.parse(body)
    detail = isRecord(parsed) && 'detail' in parsed ? parsed.detail : parsed
    if (typeof detail === 'string' && detail.trim()) message = detail
    else if (isRecord(detail) && typeof detail.message === 'string' && detail.message.trim()) message = detail.message
  } catch {
    const plain = body.trim()
    if (plain && plain.length <= 300 && !/[<>{}\[\]]/.test(plain)) message = plain
  }
  if (message === 'All documents must finish processing successfully before analysis') {
    message = 'Prima di avviare l’analisi, completa l’elaborazione di tutti i documenti.'
  }
  return new ApiError(message, status, detail)
}

export function getBlockedDocuments(error: unknown): BlockedDocument[] {
  if (!(error instanceof ApiError) || error.code !== 'documents_not_ready' || !isRecord(error.detail)) return []
  const documents = error.detail.documents
  if (!Array.isArray(documents)) return []
  return documents.filter((doc): doc is BlockedDocument =>
    isRecord(doc) && typeof doc.id === 'number' && typeof doc.filename === 'string'
    && typeof doc.status === 'string' && typeof doc.reason === 'string',
  )
}
