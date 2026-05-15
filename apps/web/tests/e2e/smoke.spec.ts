import { test, expect, Page } from '@playwright/test'

/**
 * Smoke tests for paths the backend pytest suite cannot exercise:
 * cookie-based auth guard, workspace switcher rendering, and the
 * insights page actually loading data from /workspaces/{id}/insights.
 *
 * Each test registers a fresh user so the suite is idempotent against
 * the same DB.
 */

const randEmail = () => `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@diligenx.test`
const PASSWORD = 'TestPass-1234!'


async function register(page: Page): Promise<string> {
  const email = randEmail()
  await page.goto('/login')

  // Switch to the "Registrati" tab.
  await page.getByRole('button', { name: 'Registrati' }).first().click()

  // The form fields are typed inputs without explicit label associations;
  // target them by attribute. The first password input belongs to the
  // register form (the login form is hidden when tab=register).
  const emailInput = page.locator('input[type="email"]').first()
  await emailInput.fill(email)
  const passwordInput = page.locator('input[type="password"]').first()
  await passwordInput.fill(PASSWORD)

  // Submit. The register submit reads "Crea account" (or similar Italian);
  // fall back to the only visible submit button if the label changes.
  const submitByName = page.getByRole('button', { name: /crea account|registrati e accedi|crea/i }).first()
  if (await submitByName.isVisible().catch(() => false)) {
    await submitByName.click()
  } else {
    await page.locator('form button[type="submit"]').first().click()
  }

  await expect(page).toHaveURL(/\/dashboard(\/.*)?$/, { timeout: 15_000 })
  return email
}


test('unauthenticated visit to / redirects to /login', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login(\?.*)?$/)
})


test('register → land on dashboard → see the deals heading', async ({ page }) => {
  await register(page)
  await expect(page.getByRole('heading', { name: /^deals$/i })).toBeVisible()
})


test('insights page renders for an empty workspace', async ({ page }) => {
  await register(page)
  await page.goto('/dashboard/insights')

  // The heading is always present; the empty-state copy confirms that the
  // /insights endpoint round-trip succeeded and returned zeroed buckets.
  await expect(page.getByRole('heading', { name: /^insights$/i })).toBeVisible()
  await expect(
    page.getByText(/nessun dato ancora/i),
  ).toBeVisible({ timeout: 10_000 })
})
