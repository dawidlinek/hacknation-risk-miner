// Rehearsal of the organizers' 11:00 live test (docs/submission/test_1100_runbook.md), through the UI like a person:
//  A. /zrodla: upload the extra project record (XLSX / CSV / TXT ...), test run, approve + import, open the card,
//     "Eksportuj rekord" -> PDF + Markdown.
//  B. /analizy/nowa: the new investment description (pasted text, or an uploaded DOCX / PDF / TXT), Uruchom analizę,
//     report, Czerwony długopis (approve the AI notes so they enter the pack), Symulacja, Podział ryzyk i pakiet,
//     pack PDF + DOCX.
// It writes to the database, so it is skipped unless RM_REHEARSAL=1. Inputs and outputs:
//   RM_RECORD=<file>[,<file>]   default: the four docs/submission/dryrun_inputs/dryrun_rekord_projektu.* files
//   RM_DESC=<file>[,<file>]     default: dryrun_opis_inwestycji.{docx,pdf,txt} + one pasted-text run
//   RM_OUT=<dir>                downloads (default: docs/submission/dryrun_outputs/e2e)
//   E2E_BASE_URL=https://exante.linek.dev to run against the deployed app (default: local 127.0.0.1:5173)
// Run: RM_REHEARSAL=1 npx playwright test e2e/rehearsal-1100.spec.ts --project=live
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, resolve } from 'node:path'
import { expect, type Page, test } from '@playwright/test'
import { realBackend } from './helpers'

const ON = process.env.RM_REHEARSAL === '1'
const IN = resolve(import.meta.dirname, '../../docs/submission/dryrun_inputs')
const OUT = process.env.RM_OUT ?? resolve(import.meta.dirname, '../../docs/submission/dryrun_outputs/e2e')
const list = (v: string | undefined, dflt: string[]) =>
  v ? v.split(',').map((x) => resolve(x.trim())) : dflt
const RECORDS = list(
  process.env.RM_RECORD,
  ['xlsx', 'csv', 'txt']
    .map((e) => `${IN}/dryrun_rekord_projektu.${e}`)
    .concat(`${IN}/dryrun_rekord_projektu_pola.txt`),
)
const DESCS = list(
  process.env.RM_DESC,
  ['docx', 'pdf', 'txt'].map((e) => `${IN}/dryrun_opis_inwestycji.${e}`),
)
const PASTE = process.env.RM_PASTE ?? `${IN}/dryrun_opis_inwestycji.txt`
const timings: Record<string, number> = {}

test.skip(!ON, 'rehearsal only: set RM_REHEARSAL=1 (writes test records to the database)')
test.describe.configure({ mode: 'serial' })

async function loginUi(page: Page) {
  await page.goto('/zaloguj')
  await page.getByRole('button', { name: 'Zaloguj się' }).first().click()
  await expect(page).not.toHaveURL(/\/zaloguj/, { timeout: 15_000 })
}

async function save(page: Page, click: () => Promise<void>, name: string) {
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 120_000 }), click()])
  mkdirSync(OUT, { recursive: true })
  const path = `${OUT}/${name}${dl.suggestedFilename().replace(/^.*(\.[a-z]+)$/, '$1')}`
  await dl.saveAs(path)
  return path
}

/** Wait for a busy line to appear (it may take a moment) and then to disappear. */
async function settle(page: Page, busy: string | RegExp) {
  const line = page.getByText(busy).first()
  await line.waitFor({ state: 'visible', timeout: 10_000 }).catch(() => undefined)
  await expect(line).toBeHidden({ timeout: 180_000 })
}

test.beforeEach(async ({ page }) => realBackend(page))

for (const file of RECORDS) {
  test(`A: rekord projektu z ${basename(file)}`, async ({ page }) => {
    test.setTimeout(240_000)
    const t0 = Date.now()
    await loginUi(page)
    await page.goto('/zrodla')
    await page.getByLabel('Wybierz pliki do importu').setInputFiles(file)
    const agent = page.getByRole('region', { name: 'Agent importu' })
    await expect(agent.getByText('Tak mapuję kolumny pliku na pola bazy:')).toBeVisible({ timeout: 60_000 })
    // a file with amounts asks "netto czy brutto?"; the organizer layout has none
    const q = agent.getByRole('button', { name: /Brutto, z VAT/ })
    if (await q.isVisible().catch(() => false)) await q.click()
    await agent.getByRole('button', { name: /Wykonaj próbny import/ }).click()
    await expect(agent.getByText(/Próbny import, transakcja wycofana/)).toBeVisible({ timeout: 60_000 })
    await agent.getByRole('button', { name: 'Zatwierdź i importuj' }).click()
    await expect(agent.getByText('Import zakończony')).toBeVisible({ timeout: 120_000 })
    const open = agent.getByRole('link', { name: /Otwórz kartę projektu/ }).first()
    await expect(open).toBeVisible({ timeout: 60_000 })
    const linkInfo = await agent.getByRole('list', { name: 'Zaimportowane projekty' }).innerText()
    await open.click()
    await expect(page).toHaveURL(/\/projekty\/[^/]+$/)
    const id = decodeURIComponent(page.url().split('/').pop()!)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 30_000 })
    timings[`A ${basename(file)} import+card s`] = (Date.now() - t0) / 1000
    const tag = basename(file)
      .replace(/\.[a-z]+$/, '')
      .replace('dryrun_rekord_projektu', 'rekord')
    for (const [fmt, label] of [
      ['pdf', 'PDF'],
      ['md', 'Markdown'],
    ] as const) {
      await save(
        page,
        async () => {
          await page.getByRole('button', { name: /Eksportuj rekord/ }).click()
          await page.getByRole('menuitem', { name: label }).click()
        },
        `${tag}_${basename(file).split('.').pop()}_${id}_${fmt}`,
      )
    }
    timings[`A ${basename(file)} total s`] = (Date.now() - t0) / 1000
    console.log(
      `A ${basename(file)}: ${id}; ${linkInfo.replace(/\s+/g, ' ')}; ${timings[`A ${basename(file)} total s`]} s`,
    )
  })
}

