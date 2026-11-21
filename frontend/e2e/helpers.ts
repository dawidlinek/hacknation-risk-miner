import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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

/** A real public PFU from the docs_22 download (local data, not in git). */
export const PFU_FILE = resolve(
  import.meta.dirname,
  '../../data/raw/docs_22/2026-11-21/RM-2026-013/files/9cdc085eedd413b1_PFU_Kaniów.pdf',
)

/** Uploads the public PFU in this browser context; returns its document id, or null when the file is absent. */
export async function uploadPublicPfu(request: APIRequestContext): Promise<number | null> {
  if (!existsSync(PFU_FILE)) return null
  const r = await request.post('/api/documents/upload', {
    headers: CSRF,
    multipart: {
      file: { name: 'PFU_Kaniow_e2e.pdf', mimeType: 'application/pdf', buffer: readFileSync(PFU_FILE) },
      sensitivity: 'public',
    },
  })
  expect(r.ok(), await r.text()).toBeTruthy()
  const body = (await r.json()) as { document_id?: number; id?: number }
  return (body.document_id ?? body.id) as number
}
