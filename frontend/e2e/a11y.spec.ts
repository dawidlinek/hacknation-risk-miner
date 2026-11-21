// axe sweep (wcag2a/aa, serious + critical) over the public routes on the real backend.
// Analyses are owner-only, so the Flow 1 pages use an analysis created in the same browser context
// (with the synthetic public PFU, document 33366, attached so Red Pen has a document).
import { expect, test } from '@playwright/test'
import { expectNoA11yViolations } from './a11y'

const PUBLIC_PFU = 33366
const ROUTES = ['/zaloguj', '/analizy/nowa', '/projekty', '/projekty/RM-2026-003', '/zapytaj', '/monitoring']

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try {
      localStorage.setItem('rm.mocks', 'none')
      localStorage.removeItem('rm.mockRole')
    } catch {
      /* ignore */
    }
  })
})

for (const path of ROUTES) {
  test(`a11y ${path}`, async ({ page }) => {
    await page.goto(path)
    await expect(page.locator('h1').first()).toBeVisible({ timeout: 30_000 })
    await page.waitForLoadState('networkidle')
    await expectNoA11yViolations(page, path)
  })
}

test('a11y Flow 1 on an own analysis', async ({ page }) => {
  await page.goto('/zaloguj')
  const h = { 'X-Requested-With': 'ex-ante' }
  const created = await page.request.post('/api/analyses', {
    headers: h,
    data: {
      text: 'Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami, zaprojektuj i wybuduj, 7 mln zł brutto, 14 miesięcy, FEnIKS. [e2e]',
      document_ids: [PUBLIC_PFU],
    },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const draft = (await created.json()) as { id?: string; code?: string }
  const code = draft.id ?? draft.code
  const run = await page.request.post(`/api/analyses/${code}/run`, { headers: h, data: {} })
  expect(run.ok(), await run.text()).toBeTruthy()
  for (const path of [
    `/analizy/${code}`,
    `/analizy/${code}/dokumenty/${PUBLIC_PFU}`,
    `/analizy/${code}/symulacja`,
    `/analizy/${code}/pakiet`,
  ]) {
    await page.goto(path)
    await expect(page.locator('h1').first(), path).toBeVisible({ timeout: 60_000 })
    await page.waitForLoadState('networkidle')
    await expectNoA11yViolations(page, path)
  }
})
