import { test, expect, Page } from '@playwright/test'

async function mockFindings(page: Page, payload: unknown, sourcePage: number | null = null) {
  const token = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url')
  await page.context().addCookies([{ name: 'dm_token', value: `test.${token}.test`,
    url: test.info().project.use.baseURL as string }])
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '')
    if (path === '/workspaces') return route.fulfill({ json: [{ id: 1, name: 'Collaudo', owner_id: 1 }] })
    if (path === '/deals/4') return route.fulfill({ json: { id: 4, title: 'Collaudo', status: 'reviewed' } })
    if (path === '/deals/4/clause-findings') return route.fulfill({ json: [] })
    if (path === '/documents/deals/4/documents') return route.fulfill({ json: [
      { id: 241, filename: 'finanziamento.pdf' },
      { id: 242, filename: 'situazione_finanziaria.pdf' },
      { id: 244, filename: 'lettera_intenti.txt' },
    ] })
    if (path === '/deals/4/red-flags') return route.fulfill({ json: [{
      id: 56, deal_id: 4, title: 'Condizioni del finanziamento',
      issue: 'La cessione richiede il consenso scritto della banca.',
      risk: 'Il rimborso per violazione del covenant richiede un termine di rimedio di 30 giorni.',
      recommendation: 'Ottenere il consenso prima del perfezionamento.',
      severity: 'high', area: 'indebtedness', category: 'covenant', confidence: 0.95,
      source_document_id: 241, source_page: sourcePage, remedy_type: null, impact: null,
      structured_payload_json: payload,
    }] })
    return route.fulfill({ status: 404, json: { detail: 'Unexpected request' } })
  })
}

test('reviewed combined findings show every source and all pages without duplicates', async ({ page }) => {
  await mockFindings(page, {
    grounding_reviewed: true,
    source_pages: [
      { source_document_id: 241, page: 2 },
      { source_document_id: 241, page: 1 },
      { source_document_id: 241, page: 2 },
      { source_document_id: 242, page: 1 },
    ],
    evidence: [
      { source_document_id: 241, source_page: 2 },
      { source_document_id: 244, source_page: null },
    ],
  })
  await page.goto('/deals/4/findings')
  await expect(page.getByText('finanziamento.pdf, pagg. 1, 2', { exact: true })).toBeVisible()
  await expect(page.getByText('finanziamento.pdf, pagg. 1, 2', { exact: true })).toHaveCount(1)
  await expect(page.getByText('situazione_finanziaria.pdf, pag. 1', { exact: true })).toBeVisible()
  await expect(page.getByText('lettera_intenti.txt', { exact: true })).toBeVisible()
})

test('legacy findings retain their single source and page', async ({ page }) => {
  await mockFindings(page, null, 2)
  await page.goto('/deals/4/findings')
  await expect(page.getByText('finanziamento.pdf, pag. 2', { exact: true })).toBeVisible()
  await expect(page.getByText('situazione_finanziaria.pdf', { exact: true })).toHaveCount(0)
})

test('malformed reviewed coordinates do not hide unpaginated evidence or crash the page', async ({ page }) => {
  await mockFindings(page, {
    grounding_reviewed: true,
    source_pages: [null, 'invalid', { source_document_id: 999, page: 9 },
      { source_document_id: 241, page: -1 }, { source_document_id: 241, page: true }],
    evidence: [{ source_document_id: 244, source_page: null }],
  })
  await page.goto('/deals/4/findings')
  await expect(page.getByRole('heading', { name: 'Condizioni del finanziamento' })).toBeVisible()
  await expect(page.getByText('finanziamento.pdf', { exact: true })).toBeVisible()
  await expect(page.getByText('lettera_intenti.txt', { exact: true })).toBeVisible()
  await expect(page.getByText('pag. -1', { exact: false })).toHaveCount(0)
})

test('unreviewed structured coordinates do not override a legacy citation', async ({ page }) => {
  await mockFindings(page, { source_pages: [{ source_document_id: 242, page: 42 }] }, 2)
  await page.goto('/deals/4/findings')
  await expect(page.getByText('finanziamento.pdf, pag. 2', { exact: true })).toBeVisible()
  await expect(page.getByText('situazione_finanziaria.pdf, pag. 42', { exact: true })).toHaveCount(0)
})
