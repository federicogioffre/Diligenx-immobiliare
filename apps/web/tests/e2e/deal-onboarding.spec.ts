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
  const deal = { id: 51, workspace_id: 1, title: 'Appartamento via Roma 1', status: 'draft', report_language: 'it', target_company_names: null, created_at: '2026-09-18T10:00:00Z' }
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
      return route.fulfill({ status: 201, json: { id: 91, filename: 'Proposta.pdf', document_role: 'loi', status: 'pending', file_size: 20, language: null } })
    }
    if (path === '/deals/51') return route.fulfill({ json: deal })
    if (path === '/documents/deals/51/documents') return route.fulfill({ json: [{
      id: 91, deal_id: 51, filename: 'Proposta.pdf', document_role: 'loi', mime_type: 'application/pdf', file_size: 20,
      status: 'processed', analysis_ready: true, processing_issue: null, page_count: 1, language: 'it', created_at: '2026-09-18T10:00:00Z',
    }] })
    if (path === '/deals/51/analysis-checkpoint') return route.fulfill({ json: { available: false } })
    if (path === '/deals/51/stream-ticket') return route.fulfill({ json: { ticket: 'mock-ticket' } })
    if (/\/(agent-runs|clause-findings|red-flags|open-questions|missing-documents|property-profiles)$/.test(path)) return route.fulfill({ json: [] })
    if (request.method() !== 'GET') otherWrites.push(path)
    return route.fulfill({ status: 404, json: { detail: 'Unexpected mocked request' } })
  })
  await page.goto('/dashboard')
  await page.getByRole('button', { name: 'Ho capito', exact: true }).click()
  await page.getByRole('button', { name: 'Nuova pratica', exact: true }).click()
  await page.getByLabel('Immobile *', { exact: true }).fill('Appartamento via Roma 1')
  return { creates, uploads, otherWrites }
}

const proposal = { name: 'Proposta.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nProposal fixture') }
const PROPOSAL_LABEL = 'Proposta d’acquisto o preliminare — facoltativo'

test('a new purchase is created with the property and no company scope', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await mockOnboarding(page)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Crea pratica', exact: true }).click()
  await expect(page.getByRole('link', { name: /Appartamento via Roma 1/ })).toBeVisible()
  expect(state.creates).toEqual([{ title: 'Appartamento via Roma 1' }])
  expect(state.uploads).toEqual([])
  expect(state.otherWrites).toEqual([])
})

test('the proposal is uploaded with its role to the new purchase and remains labelled', async ({ page }) => {
  const state = await mockOnboarding(page)
  const input = page.getByLabel(PROPOSAL_LABEL)
  await input.evaluate((element) => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(['%PDF-1.4\nProposal fixture'], 'Proposta.pdf'))
    ;(element as HTMLInputElement).files = transfer.files
    element.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.getByRole('button', { name: 'Crea pratica', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Nuova pratica', exact: true })).toBeVisible()
  expect(state.creates).toHaveLength(1)
  expect(state.uploads).toHaveLength(1)
  expect(state.uploads[0]).toMatchObject({ dealId: '51', role: 'loi' })
  expect(state.uploads[0].body).toContain('filename="Proposta.pdf"')
  expect(state.uploads[0].body).toContain('Content-Type: application/pdf')
  expect(state.otherWrites).toEqual([])
  await page.getByRole('link', { name: /Appartamento via Roma 1/ }).click()
  await expect(page.getByRole('cell', { name: 'Proposta.pdf Proposta', exact: true })).toBeVisible()
})

test('a failed proposal upload retries on the same purchase without creating a duplicate', async ({ page }) => {
  const state = await mockOnboarding(page, { failFirstUpload: true })
  await page.getByLabel(PROPOSAL_LABEL).setInputFiles(proposal)
  await page.getByRole('button', { name: 'Crea pratica', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Caricamento della proposta non confermato.' })).toBeVisible()
  await expect(page.getByLabel('Immobile *', { exact: true })).toBeDisabled()
  await expect(page.getByLabel(PROPOSAL_LABEL)).toBeDisabled()
  await expect(page.getByRole('link', { name: 'Apri pratica', exact: true })).toHaveAttribute('href', '/deals/51')
  await page.getByRole('button', { name: 'Riprova caricamento proposta', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Nuova pratica', exact: true })).toBeVisible()
  expect(state.creates).toHaveLength(1)
  expect(state.uploads.map(({ dealId, role }) => ({ dealId, role }))).toEqual([{ dealId: '51', role: 'loi' }, { dealId: '51', role: 'loi' }])
  expect(state.otherWrites).toEqual([])
})

test('a creation error keeps the draft and does not upload the proposal', async ({ page }) => {
  const state = await mockOnboarding(page, { failCreate: true })
  await page.getByLabel(PROPOSAL_LABEL).setInputFiles(proposal)
  await page.getByRole('button', { name: 'Crea pratica', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Creazione non riuscita.' })).toBeVisible()
  await expect(page.getByLabel('Immobile *', { exact: true })).toHaveValue('Appartamento via Roma 1')
  await expect(page.getByLabel(PROPOSAL_LABEL)).toHaveValue(/Proposta.pdf$/)
  expect(state.uploads).toEqual([])
})

test('invalid proposal files are rejected before creating a purchase', async ({ page }) => {
  const state = await mockOnboarding(page)
  const submit = page.getByRole('button', { name: 'Crea pratica', exact: true })
  const input = page.getByLabel(PROPOSAL_LABEL)
  await input.setInputFiles({ name: 'Proposta.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('invalid') })
  await submit.click()
  await expect(page.getByRole('alert').filter({ hasText: 'PDF, DOCX o TXT' })).toBeVisible()
  await input.setInputFiles({ name: 'Proposta.pdf', mimeType: 'image/jpeg', buffer: Buffer.from('invalid') })
  await submit.click()
  await expect(page.getByRole('alert').filter({ hasText: 'formato della proposta non è supportato' })).toBeVisible()
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

test('repeated submits during creation cannot start a second purchase', async ({ page }) => {
  let releaseCreate: () => void = () => {}
  const delayCreate = new Promise<void>((resolve) => { releaseCreate = resolve })
  const state = await mockOnboarding(page, { delayCreate })
  await page.locator('form').evaluate((form) => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  })
  await expect.poll(() => state.creates.length).toBe(1)
  await expect(page.getByRole('button', { name: 'Annulla', exact: true })).toBeDisabled()
  await expect(page.getByLabel('Immobile *', { exact: true })).toBeDisabled()
  releaseCreate()
  await expect(page.getByRole('button', { name: 'Nuova pratica', exact: true })).toBeVisible()
  expect(state.creates).toHaveLength(1)
})
