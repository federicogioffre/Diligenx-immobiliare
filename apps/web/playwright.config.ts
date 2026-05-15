import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config for Diligenx web smoke tests.
 *
 * Tests run against a live Next.js dev server (auto-started via the
 * webServer block below) which proxies /api/* to the FastAPI backend
 * (see next.config.ts). Start the backend first, then run the tests:
 *
 *   # one-off, downloads the Chromium binary
 *   pnpm dlx playwright install chromium
 *
 *   # start the API in another shell (defaults to :8001 per next.config)
 *   cd ../api && uvicorn app.main:app --port 8001
 *
 *   # run the smoke suite
 *   pnpm test:e2e
 */
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: 'list',

  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000',
    trace: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: process.env.PLAYWRIGHT_SKIP_WEBSERVER
    ? undefined
    : {
        command: 'pnpm dev',
        url: 'http://localhost:3000',
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
})
