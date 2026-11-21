// Jury path (a) on the real backend: Projekty -> Karta (pilot + OCID auto card) -> Graf powiązań -> Przegląd (no
// decision) -> Dokumenty: upload of one organizer file -> "Co się zmieniło".
// The upload runs only with E2E_UPLOAD=1 (it writes to the case base); no review decision is taken.
// Run: npx playwright test e2e/demo-a-projects.spec.ts --project=live
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import { expectNoA11yViolations } from './a11y'
import { anyOcid, login, realBackend } from './helpers'

const ORGANIZER_FILE = resolve(
  import.meta.dirname,
  '../../materials/organizer_cases/Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf',
)
const ZAGRODNO = 'RM-2026-002'

test.describe('demo (a): od projektu do dowodu', () => {
  test.beforeEach(async ({ page }) => realBackend(page))

  test('Projekty, Steklin, auto karta BZP, graf powiązań, link do Przeglądu', async ({ page }) => {
    await login(page.request)
    await page.goto('/projekty')
    await expect(page.getByRole('heading', { level: 1, name: 'Projekty' })).toBeVisible()
    await expectNoA11yViolations(page, '2.2')

    // Sorting: after an in-page sort, real pointer input stops being acknowledged in headless Chromium 1243
    // (reported to F2). The sort is checked with dispatched clicks, then the sorted URL is loaded fresh.
    const delayHeader = page.getByRole('columnheader', { name: /Opóźnienie/ })
    const sortBtn = page.getByRole('button', { name: 'Opóźnienie' })
    const first = await delayHeader.getAttribute('aria-sort')
    await sortBtn.dispatchEvent('click')
    await expect(delayHeader).not.toHaveAttribute('aria-sort', first ?? 'none')
    await expect(delayHeader).toHaveAttribute('aria-sort', /ascending|descending/)
    await page.goto('/projekty?sort=delay&kier=desc')
    await expect(page.getByRole('columnheader', { name: /Opóźnienie/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    )

    await page
      .getByRole('link', { name: /Steklin/ })
      .first()
      .click()
    await expect(page.getByText('277 dni', { exact: false }).first()).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Przebieg' })).toBeVisible()
    await expectNoA11yViolations(page, '2.3 pilot')

    await page.getByRole('link', { name: 'Graf powiązań' }).click()
    await page.getByRole('button', { name: /R04/ }).click()
    await expect(page.getByRole('button', { name: /R04/ })).toHaveAttribute('aria-pressed', 'true')
    await expectNoA11yViolations(page, '2.4')

    await page.getByRole('link', { name: 'Sprawdź w Przeglądzie' }).click()
    await expect(page).toHaveURL(/\/przeglad\?.*sprawa=\d+/)
    await expect(page.locator('[data-review-question]')).toBeVisible()

    const ocid = await anyOcid(page.request)
    await page.goto(`/projekty/${ocid}`)
    await expect(page.locator('h1').first()).toBeVisible()
    await expect(page.getByText(/Nie ma takiego projektu/)).toHaveCount(0)
    await expectNoA11yViolations(page, '2.3 auto card')
  })

  test('Dokumenty: dokument organizatora i "Co się zmieniło"', async ({ page }) => {
    // Writes proposals, review items and an alert into the shared case base: opt-in only (E2E_UPLOAD=1, rehearsal VM).
    test.skip(process.env.E2E_UPLOAD !== '1', 'set E2E_UPLOAD=1 to upload an organizer file')
    test.skip(!existsSync(ORGANIZER_FILE), 'materials/organizer_cases/ not present')
    test.setTimeout(240_000)
    await login(page.request)
    await page.goto(`/projekty/${ZAGRODNO}/dokumenty`)
    await expect(page.getByText('Upuść PDF, DOCX albo ZIP')).toBeVisible()
    await expectNoA11yViolations(page, '2.5')

    // One appended byte: a different sha256, so the jury's own upload of the real file is never a duplicate.
    const bytes = Buffer.concat([readFileSync(ORGANIZER_FILE), Buffer.from('\n')])
    await page.getByLabel('Wybierz plik z dysku').setInputFiles({
      name: 'e2e_protokol_zagrodno.pdf',
      mimeType: 'application/pdf',
      buffer: bytes,
    })
    const panel = page.getByRole('region', { name: 'Analiza dokumentu' })
    await expect(panel).toBeVisible({ timeout: 60_000 })

    // Extraction runs as a job; link the document once facts are read (the button shows only then).
    const link = panel.getByRole('button', { name: 'Powiąż z projektem' })
    const diff = page.getByRole('heading', { name: 'Co się zmieniło' })
    await expect(link.or(diff)).toBeVisible({ timeout: 180_000 })
    if (await link.isVisible()) await link.click()
    await expect(diff).toBeVisible({ timeout: 120_000 })
    await expectNoA11yViolations(page, '2.5 new document')
  })

  test('Monitoring: mapa, województwo, powiat', async ({ page }) => {
    await page.goto('/monitoring')
    await expect(page.getByRole('heading', { name: /Województwa/ })).toBeVisible()
    await page
      .getByRole('link', { name: /małopolskie/ })
      .first()
      .click()
    await expect(page.getByRole('heading', { name: 'małopolskie' })).toBeVisible()
    await expect(page.getByText('SYGNAŁY TERAZ')).toBeVisible()
  })
})
