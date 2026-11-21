// Jury path (b) on the real backend, public (anonymous) user:
// 1.1 description + PFU upload -> Uruchom analizę -> 1.2 Raport -> 1.3 Czerwony długopis -> 1.4 Symulacja
// -> 1.5 Podział ryzyk -> PDF (and DOCX) download. Creates one [e2e] AN-… analysis per run.
// Run: npx playwright test e2e/demo-b-analysis.spec.ts --project=live
import { existsSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { expectNoA11yViolations } from './a11y'
import { PFU_FILE, realBackend } from './helpers'

const DESCRIPTION =
  'Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami w formule zaprojektuj i wybuduj, ' +
  'budżet 7 mln zł brutto, termin 14 miesięcy, finansowanie FEnIKS. [e2e]'
// Without the local PFU file (helpers.PFU_FILE) the Red Pen step is skipped.
const PFU = PFU_FILE

test.describe('demo (b): nowa inwestycja do pakietu', () => {
  test.beforeEach(async ({ page }) => realBackend(page))

  test('opis i PFU, raport, czerwony długopis, symulacja, podział ryzyk, PDF', async ({ page }) => {
    test.setTimeout(240_000)
    const withPfu = existsSync(PFU)
    await page.goto('/analizy/nowa')
    await expect(page.getByRole('heading', { level: 1, name: /Co planujesz zbudować/ })).toBeVisible()
    await expectNoA11yViolations(page, '1.1 empty')

    await page.getByLabel('Opis inwestycji').fill(DESCRIPTION)
    await expect(page.getByText(/kanalizacja sanitarna/i).first()).toBeVisible({ timeout: 30_000 })
    if (withPfu) {
      // The PFU is a public tender document; confidential files need the sovereign model (503 while it is down).
      await page.getByLabel(/Dokument jest publiczny/).check()
      await page.getByTestId('file-drop').locator('input[type="file"]').setInputFiles(PFU)
      await expect(page.getByRole('button', { name: /Usuń .*PFU_Kaniów/ })).toBeVisible({ timeout: 60_000 })
    }
    await expectNoA11yViolations(page, '1.1 chips')

    const run = page.getByRole('button', { name: 'Uruchom analizę' })
    await expect(run).toBeEnabled({ timeout: 30_000 })
    await run.click()

    await expect(page).toHaveURL(/\/analizy\/AN-\d{4}-\d{4}$/, { timeout: 30_000 })
    const code = page.url().split('/').pop()!
    const cards = page.getByTestId('question-cards')
    await expect(cards).toBeVisible({ timeout: 60_000 })
    await expect(cards.locator('[data-testid^="q-"]')).toHaveCount(3)
    await expect(page.getByTestId('case-row').first()).toBeVisible()
    await expect(page.getByTestId('funnel')).toBeAttached()
    await expectNoA11yViolations(page, '1.2 report')

    if (withPfu) {
      await page.getByRole('link', { name: 'Czerwony długopis' }).click()
      await expect(page).toHaveURL(new RegExp(`/analizy/${code}/dokumenty/\\d+`))
      await expect(page.getByTestId('page-text')).toBeVisible({ timeout: 60_000 })
      const notes = page.getByRole('complementary')
      await expect(notes.getByRole('heading', { name: 'Uwagi do dokumentów' })).toBeVisible()
      await notes.getByRole('button').first().click({ timeout: 60_000 })
      await expect(page.getByTestId('note-card').first()).toBeVisible()
      await expectNoA11yViolations(page, '1.3 red pen')
    }

    await page.getByRole('link', { name: 'Symulacja' }).click()
    await expect(page).toHaveURL(new RegExp(`/analizy/${code}/symulacja`))
    await expect(page.locator('svg[role="img"]').first()).toBeVisible({ timeout: 30_000 })
    await expectNoA11yViolations(page, '1.4 simulation')

    await page.getByRole('link', { name: 'Podział ryzyk i pakiet' }).click()
    await expect(page).toHaveURL(new RegExp(`/analizy/${code}/pakiet`))
    await expect(page.getByText('Po stronie zamawiającego')).toBeVisible({ timeout: 30_000 })
    await expectNoA11yViolations(page, '1.5 allocation')

    const exportBox = page.getByTestId('export-buttons')
    const [pdf] = await Promise.all([
      page.waitForEvent('download', { timeout: 90_000 }),
      exportBox.getByRole('button', { name: 'PDF', exact: true }).click(),
    ])
    expect(pdf.suggestedFilename()).toMatch(/^AN-\d{4}-\d{4}.*\.pdf$/)
    const [docx] = await Promise.all([
      page.waitForEvent('download', { timeout: 90_000 }),
      exportBox.getByRole('button', { name: 'Pobierz DOCX' }).click(),
    ])
    expect(docx.suggestedFilename()).toMatch(/^AN-\d{4}-\d{4}.*\.docx$/)
  })
})
