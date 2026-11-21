import type { DocsView } from './types'

/** Selection key -> where it lives. Keys: expected key, public key. */
export function findSelection(view: DocsView, key: string | null | undefined) {
  if (!key) return null
  const e = view.expected.find((x) => x.key === key)
  if (e) return { type: 'expected' as const, item: e }
  const p = view.publicDocs.find((x) => x.key === key)
  return p ? { type: 'public' as const, item: p } : null
}

export const docsHeading = (view: DocsView) => `${view.have} z ${view.expectedTotal}`

/** Uploads accept PDF, DOCX and ZIP only (api_contract §3.3); max 50 MB. */
export const ACCEPT = '.pdf,.docx,.doc,.odt,.zip'
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024
export function validateUpload(file: { name: string; size: number }): string | null {
  if (file.size > MAX_UPLOAD_BYTES) return 'Plik jest większy niż 50 MB.'
  if (!/\.(pdf|docx?|odt|zip)$/i.test(file.name)) return 'Obsługujemy pliki PDF, DOCX i ZIP.'
  return null
}

export const READ_ONLY_REASON = 'To konto jest tylko do odczytu, dodawanie dokumentów jest wyłączone.'