async function flowB(page: Page, label: string, opts: { file?: string; paste?: string; isPublic: boolean }) {
  const t0 = Date.now()
  await loginUi(page)
  await page.goto('/analizy/nowa')
  await expect(page.getByLabel('Opis inwestycji')).toBeVisible({ timeout: 30_000 })
  // the public/confidential checkbox was removed on 21.11 (uploads here are public); tick it only where it still exists
  const publicBox = page.getByLabel(/Dokument jest publiczny/)
  if (opts.isPublic && (await publicBox.count()) > 0) await publicBox.check()
  if (opts.paste) await page.getByLabel('Opis inwestycji').fill(opts.paste)
  if (opts.file) {
    await page.getByTestId('file-drop').locator('input[type="file"]').setInputFiles(opts.file)
    await expect(
      page.getByRole('button', { name: new RegExp(`Usuń .*${basename(opts.file).split('.')[0]}`) }),
    ).toBeVisible({
      timeout: 90_000,
    })
  }
  const run = page.getByRole('button', { name: 'Uruchom analizę' })
  await expect(run).toBeEnabled({ timeout: 60_000 })
  // let the AI feature reading finish: "Czytamy opis i dokumenty…" shows up once the draft exists, then goes away
  await settle(page, 'Czytamy opis i dokumenty…')
  const chips = await page
    .getByTestId('chips')
    .innerText()
    .catch(() => '')
  await run.click()
  await expect(page).toHaveURL(/\/analizy\/AN-\d{4}-\d{4}$/, { timeout: 60_000 })
  const code = page.url().split('/').pop()!
  await expect(page.getByTestId('question-cards')).toBeVisible({ timeout: 90_000 })
  timings[`B ${label} report s`] = (Date.now() - t0) / 1000
  mkdirSync(OUT, { recursive: true })
  writeFileSync(`${OUT}/${code}_${label}_raport.txt`, await page.locator('main').innerText())
  if (opts.file) {
    await page.getByRole('link', { name: 'Czerwony długopis' }).click()
    await expect(page.getByTestId('page-text')).toBeVisible({ timeout: 90_000 })
    // the AI notes arrive a few seconds after the rule notes ("Model AI czyta dokument…")
    await settle(page, /Model AI czyta dokument/)
    // approve every AI note still waiting (in a real run: approve the right ones, reject wrong ones with a reason)
    const ids = await page
      .locator('aside button[id^="u"]')
      .filter({ hasText: /\bAI\b/ })
      .evaluateAll((els) => els.map((e) => e.id))
    for (const nid of ids) {
      await page.locator(`#${nid}`).click()
      const approve = page.getByRole('button', { name: 'Zatwierdź', exact: true })
      if (
        await approve.waitFor({ state: 'visible', timeout: 3_000 }).then(
          () => true,
          () => false,
        )
      ) {
        await approve.click()
        await expect(approve).toBeHidden({ timeout: 15_000 })
      }
    }
    timings[`B ${label} red pen s`] = (Date.now() - t0) / 1000
  }
  await page.getByRole('link', { name: 'Symulacja' }).click()
  await expect(page.locator('svg[role="img"]').first()).toBeVisible({ timeout: 60_000 })
  await page.getByRole('link', { name: 'Podział ryzyk i pakiet' }).click()
  await expect(page.getByText('Po stronie zamawiającego')).toBeVisible({ timeout: 60_000 })
  const box = page.getByTestId('export-buttons')
  const pdf = await save(
    page,
    () => box.getByRole('button', { name: 'PDF', exact: true }).click(),
    `${code}_${label}_pakiet`,
  )
  const docx = await save(
    page,
    () => box.getByRole('button', { name: 'Pobierz DOCX' }).click(),
    `${code}_${label}_pakiet`,
  )
  timings[`B ${label} total s`] = (Date.now() - t0) / 1000
  console.log(
    `B ${label}: ${code}; ${timings[`B ${label} total s`]} s; ${pdf}; ${docx}; chips: ${chips.replace(/\s+/g, ' ').slice(0, 300)}`,
  )
}

test('B: opis wklejony jako tekst (publiczny)', async ({ page }) => {
  test.setTimeout(300_000)
  await flowB(page, 'tekst', { paste: readFileSync(PASTE, 'utf-8'), isPublic: true })
})

for (const file of DESCS) {
  test(`B: opis z pliku ${basename(file)} (publiczny)`, async ({ page }) => {
    test.setTimeout(300_000)
    await flowB(page, basename(file).split('.').pop()!, { file, isPublic: true })
  })
}

test('B: domyślnie poufny (PDF, bez modelu w chmurze)', async ({ page }) => {
  test.setTimeout(300_000)
  await page.goto('/analizy/nowa')
  test.skip(
    (await page.getByLabel(/Dokument jest publiczny/).count()) === 0,
    'no confidential choice on this screen any more',
  )
  await flowB(page, 'poufny_pdf', {
    file: DESCS.find((f) => f.endsWith('.pdf')) ?? DESCS[0],
    isPublic: false,
  })
})

test.afterAll(() => {
  if (!ON) return
  mkdirSync(OUT, { recursive: true })
  writeFileSync(`${OUT}/timings.json`, JSON.stringify(timings, null, 1))
  console.log(JSON.stringify(timings, null, 1))
})
