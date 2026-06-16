import { defineConfig, devices } from '@playwright/test'

// End-to-end tests drive the real React UI (Vite dev server) against a real
// FastAPI app (app.e2e_server, with an inline-draining queue + seeded connectors).
// The dev server proxies API calls to the backend, so the browser talks same-origin.
const FRONTEND_PORT = 5173
const BACKEND_PORT = 8000

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? 'line' : [['list']],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `uv run uvicorn app.e2e_server:app --port ${BACKEND_PORT}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${BACKEND_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { VITE_PROXY_TARGET: `http://127.0.0.1:${BACKEND_PORT}` },
    },
  ],
})
