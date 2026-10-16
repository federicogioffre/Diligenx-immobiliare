import { test, expect, Page } from '@playwright/test'
import { getBlockedDocuments, parseApiError } from '../../src/lib/api-error'
import type { DocumentRead } from '../../src/lib/api'

const makeDocument = (id: number, overrides: Partial<DocumentRead> = {}): DocumentRead => ({
  id, deal_id: 4, filename: `documento-${id}.pdf`, mime_type: 'application/pdf',
  file_size: 1200, status: 'processed', analysis_ready: true, processing_issue: null,
  page_count: 1, language: 'it', created_at: '2026-09-17T10:00:00Z', ...overrides,
})
const agents = ['intake', 'document_router', 'property_identity', 'title_chain_review',
  'encumbrances_review', 'building_cadastral_review', 'condominium_occupancy_review', 'consistency_check',
  'red_flag_aggregation', 'report_generation']

async function mockDeal(page: Page, initialDocs: DocumentRead[]) {
  let docs = initialDocs
  const retries: number[] = []
  // Synthetic cookie only for the local middleware; every API call is mocked.
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url')
  await page.context().addCookies([{ name: 'dm_token', value: `test.${payload}.test`, url: test.info().project.use.baseURL as string || 'http://localhost:3000' }])
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api', '')
    if (path === '/workspaces') return route.fulfill({ json: [{ id: 1, name: 'My Workspace', owner_id: 1 }] })
    if (path === '/deals/4') return route.fulfill({ json: { id: 4, title: 'Verifica documenti', status: 'draft', report_language: 'it' } })
    if (path === '/documents/deals/4/documents') return route.fulfill({ json: docs })
    if (path === '/deals/4/agent-runs') return route.fulfill({ json: agents.map((agent_name, i) => ({
      id: i + 1, agent_name, status: 'completed', completed_at: '2026-09-17T12:00:00Z', duration_seconds: 1,
    })) })
    const retry = path.match(/^\/documents\/(\d+)\/retry$/)
    if (retry) {
      const id = Number(retry[1])
      retries.push(id)
      docs = docs.map((doc) => doc.id === id ? { ...doc, status: 'processed', analysis_ready: true, processing_issue: null } : doc)
      return route.fulfill({ status: 202, json: docs.find((doc) => doc.id === id) })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected mocked request' } })
  })
  return { retries, setDocs: (fresh: DocumentRead[]) => { docs = fresh } }
}

test('API errors show a message while preserving actionable blockers', () => {
  expect(parseApiError('{"detail":"Documento non trovato"}', 404).message).toBe('Documento non trovato')
  const blocker = { id: 2, filename: 'bilancio.pdf', status: 'pending', reason: 'pending' }
  const error = parseApiError(JSON.stringify({ detail: { code: 'documents_not_ready', message: 'Elabora i documenti.', documents: [blocker, {}] } }), 409)
  expect(error.message).toBe('Elabora i documenti.')
  expect(getBlockedDocuments(error)).toEqual([blocker])
  expect(parseApiError('{"detail":[{"msg":"validation"}]}', 422).message).not.toContain('{')
  expect(parseApiError('<html>Upstream failure</html>', 502).message).not.toContain('<html>')
})

test('mobile names and statuses remain visible; pending and empty-text documents can be retried', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await mockDeal(page, [makeDocument(1), makeDocument(2, { filename: 'bilancio in attesa.pdf', status: 'pending', analysis_ready: false, processing_issue: 'pending' }),
    makeDocument(3, { filename: 'statuto senza testo.pdf', analysis_ready: false, processing_issue: 'missing_text' })])
  await page.goto('/deals/4')
  await expect(page.getByRole('button', { name: 'Avvia Analisi', exact: true })).toBeDisabled()
  await expect(page.getByText('Testo non disponibile', { exact: true })).toBeVisible()
  await expect(page.getByText('Ultima analisi completata', { exact: true })).toBeVisible()
  await expect(page.getByText(/Questi risultati appartengono all’analisi precedente/)).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('mobile-document-readiness.png'), fullPage: true })
  await page.getByRole('button', { name: 'Riprova elaborazione di bilancio in attesa.pdf', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Avvia Analisi', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Riprova elaborazione di statuto senza testo.pdf', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Avvia Analisi', exact: true })).toBeEnabled()
  expect(state.retries).toEqual([2, 3])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  const logo = await page.getByRole('link', { name: 'Diligenx', exact: true }).boundingBox()
  const workspace = await page.getByRole('button', { name: 'My Workspace', exact: true }).boundingBox()
  expect(logo!.x + logo!.width).toBeLessThanOrEqual(workspace!.x)
})

test('a readiness conflict refreshes documents and identifies results from the previous run', async ({ page }) => {
  const state = await mockDeal(page, [makeDocument(1)])
  await page.route('**/api/deals/4/analyze', async (route) => {
    state.setDocs([makeDocument(1, { filename: 'statuto.pdf', analysis_ready: false, processing_issue: 'missing_text' })])
    await route.fulfill({ status: 409, json: { detail: { code: 'documents_not_ready', message: 'Un documento richiede attenzione.',
      documents: [{ id: 1, filename: 'statuto.pdf', status: 'processed', reason: 'missing_text' }],
    } } })
  })
  await page.goto('/deals/4')
  await page.getByRole('button', { name: 'Avvia Analisi', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Un documento richiede attenzione.' })).toHaveText('Un documento richiede attenzione.')
  await expect(page.getByRole('button', { name: 'Riprova elaborazione di statuto.pdf', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Avvia Analisi', exact: true })).toBeDisabled()
  await expect(page.getByText('Ultima analisi completata', { exact: true })).toBeVisible()
  await expect(page.getByText(/Questi risultati appartengono all’analisi precedente/)).toBeVisible()
})
