import { clearAuth } from './auth'

const BASE = '/api'

// ── Types ──────────────────────────────────────────────────────────────────

export interface Token {
  access_token: string
  token_type: string
}

export interface UserRead {
  id: number
  email: string
  full_name: string | null
  is_active: boolean
  created_at: string
}

export interface WorkspaceRead {
  id: number
  name: string
  description: string | null
  owner_id: number
  created_at: string
}

export interface CategoryCount {
  category: string
  count: number
}

export interface WorkspaceInsights {
  workspace_id: number
  deals_total: number
  deals_by_status: Record<'draft' | 'analyzing' | 'reviewed' | 'closed', number>
  red_flags_total: number
  red_flags_by_severity: Record<'low' | 'medium' | 'high', number>
  top_red_flag_categories: CategoryCount[]
  deals_analyzed: number
  deals_with_missing_documents: number
}

export interface DealRead {
  id: number
  workspace_id: number
  title: string
  description: string | null
  value: number | null
  status: 'draft' | 'analyzing' | 'reviewed' | 'closed'
  report_language: 'it' | 'en' | null
  created_at: string
  updated_at: string | null
}

export interface DealAnalysisResponse {
  deal_id: number
  status: string
  completed: boolean
  documents_analyzed: number
  clause_findings_count: number
  red_flags_count: number
  open_questions_count: number
  report_id: number | null
  stages: Record<string, unknown> | null
}

export interface AgentRunRead {
  id: number
  deal_id: number
  document_id: number | null
  agent_name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  error_message: string | null
  input_hash: string | null
  created_at: string
}

export interface ClauseFindingRead {
  id: number
  document_id: number
  clause_type: string
  title: string
  content: string
  page_number: number | null
  confidence: number | null
  relevance_score: 'high' | 'medium' | 'low' | null
  relevance_reason: string | null
  created_at: string
}

export type DueDiligenceArea =
  | 'corporate'
  | 'indebtedness'
  | 'real_estate'
  | 'employees'
  | 'suppliers_customers'
  | 'insurance'
  | 'litigation'
  | 'ip_it'
  | 'data_protection'
  | 'financial'
  | 'tax'
  | 'other'

export interface RedFlagRead {
  id: number
  deal_id: number
  title: string
  // Issue / Risk / Recommendation triple — mirrors professional DD reports.
  issue: string
  risk: string | null
  recommendation: string | null
  severity: 'low' | 'medium' | 'high'
  area: DueDiligenceArea | null
  category: string
  confidence: number | null
  source_document_id: number | null
  source_page: number | null
  // remedy_type: the instrument that answers the finding. impact: what it
  // hits. Both null where the analysis did not tag the flag.
  remedy_type:
    | 'indemnity'
    | 'warranty'
    | 'price_adjustment'
    | 'earn_out'
    | 'condition_precedent'
    | 'pre_closing_verification'
    | 'post_closing_action'
    | 'information_request'
    | null
  impact: 'value' | 'spa' | 'other' | null
  structured_payload_json: {
    amount_eur?: number
    fiscal_years?: number[]
    severity_floored?: boolean
  } | null
  created_at: string
}

export type Priority = 'low' | 'medium' | 'high'

export interface OpenQuestionRead {
  id: number
  deal_id: number
  document_id: number | null
  agent_name: string
  question: string
  priority: Priority
  status: 'open' | 'resolved'
  created_at: string
}

export interface MissingDocumentRead {
  id: number
  deal_id: number
  document_category: string
  expected_item: string
  reason: string
  priority: Priority
  created_at: string
}

export interface CompanyProfileRead {
  id: number
  deal_id: number
  company_name: string
  legal_form: string | null
  incorporation_date: string | null
  registered_office: string | null
  corporate_capital: string | null
  shareholders: string | null
  pledge: string | null
  managing_body: string | null
  auditors: string | null
  auditing_company: string | null
  business: string | null
  fiscal_year: string | null
  duration: string | null
  confidence: number | null
  source_document_id: number | null
  created_at: string
}

export interface DocumentRead {
  id: number
  deal_id: number
  filename: string
  mime_type: string
  file_size: number
  status: 'pending' | 'processing' | 'processed' | 'failed'
  page_count: number | null
  language: string | null
  created_at: string
}

export interface DocumentUploadResponse {
  id: number
  filename: string
  status: string
  file_size: number
  language: string | null
}

export interface ReportResponse {
  report_id: number
  deal_id: number
  markdown: string
}

export interface QASource {
  document_id: number
  page_number: number | null
  excerpt: string
}

export interface QAResponse {
  answer: string
  sources: QASource[]
}

