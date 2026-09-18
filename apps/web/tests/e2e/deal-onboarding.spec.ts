import { test, expect, Page } from '@playwright/test'

async function mockOnboarding(page: Page, options: { failCreate?: boolean; failFirstUpload?: boolean; delayCreate?: Promise<void> } = {}) {
  const creates: Record<string, unknown>[] = []
  const uploads: { dealId: string | null; role: string | null; body: string }[] = []
  const otherWrites: string[] = []
  const baseURL = test.info().project.use.baseURL as string || 'http://localhost:3000'
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url')
  await page.context().addCookies([
    { name: 'dm_token', value: `test.${payload}.test`, url: baseURL },
    { name: 'dm_workspace', value: '1', url: baseURL },
  ])
  await page.addInitScript(() => {
    window.EventSource = class { onerror = null; addEventListener() {}; close() {} } as unknown as typeof EventSource
  })
  const deal = { id: 51, workspace_id: 1, title: 'Acquisizione Arcari', status: 'draft', report_language: 'it', target_company_names: ['Arcari S.r.l.'], created_at: '2026-09-18T10:00:00Z' }
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api', '')
    if (path === '/workspaces') return route.fulfill({ json: [{ id: 1, name: 'My Workspace', owner_id: 1 }] })
    if (path === '/deals' && request.method() === 'GET') return route.fulfill({ json: [] })
    if (path === '/deals' && request.method() === 'POST') {
      const body = request.postDataJSON()
      creates.push(body)
      if (options.delayCreate) await options.delayCreate
      if (options.failCreate) return route.fulfill({ status: 400, json: { detail: 'Creazione temporaneamente non disponibile.' } })
      return route.fulfill({ status: 201, json: { ...deal, ...body } })
    }
    if (path === '/documents/upload' && request.method() === 'POST') {
      uploads.push({ dealId: url.searchParams.get('deal_id'), role: url.searchParams.get('document_role'), body: request.postData() ?? '' })
      if (options.failFirstUpload && uploads.length === 1) return route.fulfill({ status: 400, json: { detail: 'File non acquisito. Riprova.' } })
      return route.fulfill({ status: 201, json: { id: 91, filename: 'LOI.pdf', document_role: 'loi', status: 'pending', file_size: 20, language: null } })
    }
    if (path === '/deals/51') return route.fulfill({ json: deal })
    if (path === '/documents/deals/51/documents') return route.fulfill({ json: [{
      id: 91, deal_id: 51, filename: 'LOI.pdf', document_role: 'loi', mime_type: 'application/pdf', file_size: 20,
      status: 'processed', analysis_ready: true, processing_issue: null, page_count: 1, language: 'it', created_at: '2026-09-18T10:00:00Z',
    }] })
    if (path === '/deals/51/analysis-checkpoint') return route.fulfill({ json: { available: false } })
    if (path === '/deals/51/stream-ticket') return route.fulfill({ json: { ticket: 'mock-ticket' } })
    if (/\/(agent-runs|clause-findings|red-flags|open-questions|missing-documents|company-profiles)$/.test(path)) return route.fulfill({ json: [] })
    if (request.method() !== 'GET') otherWrites.push(path)
    return route.fulfill({ status: 404, json: { detail: 'Unexpected mocked request' } })
  })
  await page.goto('/dashboard')
  await page.getByRole('button', { name: 'Ho capito', exact: true }).click()
  await page.getByRole('button', { name: 'Nuovo Deal', exact: true }).click()
  await page.getByLabel('Titolo *', { exact: true }).fill('Acquisizione Arcari')
  return { creates, uploads, otherWrites }
}

const loi = { name: 'LOI.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nLOI fixture') }

test('new operation requires a legal name and saves the explicit scope without a LOI', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await mockOnboarding(page)
  await page.getByRole('button', { name: 'Crea Deal', exact: true }).click()
  expect(state.creates).toHaveLength(0)
  await expect(page.getByLabel('Società target *')).toBeFocused()
  await page.getByLabel('Società target *').fill('  Arcari S.r.l.  \n\n Seconda S.p.A.\nArcari S.r.l. ')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Crea Deal', exact: true }).click()
  await expect(page.getByRole('link', { name: /Acquisizione Arcari/ })).toBeVisible()
  expect(state.creates).toEqual([{ title: 'Acquisizione Arcari', target_company_names: ['Arcari S.r.l.', 'Seconda S.p.A.'] }])
  expect(state.uploads).toEqual([])
  expect(state.otherWrites).toEqual([])
})

test('LOI is uploaded with its role to the newly created operation and remains labelled', async ({ page }) => {
  const state = await mockOnboarding(page)
  await page.getByLabel('Società target *').fill('Arcari S.r.l.')
  const input = page.getByLabel('Lettera di intenti (LOI) — facoltativa')
  await input.evaluate((element) => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(['%PDF-1.4\nLOI fixture'], 'LOI.pdf'))
    ;(element as HTMLInputElement).files = transfer.files
    element.dispatchEvent(new Event('change', { bubbles: true }))
  })
  expect(await input.evaluate((element) => (element as HTMLInputElement).files?.[0].type)).toBe('')
  await page.getByRole('button', { name: 'Crea Deal', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Nuovo Deal', exact: true })).toBeVisible()
  expect(state.creates).toHaveLength(1)
  expect(state.uploads).toHaveLength(1)
  expect(state.uploads[0]).toMatchObject({ dealId: '51', role: 'loi' })
  expect(state.uploads[0].body).toContain('filename="LOI.pdf"')
  expect(state.uploads[0].body).toContain('Content-Type: application/pdf')
  expect(state.otherWrites).toEqual([])
  await page.getByRole('link', { name: /Acquisizione Arcari/ }).click()
  await expect(page.getByText('LOI', { exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'LOI.pdf LOI', exact: true })).toBeVisible()
})

