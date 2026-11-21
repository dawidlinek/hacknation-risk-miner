// Pure helpers for 1.3 Czerwony długopis (frontend.md §2 1.3). Page text, marks and notes come from
// GET /api/analyses/{id}/redpen/{doc}; marks are character offsets inside each paragraph.
import type { RedPenMark, RedPenNote, RedPenOut, RedPenPage, RedPenParagraph } from '@/api/contracts/redpen'
import { plural } from '@/lib/plural'

/** Server extras on top of the frontend contract. */
export type RedPen = RedPenOut & {
  limitations?: string[]
  case_hints?: { risk_code: string; text: string; cases: { label: string; href: string }[] }[]
  job?: { job_id: number; status: string } | null
}

export type Note = RedPenNote & {
  item_id?: number | null
  origin?: 'CALC' | 'AI'
  rule?: string | null
  state_label?: string | null
}

export interface Segment {
  text: string
  /** note numbers covering this piece ([] = plain text) */
  notes: string[]
  /** note numbers whose mark ends here (anchor goes after the piece) */
  endsHere: string[]
}

/** Split a paragraph into plain and marked pieces; overlapping marks are merged per piece. */
export function segments(p: RedPenParagraph): Segment[] {
  const text = p.text
  const marks: RedPenMark[] = p.marks
    .map((m) => ({ ...m, start: Math.max(0, m.start), end: Math.min(text.length, m.end) }))
    .filter((m) => m.end > m.start)
  if (!marks.length) return [{ text, notes: [], endsHere: [] }]
  const cuts = new Set<number>([0, text.length])
  for (const m of marks) {
    cuts.add(m.start)
    cuts.add(m.end)
  }
  const pts = [...cuts].sort((a, b) => a - b)
  const out: Segment[] = []
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i]
    const b = pts[i + 1]
    const covering = marks.filter((m) => m.start <= a && m.end >= b)
    out.push({
      text: text.slice(a, b),
      notes: covering.map((m) => m.note_no),
      endsHere: covering.filter((m) => m.end === b).map((m) => m.note_no),
    })
  }
  return out
}

export function notedPages(pages: RedPenPage[]): number[] {
  return pages.filter((p) => p.paragraphs.some((x) => x.marks.length)).map((p) => p.page_no)
}

/** Pages to step through: every page, or only those with marks (falls back to all when none has marks). */
export function stepPages(pages: RedPenPage[], onlyNoted: boolean): number[] {
  const all = pages.map((p) => p.page_no).sort((a, b) => a - b)
  if (!onlyNoted) return all
  const noted = notedPages(pages).sort((a, b) => a - b)
  return noted.length ? noted : all
}

export function neighbour(list: number[], current: number, dir: -1 | 1): number | null {
  const i = list.indexOf(current)
  if (i === -1) {
    const next = dir === 1 ? list.find((p) => p > current) : [...list].reverse().find((p) => p < current)
    return next ?? null
  }
  return list[i + dir] ?? null
}

export function countsLabel(found: number, missing: number): string {
  const a = `${found} ${plural(found, ['uwaga', 'uwagi', 'uwag'])}`
  if (!missing) return a
  return `${a}, ${missing} ${plural(missing, ['brak', 'braki', 'braków'])}`
}

export function noteFromHash(hash: string | undefined | null): string | null {
  const m = /^#?u([A-Za-z0-9]+)$/.exec(hash ?? '')
  return m ? m[1] : null
}

export function noteMeta(n: Note, docType: string): string {
  const parts = [...n.risk_codes]
  if (n.origin === 'AI') parts.push('AI')
  else if (n.kind === 'found') parts.push('reguła')
  if (n.page) parts.push(`${docType} s. ${n.page}${n.locator ? ` ${n.locator}` : ''}`)
  return parts.join(', ')
}

export const STATUS_LABEL: Record<string, string> = {
  auto: 'obliczenie',
  proposed: 'do przeglądu',
  approved: 'zatwierdzone',
  edited: 'poprawione',
  rejected: 'odrzucone',
}

/** Owner decisions are offered on AI notes still waiting for review. */
export function canDecide(n: Note): boolean {
  return n.origin === 'AI' && n.review_status === 'proposed' && typeof n.item_id === 'number'
}

/** "Dodaj do PPU" needs a clause and, for quoted notes, a verified quote. */
export function canAddClause(n: Note): boolean {
  if (!n.clause?.code) return false
  if (n.quote && !n.quote.verified) return false
  return true
}

export function firstPage(r: RedPen, wanted?: number | null): number | null {
  const all = r.pages.map((p) => p.page_no)
  if (wanted && all.includes(wanted)) return wanted
  return notedPages(r.pages)[0] ?? all[0] ?? null
}
