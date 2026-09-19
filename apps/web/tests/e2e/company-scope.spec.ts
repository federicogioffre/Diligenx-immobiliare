import { test, expect, Page } from '@playwright/test'

async function mockScope(page: Page, status = 'reviewed', rejectSave = false) {
  let names = ['Alfa S.r.l.']
  const writes: { path: string; body: unknown }[] = []
  let profileReads = 0
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url')
  await page.context().addCookies([{ name: 'dm_token', value: `test.${payload}.test`, url: test.info().project.use.baseURL as string || 'http://localhost:3000' }])
  await page.addInitScript(() => {
    // No live stream/backend is contacted by this isolated UI fixture.
    window.EventSource = class {
      onerror = null
      addEventListener() {}
      close() {}
    } as unknown as typeof EventSource
  })
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace('/api', '')
    if (path === '/workspaces') return route.fulfill({ json: [{ id: 1, name: 'My Workspace', owner_id: 1 }] })
    if (path === '/deals/4/stream-ticket') return route.fulfill({ json: { ticket: 'test-ticket' } })
    if (request.method() !== 'GET') writes.push({ path, body: request.postDataJSON() })
    if (path === '/deals/4') {
      if (request.method() === 'PATCH') {
        if (rejectSave) return route.fulfill({ status: 409, json: { detail: 'Il report esistente richiede verifica prima di aggiornare il perimetro.' } })
        names = request.postDataJSON().target_company_names
        status = 'draft'
      }
      return route.fulfill({ json: { id: 4, title: 'Operazione Riservata', status, report_language: 'it', target_company_names: names } })
    }
    if (path === '/deals/4/company-profiles') {
      profileReads += 1
      return route.fulfill({ json: names.map((company_name, index) => ({
        id: index + 1, deal_id: 4, company_name, registered_office: 'Milano',
        corporate_capital: 'EUR 10,000\nEUR 20,000', confidence: 0.9,
        source_filenames: ['visura.pdf', 'statuto.pdf'], conflicting_fields: ['corporate_capital'],
      })) })
    }
    if (path === '/deals/4/analysis-checkpoint') return route.fulfill({ json: { available: false } })
    if (path === '/deals/4/report') return route.fulfill({ json: {
      report_id: 1, deal_id: 4, generation_available: false, stale: true,
      markdown: '# Report\n\n## 1. Introduzione\nTesto invariato.\n\n## 2. Informazioni Societarie\n\n'
        + '### 2.1 Alfa S.r.l.\n\n| Campo | Valore |\n|---|---|\n| Sede | Milano |\n'
        + '\n## 3. Executive Summary\nRiassunto invariato.',
    } })
    if (path === '/documents/deals/4/documents' || /\/(agent-runs|red-flags|open-questions|missing-documents)$/.test(path)) {
      return route.fulfill({ json: [] })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected mocked request' } })
  })
  return { writes, profileReads: () => profileReads }
}

test('scope saves legal names and marks the preserved report as out of date', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await mockScope(page)
  await page.goto('/deals/4')
  await page.getByRole('button', { name: 'Ho capito', exact: true }).click()
  const field = page.getByLabel('Società nel perimetro', { exact: true })
  await expect(field).toHaveValue('Alfa S.r.l.')
  await expect(page.getByRole('heading', { name: 'Alfa S.r.l.', exact: true })).toBeVisible()
  await field.fill('  Beta S.r.l.  \n\nGamma S.p.A.\nBeta S.r.l.\n')
  await page.getByRole('button', { name: 'Salva perimetro', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Perimetro salvato.' })).toBeVisible()
  await expect(field).toHaveValue('Beta S.r.l.\nGamma S.p.A.')
  await expect(page.getByRole('heading', { name: 'Beta S.r.l.', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Alfa S.r.l.', exact: true })).toHaveCount(0)
  await expect(page.getByText('Fonti: visura.pdf; statuto.pdf').first()).toBeVisible()
  await expect(page.getByText(/Le fonti riportano valori diversi/).first()).toBeVisible()
  expect(state.writes).toEqual([{ path: '/deals/4', body: { target_company_names: ['Beta S.r.l.', 'Gamma S.p.A.'] } }])
  expect(state.profileReads()).toBeGreaterThanOrEqual(2)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

  await page.getByRole('link', { name: 'Report', exact: true }).click()
  await expect(page).toHaveURL(/\/deals\/4\/report$/, { timeout: 15_000 })
  await expect(page.getByRole('heading', { name: '2.1 Alfa S.r.l.', exact: true })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: 'versione precedente conservata' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'PDF', exact: true })).toBeDisabled()
  await expect(page.getByText('Riassunto invariato.', { exact: true })).toBeVisible()
  expect(state.writes).toHaveLength(1)
})

test('scope cannot change during an active analysis', async ({ page }) => {
  const state = await mockScope(page, 'analyzing')
  await page.goto('/deals/4')
  await expect(page.getByLabel('Società nel perimetro', { exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Salva perimetro', exact: true })).toBeDisabled()
  await expect(page.getByText('Modificabile al termine dell’analisi.', { exact: true })).toBeVisible()
  expect(state.writes).toEqual([])
})

test('a rejected scope change retains the draft and shows the actionable error', async ({ page }) => {
  const state = await mockScope(page, 'reviewed', true)
  await page.goto('/deals/4')
  const field = page.getByLabel('Società nel perimetro', { exact: true })
  await field.fill('Beta S.r.l.')
  await page.getByRole('button', { name: 'Salva perimetro', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Il report esistente richiede' })).toHaveText('Il report esistente richiede verifica prima di aggiornare il perimetro.')
  await expect(field).toHaveValue('Beta S.r.l.')
  await expect(page.getByRole('heading', { name: 'Alfa S.r.l.', exact: true })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'Perimetro salvato.' })).toHaveCount(0)
  expect(state.writes).toHaveLength(1)
})

test('companies without an extracted profile are identified without inventing cards', async ({ page }) => {
  await mockScope(page)
  await page.route('**/api/deals/4/company-profiles', (route) => route.fulfill({ json: [] }))
  await page.goto('/deals/4')
  await expect(page.getByRole('status').filter({ hasText: 'Nessun profilo estratto corrisponde a: Alfa S.r.l.' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Alfa S.r.l.', exact: true })).toHaveCount(0)
})
