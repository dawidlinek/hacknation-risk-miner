// axe sweep (wcag2a/aa/21a/21aa; fails on serious + critical) over every flagged-on route, on the real backend.
// Public routes run anonymous; expert routes run as the read-only demo persona "juror" (nothing is written).
// Flow 1 pages use an analysis created in this browser context (analyses are owner-only) with a public PFU
// uploaded in the same context (local data/raw file; the Red Pen page is skipped without it).
// Owners: A for analizy/** and replay, F2 for the rest.
import { expect, type Page, test } from '@playwright/test'
import { expectNoA11yViolations } from './a11y'
import { anyOcid, createAnalysis, loginAs, realBackend, uploadPublicPfu } from './helpers'

async function check(page: Page, path: string) {
  await page.goto(path)
  await expect(page.locator('h1').first(), path).toBeVisible({ timeout: 60_000 })
  await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => undefined)
  await expectNoA11yViolations(page, path)
}

const PUBLIC = [
  '/zaloguj',
  '/analizy/nowa',
  '/projekty',
  '/projekty/RM-2026-003',
  '/projekty/RM-2026-003/graf',
  '/projekty/RM-2026-003/dokumenty',
  '/zapytaj',
  '/monitoring',
  '/monitoring/12',
  '/monitoring/12/1209',
  '/monitoring/12/1209/umowa/135882',
]
const EXPERT = [
  '/',
  '/przeglad',
  '/katalog',
  '/zrodla',
  '/historia',
  '/ustawienia',
  '/projekty/RM-2026-003/historia',
]

test.describe('a11y public', () => {
  test.beforeEach(async ({ page }) => realBackend(page))
  for (const path of PUBLIC) test(path, async ({ page }) => check(page, path))
  test('/projekty/<ocid> (auto card)', async ({ page }) =>
    check(page, `/projekty/${await anyOcid(page.request)}`))
  test('Flow 1 on an own analysis', async ({ page }) => {
    test.setTimeout(180_000)
    await page.goto('/zaloguj')
    const doc = await uploadPublicPfu(page.request)
    const code = await createAnalysis(page.request, doc ? [doc] : [])
    const subs = ['', ...(doc ? [`/dokumenty/${doc}`] : []), '/symulacja', '/pakiet']
    for (const sub of subs) await check(page, `/analizy/${code}${sub}`)
  })
})

test.describe('a11y expert (juror)', () => {
  test.beforeEach(async ({ page }) => {
    await realBackend(page)
    await loginAs(page.request, 'juror')
  })
  for (const path of EXPERT) test(path, async ({ page }) => check(page, path))
})
