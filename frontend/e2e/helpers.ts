import type { APIRequestContext, Page } from '@playwright/test'
import { expect } from '@playwright/test'

export const CSRF = { 'X-Requested-With': 'ex-ante' }

/** Always talk to the real backend, whatever VITE_MOCKS the dev server started with. */
export async function realBackend(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem('rm.mocks', 'none')
      localStorage.removeItem('rm.mockRole')
    } catch {
      /* ignore */
    }
  })
}

/** Passwordless demo persona: juror (read-only expert), expert (writes), admin. */
export async function loginAs(request: APIRequestContext, persona: 'juror' | 'expert' | 'admin') {
  const r = await request.post('/api/auth/demo-login', { data: { persona }, headers: CSRF })
  expect(r.ok(), `demo-login ${persona}: ${r.status()}`).toBeTruthy()
}

/** Creates and runs an analysis in this browser context (analyses are owner-only). Returns its code. */
export async function createAnalysis(
  request: APIRequestContext,
  documentIds: number[] = [],
): Promise<string> {
  const created = await request.post('/api/analyses', {
    headers: CSRF,
    data: {
      text: 'Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami, zaprojektuj i wybuduj, 7 mln zł brutto, 14 miesięcy, FEnIKS. [e2e]',
      document_ids: documentIds,
    },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const draft = (await created.json()) as { id?: string; code?: string }
  const code = (draft.id ?? draft.code) as string
  const run = await request.post(`/api/analyses/${code}/run`, { headers: CSRF, data: {} })
  expect(run.ok(), await run.text()).toBeTruthy()
  return code
}

/** A real OCID that has an automatic (unverified) BZP card. */
export async function anyOcid(request: APIRequestContext): Promise<string> {
  const r = await request.get('/api/monitoring/signals?limit=1')
  expect(r.ok()).toBeTruthy()
  const body = (await r.json()) as { items?: { ocid: string }[] } | { ocid: string }[]
  const items = Array.isArray(body) ? body : (body.items ?? [])
  return items[0].ocid
}

export const PUBLIC_PFU = 33366
