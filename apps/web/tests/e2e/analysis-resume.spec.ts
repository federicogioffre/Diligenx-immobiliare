import { test, expect, Page } from '@playwright/test'
import type { AgentRunRead, AnalysisBatchProgress, AnalysisStreamEvent, DealRead } from '../../src/lib/api'

const AGENTS = ['intake', 'document_router', 'contract_analysis', 'corporate_governance',
  'corporate_intro_extraction', 'tax_analysis', 'financial_analysis', 'red_flag_aggregation', 'report_generation']
const START = Date.parse('2026-09-18T06:30:00Z')

function runs(finance: 'running' | 'failed' | 'completed' = 'failed'): AgentRunRead[] {
  return AGENTS.map((agent_name, index) => {
    const old = index > 6
    const started = old ? START - 86_400_000 : START + index * 60_000
    const status = index === 6 ? finance : 'completed'
    return {
      id: index + 1, deal_id: 4, document_id: null, agent_name, status,
      started_at: new Date(started).toISOString(),
      completed_at: status === 'running' ? null : new Date(started + 30_000).toISOString(),
      duration_seconds: status === 'running' ? null : old ? 999 : 30,
      error_message: status === 'failed' ? 'Analisi interrotta per tempo massimo. Le fasi completate sono state conservate.' : null,
      input_hash: index === 0 ? 'checkpoint' : null,
      created_at: new Date(started).toISOString(),
    }
  })
}

function progress(completed: number): AnalysisBatchProgress {
  return { agent_name: 'financial_analysis', run_id: 7, completed_batches: completed,
    total_batches: 120, document_id: 2, updated_at: '2026-09-18T07:00:00Z' }
}

interface MockStream {
  onmessage: ((event: { data: string }) => void) | null
  onerror: (() => void) | null
  close: () => void
}
type MockWindow = Window & { analysisTestStream?: MockStream }

async function prepare(page: Page, initialStatus: DealRead['status'] = 'draft') {
  const state = { status: initialStatus, runs: runs(initialStatus === 'analyzing' ? 'running' : 'failed'),
    progress: progress(5), resumes: 0, freshStarts: 0 }
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url')
  await page.context().addCookies([{ name: 'dm_token', value: `test.${payload}.test`,
    url: test.info().project.use.baseURL as string || 'http://localhost:3000' }])
  await page.addInitScript(() => {
    class TestEventSource {
      onmessage = null
      onerror = null
      constructor() { (window as MockWindow).analysisTestStream = this }
      close() { /* Each test emits only the events it needs. */ }
    }
    Object.defineProperty(window, 'EventSource', { value: TestEventSource })
  })
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api', '')
    if (path === '/workspaces') return route.fulfill({ json: [{ id: 1, name: 'My Workspace', owner_id: 1 }] })
    if (path === '/deals/4') return route.fulfill({ json: { id: 4, title: 'Ripresa verificata', status: state.status, report_language: 'it' } })
    if (path === '/documents/deals/4/documents') return route.fulfill({ json: [{
      id: 2, deal_id: 4, filename: 'bilancio.pdf', file_size: 1200, status: 'processed',
      analysis_ready: true, processing_issue: null, page_count: 4, language: 'it',
    }] })
    if (path === '/deals/4/agent-runs') return route.fulfill({ json: state.runs })
    if (path === '/deals/4/analysis-checkpoint') return route.fulfill({ json: { available: true, completed_stages: 6, next_stage: 'financial_analysis' } })
    if (path === '/deals/4/analysis-progress') return route.fulfill({ json: state.progress })
    if (path === '/deals/4/stream-ticket') return route.fulfill({ json: { ticket: 'test-ticket' } })
    if (path === '/deals/4/resume-analysis') {
      state.resumes++
      state.status = 'analyzing'
      state.runs = runs('running')
      return route.fulfill({ status: 202, json: { deal_id: 4, status: 'analyzing' } })
    }
    if (path === '/deals/4/analyze') {
      state.freshStarts++
      return route.fulfill({ status: 500, json: { detail: 'Resume must not restart every stage' } })
    }
    if (path === '/deals/4/risk-score') return route.fulfill({ status: 404, json: { detail: 'Not available yet' } })
    if (/^\/deals\/4\/(clause-findings|red-flags|open-questions|missing-documents|company-profiles)$/.test(path)) {
      return route.fulfill({ json: [] })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected mock request' } })
  })
  return state
}

async function emit(page: Page, payload: AnalysisStreamEvent) {
  await expect.poll(() => page.evaluate(() => !!(window as MockWindow).analysisTestStream?.onmessage)).toBe(true)
  await page.evaluate((value) => (window as MockWindow).analysisTestStream?.onmessage?.({ data: JSON.stringify(value) }), payload)
}

test('resume preserves the completed prefix and excludes yesterday’s report and aggregation', async ({ page }) => {
  const state = await prepare(page)
  await page.goto('/deals/4')
  await expect(page.getByRole('progressbar', { name: 'Fasi dell’analisi completate' })).toHaveAttribute('aria-valuenow', '6')
  await expect(page.getByText('999.0s', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Riprendi Analisi', exact: true }).click()
  await expect(page.getByRole('button', { name: 'In corso…', exact: true })).toBeDisabled()
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '6')
  expect(state.resumes).toBe(1)
  expect(state.freshStarts).toBe(0)
  await emit(page, { deal_status: 'analyzing', stages: state.runs, progress: progress(37) })
  await expect(page.getByRole('status').filter({ hasText: 'Analisi finanziaria:' })).toContainText('37 / 120 segmenti elaborati.')
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '6')
  await expect(page.getByText('999.0s', { exact: true })).toHaveCount(0)
})

test('a timeout clears the spinner and offers resume even if findings cannot be fetched', async ({ page }) => {
  const state = await prepare(page, 'analyzing')
  await page.route('**/api/deals/4/clause-findings', (route) => route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } }))
  await page.goto('/deals/4')
  await emit(page, { deal_status: 'analyzing', stages: state.runs, progress: progress(52) })
  await expect(page.getByRole('button', { name: 'In corso…', exact: true })).toBeDisabled()
  state.status = 'draft'
  state.runs = runs('failed')
  await emit(page, { deal_status: 'draft', stages: state.runs, progress: progress(52) })
  await expect(page.getByRole('button', { name: 'Riprendi Analisi', exact: true })).toBeEnabled()
  await expect(page.getByText('Analisi in corso…', { exact: true })).toHaveCount(0)
  await expect(page.getByText('In esecuzione…', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Ultima analisi incompleta', { exact: true })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'Analisi finanziaria:' })).toHaveCount(0)
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '6')
})

test('polling replaces stale SSE stages and continues updating batch progress', async ({ page }) => {
  const state = await prepare(page, 'analyzing')
  await page.goto('/deals/4')
  await emit(page, { deal_status: 'analyzing', stages: state.runs, progress: progress(5) })
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '6')
  state.runs = runs('completed')
  state.runs[7] = { ...state.runs[7], status: 'running', started_at: '2026-09-18T07:05:00Z', completed_at: null, duration_seconds: null }
  state.progress = progress(120)
  await page.evaluate(() => (window as MockWindow).analysisTestStream?.onerror?.())
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '7', { timeout: 12_000 })
  await expect(page.getByRole('status').filter({ hasText: 'Analisi finanziaria:' })).toContainText('120 / 120 segmenti elaborati.')
  await expect(page.getByText('999.0s', { exact: true })).toHaveCount(0)
})