export interface CategoryImpact {
  category: string
  count: number
  impact: number
  max_severity: 'low' | 'medium' | 'high'
}

export interface RiskScoreResponse {
  deal_id: number
  score: number        // 0–100
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  deductions: {
    red_flags:            { count: number; impact: number }
    observations:         { count: number; impact: number }
    information_requests: { count: number; impact: number }
    missing_documents:    { count: number; impact: number }
  }
  categories: CategoryImpact[]
}

export interface AnalysisStageEvent {
  agent_name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  error_message: string | null
}

export interface AnalysisStreamEvent {
  deal_status: 'draft' | 'analyzing' | 'reviewed' | 'closed'
  stages: AnalysisStageEvent[]
}

// ── Helpers ────────────────────────────────────────────────────────────────
//
// Auth travels in the HttpOnly session cookie set by the backend at login.
// Every call below goes through the same-origin /api proxy, so the browser
// attaches the cookie automatically — no Authorization header needed.

/**
 * Handle an expired/invalid session response from the backend.
 *
 * Called by every authenticated fetch. If the backend returns 401 it means
 * the session is no longer accepted — clear auth state and force a full-page
 * redirect to /login. A hard redirect (not router.push) is intentional:
 * it wipes all client-side state that may still reference the dead session.
 *
 * MUST be awaited: only the backend logout can delete the HttpOnly session
 * cookie. If we redirected first, the middleware would still see the (dead
 * but unexpired-looking) cookie on /login and bounce back to /dashboard,
 * whose API calls 401 again — an infinite loop.
 *
 * NOTE: do NOT use this for `POST /auth/login` — a 401 there means "wrong
 * credentials", not "session expired", and should be surfaced as an error.
 */
async function handle401IfNeeded(res: Response): Promise<boolean> {
  if (res.status !== 401) return false
  if (typeof window !== 'undefined') {
    await clearAuth()
    window.location.href = '/login'
  }
  return true
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })
  if (await handle401IfNeeded(res)) {
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json()
}

// ── API client ─────────────────────────────────────────────────────────────

