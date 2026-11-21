// Pure helpers for 1.1 Nowa analiza (frontend.md §2 1.1).
import type { AnalysisDraft, DocType, FeatureChip, UploadedDocument } from '@/api/contracts/analyses'

/** Server extras on top of the frontend contract. */
export type Draft = AnalysisDraft & {
  ai_features?: { job_id: number | null; status: string; errors?: unknown; note?: string }
  ai_pending?: boolean
  stale_sections?: string[]
  title?: string
}

export type Chip = FeatureChip & { origin?: 'CALC' | 'AI' | 'SOURCE'; review_status?: string }

export const MIN_TEXT = 20

/** The draft is created once: when the text reaches 20 characters or the first document is uploaded. */
export function readyToCreate(text: string, docIds: number[]): boolean {
  return text.trim().length >= MIN_TEXT || docIds.length > 0
}

/** CTA "Uruchom analizę": text of 20+ characters or one document, and nothing still uploading. */
export function canRun(text: string, docIds: number[], uploading: boolean): boolean {
  return !uploading && readyToCreate(text, docIds)
}

/** "6,2" / "6.2" / "6 200" → number; null when not a number. */
export function parseNumber(s: string): number | null {
  const t = s.replace(/\s| /g, '').replace(',', '.')
  if (!t || !/^-?\d+(\.\d+)?$/.test(t)) return null
  return Number(t)
}

/** "7 mln", "7,5 mln zł", "850 tys.", "7000000" → PLN; `netto` in the text marks the value as net. */
export function parseMoney(s: string): { amount: number; vat: 'gross' | 'net' } | null {
  const low = s.toLowerCase()
  const vat = /netto/.test(low) ? 'net' : 'gross'
  const m = /(\d[\d\s ]*(?:[.,]\d+)?)\s*(mld|mln|milion\w*|tys\.?|tysi\w*)?/.exec(low)
  if (!m) return null
  const n = parseNumber(m[1])
  if (n === null) return null
  const mult = m[2]?.startsWith('mld')
    ? 1e9
    : m[2]?.startsWith('mln') || m[2]?.startsWith('milion')
      ? 1e6
      : m[2]?.startsWith('tys')
        ? 1e3
        : 1
  return { amount: n * mult, vat }
}

/** Value to PATCH for a chip edited in its editor; null = invalid input. */
export function patchValue(chip: Pick<FeatureChip, 'editor'>, input: string): unknown | null {
  switch (chip.editor) {
    case 'number':
    case 'months':
      return parseNumber(input)
    case 'money': {
      const m = parseMoney(input)
      return m ? { amount: m.amount.toFixed(2), currency: 'PLN', vat_basis: m.vat } : null
    }
    default:
      return input.trim() || null
  }
}

/** Upload response → UploadedDocument (frontend contract). */
export interface UploadResponse {
  document_id: number
  filename: string
  pages: number
  doc_type: { code: string } | string
  sensitivity: 'confidential' | 'public'
  text_status?: 'ok' | 'needs_ocr' | 'failed'
  duplicate?: boolean
}

const DOC_TYPES: DocType[] = ['PFU', 'PPU', 'SWZ', 'umowa', 'inne']

export function adaptUpload(u: UploadResponse): UploadedDocument & { text_status?: string } {
  const raw = typeof u.doc_type === 'string' ? u.doc_type : u.doc_type?.code
  const up = (raw ?? '').toUpperCase()
  const dt: DocType = up === 'UMOWA' ? 'umowa' : (DOC_TYPES.find((d) => d === up) ?? 'inne')
  return {
    document_id: u.document_id,
    filename: u.filename,
    doc_type: dt,
    pages: u.pages,
    label: `${dt === 'inne' ? 'dokument' : dt}, ${u.pages} s.`,
    sensitivity: u.sensitivity,
    text_status: u.text_status,
  }
}

export const ACCEPT = '.pdf,.docx,.doc,.odt'
export const MAX_MB = 50

export function fileError(f: { name: string; size: number }): string | null {
  const ext = f.name.toLowerCase().split('.').pop() ?? ''
  if (!['pdf', 'docx', 'doc', 'odt'].includes(ext) || f.size > MAX_MB * 1024 * 1024) {
    return 'Nie udało się wczytać pliku. Obsługujemy PDF i DOCX do 50 MB.'
  }
  return null
}

export function aiStatusLine(
  d: Pick<Draft, 'ai_features' | 'ai_pending'>,
): { text: string; tone: 'busy' | 'note' } | null {
  if (d.ai_pending) return { text: 'Czytamy opis i dokumenty…', tone: 'busy' }
  if (d.ai_features?.note) return { text: d.ai_features.note, tone: 'note' }
  return null
}
