// Jury path (a) on the real backend: Projekty -> Karta (pilot + OCID auto card) -> Graf powiązań -> Przegląd (no
// decision) -> Dokumenty: upload of one organizer file -> "Co się zmieniło".
// Uses the demo persona "expert" because the upload writes; no review decision is taken.
// Run: npx playwright test e2e/demo-a-projects.spec.ts --project=live
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import { expectNoA11yViolations } from './a11y'
import { anyOcid, loginAs, realBackend } from './helpers'

const ORGANIZER_FILE = resolve(
  import.meta.dirname,
  '../../materials/organizer_cases/Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf',
)
const ZAGRODNO = 'RM-2026-002'

test.describe('demo (a): od projektu do dowodu', () => {
  test.beforeEach(async ({ page }) => realBackend(page))

  test('Projekty, Steklin, auto karta BZP, graf powiązań, link do Przeglądu', async ({ page }) => {
    await loginAs(page.request, 'juror')
    await page.goto('/projekty')
    await expect(page.getByRole('heading', { level: 1, name: 'Projekty' })).toBeVisible()
    await expectNoA11yViolations(page, '2.2')

    // dispatchEvent: with the cached Chromium 1243 a real click here never gets its input ack (the sort itself works).
    await page.getByRole('button', { name: 'Opóźnienie' }).dispatchEvent('click')
    await expect(page.getByRole('columnheader', { name: /Opóźnienie/ })).toHaveAttribute('aria-sort', /ascending|descending/)

    await page.getByRole('link', { name: /Steklin/ }).first().click()
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
    test.skip(!existsSync(ORGANIZER_FILE), 'materials/organizer_cases/ not present')
    test.setTimeout(240_000)
    await loginAs(page.request, 'expert')
    await page.goto(`/projekty/${ZAGRODNO}/dokumenty`)
    await expect(page.getByText('Upuść PDF, DOCX albo ZIP')).toBeVisible()
    await expectNoA11yViolations(page, '2.5')

    await page.getByLabel('Wybierz plik z dysku').setInputFiles(ORGANIZER_FILE)
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
    await page.getByRole('link', { name: /małopolskie/ }).first().click()
    await expect(page.getByRole('heading', { name: 'małopolskie' })).toBeVisible()
    await expect(page.getByText('SYGNAŁY TERAZ')).toBeVisible()
  })
})
