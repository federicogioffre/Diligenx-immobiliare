import { test, expect, Page } from '@playwright/test'

const agents = ['intake', 'document_router', 'contract_analysis', 'corporate_governance',
  'corporate_intro_extraction', 'tax_analysis', 'financial_analysis', 'red_flag_aggregation']

async function mockReport(page: Page, state: 'new' | 'stale' | 'current') {
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url')
  await page.context().addCookies([{ name: 'dm_token', value: `test.${payload}.test`,
    url: test.info().project.use.baseURL as string }])
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '')
    if (path === '/workspaces') return route.fulfill({ json: [{ id: 1, name: 'Audit', owner_id: 1 }] })
    if (path === '/deals/4') return route.fulfill({ json: { id: 4, title: 'Audit', status: state === 'current' ? 'reviewed' : 'draft' } })
    if (path === '/deals/4/agent-runs') return route.fulfill({ json: state === 'new' ? [] :
      agents.map((agent_name, id) => ({ id, agent_name, status: 'completed' })) })
    if (path === '/deals/4/report') return state === 'new'
      ? route.fulfill({ status: 404, json: { detail: 'No report generated yet' } })
      : route.fulfill({ json: { report_id: 1, deal_id: 4, markdown: '## Report conservato\nEvidenze precedenti.',
        generation_available: state === 'current', stale: state === 'stale' } })
    return route.fulfill({ status: 404, json: { detail: 'Unexpected request' } })
  })
}

test('a new deal cannot generate a report from an empty analysis history', async ({ page }) => {
  await mockReport(page, 'new')
  await page.goto('/deals/4/report')
  await expect(page.getByRole('button', { name: 'Genera Report', exact: true })).toBeDisabled()
  await expect(page.getByRole('alert').filter({ hasText: 'Analisi incompleta' })).toBeVisible()
})

test('stale report remains readable but cannot be exported or regenerated', async ({ page }) => {
  await mockReport(page, 'stale')
  await page.goto('/deals/4/report')
  await expect(page.getByRole('heading', { name: 'Report conservato' })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: 'versione precedente conservata' })).toBeVisible()
  for (const name of ['PDF', 'DOCX', 'Rigenera']) {
    await expect(page.getByRole('button', { name, exact: true })).toBeDisabled()
  }
})

test('current completed report enables exports and regeneration', async ({ page }) => {
  await mockReport(page, 'current')
  await page.goto('/deals/4/report')
  await expect(page.getByRole('heading', { name: 'Report conservato' })).toBeVisible()
  for (const name of ['PDF', 'DOCX', 'Rigenera']) {
    await expect(page.getByRole('button', { name, exact: true })).toBeEnabled()
  }
})
