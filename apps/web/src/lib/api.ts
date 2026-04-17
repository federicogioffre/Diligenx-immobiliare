import { getToken, clearAuth } from './auth'

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

export interface DealRead {
  id: number
  workspace_id: number
  title: string
  description: string | null
  value: number | null
  status: 'draft' | 'analyzing' | 'reviewed' | 'closed'
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

export interface RedFlagRead {
  id: number
  deal_id: number
  title: string
  description: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  category: string
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
  max_severity: 'low' | 'medium' | 'high' | 'critical'
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

function authHeaders(): HeadersInit {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/**
 * Handle an expired/invalid session response from the backend.
 *
 * Called by every authenticated fetch. If the backend returns 401 it means
 * the token is no longer accepted — clear auth state and force a full-page
 * redirect to /login. A hard redirect (not router.push) is intentional:
 * it wipes all client-side state that may still reference the dead session.
 *
 * NOTE: do NOT use this for `POST /auth/login` — a 401 there means "wrong
 * credentials", not "session expired", and should be surfaced as an error.
 */
function handle401IfNeeded(res: Response): boolean {
  if (res.status !== 401) return false
  if (typeof window !== 'undefined') {
    clearAuth()
    window.location.href = '/login'
  }
  return true
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...options.headers,
    },
    ...options,
  })
  if (handle401IfNeeded(res)) {
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
  },

  workspaces: {
    list(): Promise<WorkspaceRead[]> {
      return request('/workspaces')
    },
    create(name: string): Promise<WorkspaceRead> {
      return request('/workspaces', {
        method: 'POST',
        body: JSON.stringify({ name }),
      })
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
    getReport(id: number): Promise<ReportResponse> {
      return request(`/deals/${id}/report`)
    },
    generateReport(id: number): Promise<ReportResponse> {
      return request(`/deals/${id}/report`, { method: 'POST' })
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
      data: { title?: string; description?: string; value?: number | null }
    ): Promise<DealRead> {
      return request(`/deals/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      })
    },
    async delete(id: number): Promise<void> {
      const res = await fetch(`${BASE}/deals/${id}`, {
        method: 'DELETE',
        headers: { ...authHeaders() },
      })
      if (handle401IfNeeded(res)) throw new Error('Unauthorized')
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
        headers: { ...authHeaders() },
        body: form,
      })
      if (handle401IfNeeded(res)) throw new Error('Unauthorized')
      if (!res.ok) throw new Error(await res.text())
      return res.json()
    },
    async delete(documentId: number): Promise<void> {
      const res = await fetch(`${BASE}/documents/${documentId}`, {
        method: 'DELETE',
        headers: { ...authHeaders() },
      })
      if (handle401IfNeeded(res)) throw new Error('Unauthorized')
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
 * Auth is via ?token= query param because EventSource cannot send custom headers.
 *
 * @returns A cleanup function — call it to close the EventSource early.
 */
export function openAnalysisStream(
  dealId: number,
  onMessage: (payload: AnalysisStreamEvent) => void,
  onDone: () => void,
  onError: () => void,
): () => void {
  const token = getToken()
  // Bypass Next.js proxy — connect directly to FastAPI
  const base = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8001'
  const url = `${base}/deals/${dealId}/analysis-stream?token=${encodeURIComponent(token ?? '')}`
  const es = new EventSource(url)

  es.onmessage = (e) => {
    try {
      const payload: AnalysisStreamEvent = JSON.parse(e.data)
      onMessage(payload)
      // The server closes the stream when done; we mirror that on the client
      if (payload.deal_status !== 'analyzing') {
        es.close()
        onDone()
      }
    } catch {
      // malformed JSON — ignore
    }
  }

  es.onerror = () => {
    es.close()
    onError()
  }

  return () => es.close()
}