export const api = {
  auth: {
    async login(email: string, password: string): Promise<Token> {
      const body = new URLSearchParams({ username: email, password })
      const res = await fetch(`${BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
      })
      if (!res.ok) throw new Error(await res.text())
      return res.json()
    },

    register(data: {
      email: string
      password: string
      full_name?: string
    }): Promise<UserRead> {
      return request('/auth/register', {
        method: 'POST',
        body: JSON.stringify(data),
      })
    },

    /** Start the password-reset flow. Always resolves (202) — the backend
     *  never reveals whether the address exists. */
    async forgotPassword(email: string): Promise<void> {
      const res = await fetch(`${BASE}/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      if (!res.ok) throw new Error(await res.text())
    },

    /** Complete the reset with the token from the email link. */
    async resetPassword(token: string, newPassword: string): Promise<void> {
      const res = await fetch(`${BASE}/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: newPassword }),
      })
      if (res.status === 400) throw new Error('Link non valido o scaduto. Richiedi un nuovo link.')
      if (res.status === 422) throw new Error('La password deve avere almeno 8 caratteri.')
      if (!res.ok) throw new Error(await res.text())
    },
  },

  users: {
    me(): Promise<UserRead> {
      return request('/users/me')
    },
    /** GDPR art. 20 — full structured export, returned as a Blob to download. */
    async exportData(): Promise<Blob> {
      const res = await fetch(`${BASE}/users/me/export`)
      if (await handle401IfNeeded(res)) throw new Error('Unauthorized')
      if (!res.ok) throw new Error(await res.text())
      return res.blob()
    },
    /** GDPR art. 17 — erase the account. Requires the password as a
     *  deliberate-action check; 403 means wrong password. */
    async deleteAccount(password: string): Promise<void> {
      const res = await fetch(`${BASE}/users/me`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (res.status === 403) throw new Error('Password errata')
      if (await handle401IfNeeded(res)) throw new Error('Unauthorized')
      if (!res.ok) throw new Error(await res.text())
    },
  },

  workspaces: {
    list(): Promise<WorkspaceRead[]> {
      return request('/workspaces')
    },
    get(id: number): Promise<WorkspaceRead> {
      return request(`/workspaces/${id}`)
    },
    create(data: { name: string; description?: string }): Promise<WorkspaceRead> {
      return request('/workspaces', {
        method: 'POST',
        body: JSON.stringify(data),
      })
    },
    update(
      id: number,
      data: { name?: string; description?: string }
    ): Promise<WorkspaceRead> {
      return request(`/workspaces/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      })
    },
    async delete(id: number): Promise<void> {
      const res = await fetch(`${BASE}/workspaces/${id}`, { method: 'DELETE' })
      if (await handle401IfNeeded(res)) throw new Error('Unauthorized')
      if (!res.ok) throw new Error(await res.text())
    },
    insights(id: number): Promise<WorkspaceInsights> {
      return request(`/workspaces/${id}/insights`)
    },
  },

  deals: {
    list(workspaceId: number): Promise<DealRead[]> {
      return request(`/deals?workspace_id=${workspaceId}`)
    },
    create(
      workspaceId: number,
      data: { title: string; description?: string; value?: number }
    ): Promise<DealRead> {
      return request(`/deals?workspace_id=${workspaceId}`, {
        method: 'POST',
        body: JSON.stringify(data),
      })
    },
    get(id: number): Promise<DealRead> {
      return request(`/deals/${id}`)
    },
    analyze(id: number): Promise<DealAnalysisResponse> {
      return request(`/deals/${id}/analyze`, { method: 'POST' })
    },
    agentRuns(id: number): Promise<AgentRunRead[]> {
      return request(`/deals/${id}/agent-runs`)
    },
    clauseFindings(id: number): Promise<ClauseFindingRead[]> {
      return request(`/deals/${id}/clause-findings`)
    },
    redFlags(id: number): Promise<RedFlagRead[]> {
      return request(`/deals/${id}/red-flags`)
    },
    openQuestions(id: number): Promise<OpenQuestionRead[]> {
      return request(`/deals/${id}/open-questions`)
    },
    missingDocuments(id: number): Promise<MissingDocumentRead[]> {
      return request(`/deals/${id}/missing-documents`)
    },
    companyProfiles(id: number): Promise<CompanyProfileRead[]> {
      return request(`/deals/${id}/company-profiles`)
    },
    getReport(id: number): Promise<ReportResponse> {
      return request(`/deals/${id}/report`)
    },
    generateReport(id: number): Promise<ReportResponse> {
      return request(`/deals/${id}/report`, { method: 'POST' })
    },
    async downloadReport(id: number, format: 'pdf' | 'docx'): Promise<Blob> {
      const res = await fetch(`${BASE}/deals/${id}/report/export?format=${format}`)
      if (await handle401IfNeeded(res)) throw new Error('Unauthorized')
      if (!res.ok) throw new Error(await res.text())
      return res.blob()
    },
    getRiskScore(id: number): Promise<RiskScoreResponse> {
      return request(`/deals/${id}/risk-score`)
    },
    ask(id: number, question: string): Promise<QAResponse> {
      return request(`/deals/${id}/ask`, {
        method: 'POST',
        body: JSON.stringify({ question }),
      })
    },
    update(
      id: number,
      data: {
        title?: string
        description?: string
        value?: number | null
        report_language?: 'it' | 'en' | 'auto'
      }
    ): Promise<DealRead> {
      return request(`/deals/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      })
    },
    async delete(id: number): Promise<void> {
      const res = await fetch(`${BASE}/deals/${id}`, { method: 'DELETE' })
      if (await handle401IfNeeded(res)) throw new Error('Unauthorized')
      if (!res.ok) throw new Error(await res.text())
    },
  },

  documents: {
    list(dealId: number): Promise<DocumentRead[]> {
      return request(`/documents/deals/${dealId}/documents`)
    },
    async upload(dealId: number, file: File): Promise<DocumentUploadResponse> {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`${BASE}/documents/upload?deal_id=${dealId}`, {
        method: 'POST',
        body: form,
      })
      if (await handle401IfNeeded(res)) throw new Error('Unauthorized')
      if (!res.ok) throw new Error(await res.text())
      return res.json()
    },
    /**
     * Upload a single file with byte-level progress callbacks.
     *
     * Uses XMLHttpRequest because `fetch` does not expose upload progress
     * events (there is no stream-progress on the request body).
     * The on-wire behaviour is identical to `upload()` — same endpoint,
     * same FormData payload, same 401 → redirect contract.
     */
    async uploadWithProgress(
      dealId: number,
      file: File,
      onProgress: (bytesSent: number, bytesTotal: number) => void,
      signal?: AbortSignal,
      onRetry?: (seconds: number) => void,
    ): Promise<DocumentUploadResponse> {
      // The server identifies repeated named file content, so a timeout after
      // saving the file is safe to retry. Do not retry validation/auth errors.
      const attemptUpload = () => new Promise<DocumentUploadResponse>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${BASE}/documents/upload?deal_id=${dealId}`)
        xhr.timeout = 120_000
        const abort = () => xhr.abort()
        const fail = (message: string, retryable: boolean, retryAfter = 0) =>
          reject(Object.assign(new Error(message), { retryable, retryAfter }))
        xhr.onloadend = () => signal?.removeEventListener('abort', abort)
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) onProgress(event.loaded, event.total)
        }
        xhr.onload = () => {
          if (xhr.status === 401) {
            if (typeof window !== 'undefined') {
              clearAuth().finally(() => { window.location.href = '/login' })
            }
            fail('Unauthorized', false)
            return
          }
          if (xhr.status >= 200 && xhr.status < 300) {
            try { resolve(JSON.parse(xhr.responseText) as DocumentUploadResponse) }
            catch { fail('Risposta non valida dal server', true) }
            return
          }
          const header = xhr.getResponseHeader('Retry-After')
          const retryAfter = header
            ? (/^\d+$/.test(header) ? Number(header) * 1000 : Math.max(0, Date.parse(header) - Date.now()))
            : 0
          let message = `Caricamento non riuscito (HTTP ${xhr.status})`
          try { message = JSON.parse(xhr.responseText).detail || message } catch { /* keep concise message */ }
          fail(message, [408, 429, 500, 502, 503, 504].includes(xhr.status), retryAfter)
        }
        xhr.onerror = () => fail('Connessione interrotta durante il caricamento', true)
        xhr.ontimeout = () => fail('Tempo di caricamento scaduto', true)
        xhr.onabort = () => fail('Upload annullato', false)
        if (signal?.aborted) { fail('Upload annullato', false); return }
        signal?.addEventListener('abort', abort, { once: true })
        const form = new FormData()
        form.append('file', file)
        xhr.send(form)
      })
      for (let attempt = 0; ; attempt++) {
        try { return await attemptUpload() }
        catch (error) {
          const failure = error as Error & { retryable?: boolean; retryAfter?: number }
          if (!failure.retryable || signal?.aborted || attempt >= 4) throw error
          const delay = Math.min(120_000, Math.max(failure.retryAfter || 0, 2000 * 2 ** attempt) + Math.random() * 1000)
          onRetry?.(Math.ceil(delay / 1000))
          await new Promise<void>((resolve, reject) => {
            const abort = () => {
              clearTimeout(timer)
              reject(new Error('Upload annullato'))
            }
            const timer = setTimeout(() => {
              signal?.removeEventListener('abort', abort)
              resolve()
            }, delay)
            if (signal?.aborted) abort()
            else signal?.addEventListener('abort', abort, { once: true })
          })
        }
      }
    },
    async delete(documentId: number): Promise<void> {
      const res = await fetch(`${BASE}/documents/${documentId}`, { method: 'DELETE' })
      if (await handle401IfNeeded(res)) throw new Error('Unauthorized')
      if (!res.ok) throw new Error(await res.text())
    },
  },
}

