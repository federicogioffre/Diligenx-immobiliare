import { test, expect } from '@playwright/test'

/**
 * Legal pages and password reset are public: a signed-out visitor must land
 * on the page itself, not on /login. The in-app NavBar used to render its
 * workspace switcher there too, and the 401 from /workspaces sent the
 * visitor to the login page.
 */

test.beforeEach(async ({ page }) => {
  // Keep the cookie notice from covering the footer links.
  await page.addInitScript(() => localStorage.setItem('dm_cookie_notice_dismissed', '1'))
})

for (const start of ['/', '/login']) {
  for (const [label, path] of [
    ['Termini', '/terms'],
    ['Privacy', '/privacy'],
    ['Sicurezza', '/security'],
  ] as const) {
    test(`${label} opens from ${start} without signing in`, async ({ page }) => {
      await page.goto(start)
      await page.getByRole('link', { name: label, exact: true }).last().click()
      await expect(page).toHaveURL(new RegExp(`${path}$`))
      await page.waitForLoadState('networkidle')
      await expect(page).toHaveURL(new RegExp(`${path}$`))
    })
  }
}

test('password reset opens without signing in', async ({ page }) => {
  await page.goto('/forgot-password')
  await page.waitForLoadState('networkidle')
  await expect(page).toHaveURL(/\/forgot-password$/)
})