test('a failed LOI upload retries on the same operation without creating a duplicate', async ({ page }) => {
  const state = await mockOnboarding(page, { failFirstUpload: true })
  await page.getByLabel('Società target *').fill('Arcari S.r.l.')
  await page.getByLabel('Lettera di intenti (LOI) — facoltativa').setInputFiles(loi)
  await page.getByRole('button', { name: 'Crea Deal', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Caricamento della LOI non confermato.' })).toBeVisible()
  await expect(page.getByLabel('Società target *')).toHaveValue('Arcari S.r.l.')
  await expect(page.getByLabel('Società target *')).toBeDisabled()
  await expect(page.getByLabel('Lettera di intenti (LOI) — facoltativa')).toBeDisabled()
  await expect(page.getByRole('link', { name: 'Apri operazione', exact: true })).toHaveAttribute('href', '/deals/51')
  await page.getByRole('button', { name: 'Riprova caricamento LOI', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Nuovo Deal', exact: true })).toBeVisible()
  expect(state.creates).toHaveLength(1)
  expect(state.uploads.map(({ dealId, role }) => ({ dealId, role }))).toEqual([{ dealId: '51', role: 'loi' }, { dealId: '51', role: 'loi' }])
  expect(state.otherWrites).toEqual([])
})

test('a creation error keeps the draft and does not upload the LOI', async ({ page }) => {
  const state = await mockOnboarding(page, { failCreate: true })
  await page.getByLabel('Società target *').fill('Arcari S.r.l.')
  await page.getByLabel('Lettera di intenti (LOI) — facoltativa').setInputFiles(loi)
  await page.getByRole('button', { name: 'Crea Deal', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Creazione non riuscita.' })).toBeVisible()
  await expect(page.getByLabel('Società target *')).toHaveValue('Arcari S.r.l.')
  await expect(page.getByLabel('Titolo *', { exact: true })).toHaveValue('Acquisizione Arcari')
  await expect(page.getByLabel('Lettera di intenti (LOI) — facoltativa')).toHaveValue(/LOI.pdf$/)
  expect(state.uploads).toEqual([])
})

test('invalid target names and LOI files are rejected before creating an operation', async ({ page }) => {
  const state = await mockOnboarding(page)
  const targets = page.getByLabel('Società target *')
  const submit = page.getByRole('button', { name: 'Crea Deal', exact: true })
  await targets.fill('  \n  ')
  await submit.click()
  await expect(page.getByRole('alert').filter({ hasText: 'almeno una società target' })).toBeVisible()
  await targets.fill(Array.from({ length: 21 }, (_, i) => `Società ${i} S.r.l.`).join('\n'))
  await submit.click()
  await expect(page.getByRole('alert').filter({ hasText: 'al massimo 20' })).toBeVisible()
  await targets.fill('A'.repeat(501))
  await submit.click()
  await expect(page.getByRole('alert').filter({ hasText: 'massimo 500 caratteri' })).toBeVisible()
  await targets.fill('Arcari S.r.l.')
  const input = page.getByLabel('Lettera di intenti (LOI) — facoltativa')
  await input.setInputFiles({ name: 'LOI.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('invalid') })
  await submit.click()
  await expect(page.getByRole('alert').filter({ hasText: 'PDF, DOCX o TXT' })).toBeVisible()
  await input.setInputFiles({ name: 'LOI.pdf', mimeType: 'image/jpeg', buffer: Buffer.from('invalid') })
  await submit.click()
  await expect(page.getByRole('alert').filter({ hasText: 'formato della LOI non è supportato' })).toBeVisible()
  await input.evaluate((element) => {
    const transfer = new DataTransfer()
    transfer.items.add(new File([new Uint8Array(50 * 1024 * 1024 + 1)], 'large.pdf', { type: 'application/pdf' }))
    ;(element as HTMLInputElement).files = transfer.files
    element.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await submit.click()
  await expect(page.getByRole('alert').filter({ hasText: 'non può superare 50 MB' })).toBeVisible()
  expect(state.creates).toEqual([])
  expect(state.uploads).toEqual([])
})

test('repeated submits during creation cannot start a second operation', async ({ page }) => {
  let releaseCreate: () => void = () => {}
  const delayCreate = new Promise<void>((resolve) => { releaseCreate = resolve })
  const state = await mockOnboarding(page, { delayCreate })
  await page.getByLabel('Società target *').fill('Arcari S.r.l.')
  await page.locator('form').evaluate((form) => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  })
  await expect.poll(() => state.creates.length).toBe(1)
  await expect(page.getByRole('button', { name: 'Annulla', exact: true })).toBeDisabled()
  await expect(page.getByLabel('Società target *')).toBeDisabled()
  releaseCreate()
  await expect(page.getByRole('button', { name: 'Nuovo Deal', exact: true })).toBeVisible()
  expect(state.creates).toHaveLength(1)
})