/**
 * Open a Server-Sent Events connection to the analysis-stream endpoint.
 *
 * Connects directly to the FastAPI server (not via the Next.js proxy) because
 * Next.js rewrites buffer the full response before forwarding, which breaks SSE.
 *
 * Auth: EventSource cannot send headers and the direct connection is
 * cross-origin (no session cookie), so we first obtain a short-lived,
 * deal-scoped ticket from the backend (cookie-authenticated, via the proxy)
 * and pass it as a query param. The ticket expires in seconds and grants
 * nothing beyond this one stream — the session JWT never appears in a URL.
 *
 * @returns A cleanup function — call it to close the EventSource early.
 *          Safe to call while the ticket fetch is still in flight.
 */
export function openAnalysisStream(
  dealId: number,
  onMessage: (payload: AnalysisStreamEvent) => void,
  onDone: () => void,
  onError: () => void,
): () => void {
  let cancelled = false
  let es: EventSource | null = null

  request<{ ticket: string }>(`/deals/${dealId}/stream-ticket`, { method: 'POST' })
    .then(({ ticket }) => {
      if (cancelled) return
      // Bypass Next.js proxy — connect directly to FastAPI
      const base = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
      es = new EventSource(
        `${base}/deals/${dealId}/analysis-stream?ticket=${encodeURIComponent(ticket)}`,
      )

      es.onmessage = (e) => {
        try {
          const payload: AnalysisStreamEvent = JSON.parse(e.data)
          onMessage(payload)
          // The server closes the stream when done; we mirror that on the client
          if (payload.deal_status !== 'analyzing') {
            es?.close()
            onDone()
          }
        } catch {
          // malformed JSON — ignore
        }
      }

      es.onerror = () => {
        es?.close()
        onError()
      }
    })
    .catch(() => {
      // Ticket fetch failed — callers fall back to polling.
      if (!cancelled) onError()
    })

  return () => {
    cancelled = true
    es?.close()
  }
}

