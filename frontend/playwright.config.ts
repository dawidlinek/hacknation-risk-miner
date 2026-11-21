import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

// Playwright 1.65 expects Chromium build 1255; on hosts that only have an older cached headless shell,
// fall back to it (PW_CHROMIUM overrides). CI runs `npx playwright install chromium` and uses the default.
function fallbackChromium(): string | undefined {
  if (process.env.PW_CHROMIUM) return process.env.PW_CHROMIUM
  if (process.env.CI) return undefined
  const cache = join(homedir(), '.cache', 'ms-playwright')
  try {
    const shells = readdirSync(cache)
      .filter((d) => d.startsWith('chromium_headless_shell-'))
      .sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]))
    for (const d of shells) {
      if (Number(d.split('-')[1]) >= 1255) return undefined
      const p = join(cache, d, 'chrome-headless-shell-linux64', 'chrome-headless-shell')
      if (existsSync(p)) return p
    }
  } catch {
    /* no cache */
  }
  return undefined
}

const executablePath = fallbackChromium()
const baseURL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173'

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    headless: true,
    trace: 'retain-on-failure',
    acceptDownloads: true,
    locale: 'pl-PL',
    timezoneId: 'Europe/Warsaw',
    launchOptions: { executablePath, args: ['--enable-unsafe-swiftshader'] },
  },
  projects: [
    // Real backend on :8000 behind the Vite proxy (`npm run dev` with VITE_MOCKS=none, or ?mocks=none).
    { name: 'live', use: { ...devices['Desktop Chrome'], launchOptions: { executablePath, args: ['--enable-unsafe-swiftshader'] } } },
  ],
  // Reuse the dev server that is already running on 5173 (only one Vite server on this host).
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : { command: 'npm run dev', url: baseURL, reuseExistingServer: true, timeout: 60_000 },
})
