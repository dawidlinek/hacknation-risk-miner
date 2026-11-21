// Jury path (b) on the real backend: Nowa inwestycja -> Raport -> Symulacja -> Podział ryzyk -> DOCX.
// Public (anonymous) user, so it exercises the public mode. Creates one AN-… analysis record.
// Run: npx playwright test e2e/demo-b-analysis.spec.ts --project=live
import { expect, test } from '@playwright/test'
import { expectNoA11yViolations } from './a11y'

const DESCRIPTION =
  'Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami w formule zaprojektuj i wybuduj, ' +
  'budżet 7 mln zł brutto, termin 14 miesięcy, finansowanie FEnIKS. [e2e]'

test.describe('demo (b): nowa inwestycja do pakietu', () => {
  test.beforeEach(async ({ page }) => {
    // Force the real backend even if the dev server was started with mocks on.
    await page.addInitScript(() => {
      try {
        localStorage.setItem('rm.mocks', 'none')
        localStorage.removeItem('rm.mockRole')
      } catch {
        /* ignore */
      }
    })
  })

  test('opis, raport, symulacja, podział ryzyk, pobranie DOCX', async ({ page }) => {
    await page.goto('/analizy/nowa')
    await expect(page.getByRole('heading', { level: 1, name: /Co planujesz zbudować/ })).toBeVisible()
    await expectNoA11yViolations(page, '1.1 empty')

    await page.getByLabel('Opis inwestycji').fill(DESCRIPTION)
    // Draft is created ~800 ms after typing stops; chips appear from the regex/AI reading.
    await expect(page.getByText(/kanalizacja sanitarna/i).first()).toBeVisible({ timeout: 30_000 })
    await expectNoA11yViolations(page, '1.1 chips')

    const run = page.getByRole('button', { name: 'Uruchom analizę' })
    await expect(run).toBeEnabled()
    await run.click()

    await expect(page).toHaveURL(/\/analizy\/AN-\d{4}-\d{4}$/, { timeout: 30_000 })
    const code = page.url().split('/').pop()!
    const cards = page.getByTestId('question-cards')
    await expect(cards).toBeVisible({ timeout: 60_000 })
    await expect(cards.locator('[data-testid^="q-"]')).toHaveCount(3)
    await expect(page.getByTestId('case-row').first()).toBeVisible()
    await expect(page.getByTestId('funnel')).toBeAttached()
    await expectNoA11yViolations(page, '1.2 report')

    await page.getByRole('link', { name: 'Symulacja' }).click()
    await expect(page).toHaveURL(new RegExp(`/analizy/${code}/symulacja`))
    await expect(page.locator('svg[role="img"]').first()).toBeVisible({ timeout: 30_000 })
    await expectNoA11yViolations(page, '1.4 simulation')

    await page.getByRole('link', { name: 'Podział ryzyk i pakiet' }).click()
    await expect(page).toHaveURL(new RegExp(`/analizy/${code}/pakiet`))
    await expect(page.getByText('Po stronie zamawiającego')).toBeVisible({ timeout: 30_000 })
    await expectNoA11yViolations(page, '1.5 allocation')

    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 60_000 }),
      page.getByRole('button', { name: 'Pobierz DOCX' }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/^AN-\d{4}-\d{4}.*\.docx$/)
  })
})
