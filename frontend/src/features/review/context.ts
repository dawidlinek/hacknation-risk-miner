import { fmtInt } from '@/lib/format'

// Read-only context of a review card (backend review/card_read.py): what the item is about, a readable source,
// the proposed risk for catalogue proposals, and the queue facets. All values come from the API.

export interface AboutFact {
  label: string
  value: string
  href: string | null
}

export interface CardAbout {
  title: string | null
  lead: string | null
  facts: AboutFact[]
}

export interface CardSource {
  kind: 'document' | 'notice'
  title: string
  name: string | null
  label: string
  page: number | null
  href: string | null
  original_url: string | null
}

export interface CardStrength {
  level: 'ready' | 'check' | 'weak'
  label: string
}

export interface ProposalExample {
  quote: string
  verified: boolean
  label: string
  context: string | null
  href: string | null
}

export interface CardProposal {
  code: string
  name: string | null
  description: string | null
  sector: string
  sector_label: string
  copied_from_wodkan: boolean
  parent_code: string | null
  rationale: string | null
  proposed_by: string | null
  events: { code: string; name: string }[]
  cases: { texts: number; changes: number; codes: string[] }
  empirical: {
    n: number | null
    source: string | null
    category: string | null
    p_late: number | null
    delay_p50: number | null
    delay_p75: number | null
    cost_p75: number | null
    cost_p90: number | null
  } | null
  signals: { text: string; strength: number | null; doc_types: string[] }[]
  clauses: string[]
  mitigations: string[]
  examples: ProposalExample[]
  closest: { code: string; name: string; description: string | null; why: string }[]
}

export interface CardContext {
  about: CardAbout | null
  source: CardSource | null
  strength: CardStrength | null
  proposal: CardProposal | null
}

export interface RawContext {
  about?: CardAbout | null
  source?: CardSource | null
  strength?: CardStrength | null
  proposal?: CardProposal | null
}

export const contextOf = (raw: RawContext): CardContext => ({
  about: raw.about ?? null,
  source: raw.source ?? null,
  strength: raw.strength ?? null,
  proposal: raw.proposal ?? null,
})

export interface Facet {
  key: string
  label: string
  n: number
}

export interface ReviewFacets {
  total: number
  types: Facet[]
  projects: Facet[]
  strength: Facet[]
}

export interface QueueFilter {
  type?: string
  project?: string
  sort?: 'strength' | 'queue'
  /** '' clears the ?ryzyko= risk-code filter */
  code?: string
}

/** The question without the subject when the backend appended it ("Które ryzyko opisuje to zdarzenie? <title>"). */
export function questionOnly(question: string, title: string | null | undefined): string {
  if (!title) return question
  const q = question.trim()
  if (q !== title && q.endsWith(title)) return q.slice(0, q.length - title.length).trim()
  return q
}

const pl = (n: number) => fmtInt(n)
export const pct = (x: number | null | undefined) =>
  x === null || x === undefined ? null : `${(x * 100).toLocaleString('pl-PL', { maximumFractionDigits: 1 })}%`

/** Plain-Polish lines saying how many cases stand behind a catalogue proposal. */
export function proposalEvidence(p: CardProposal): string[] {
  const out: string[] = []
  if (p.cases.texts > 0) {
    const codes = p.cases.codes.join(', ')
    out.push(
      `Model przypisał ${codes === p.code ? 'temu ryzyku' : `kodom ${codes}`} ${pl(p.cases.texts)} opisów przyczyn zmian umów (${pl(p.cases.changes)} zmian w BZP).`,
    )
  }
  const e = p.empirical
  if (e?.n) {
    const bits = [
      e.delay_p50 !== null ? `mediana wydłużenia terminu ${pl(e.delay_p50)} dni` : null,
      e.delay_p75 !== null ? `co czwarta zmiana ponad ${pl(e.delay_p75)} dni` : null,
      e.cost_p75 !== null ? `wzrost kosztu do ${pct(e.cost_p75)} w 75% przypadków` : null,
      e.p_late !== null ? `${pct(e.p_late)} umów po terminie` : null,
    ].filter(Boolean)
    out.push(
      `Analiza ogłoszeń BZP${
        e.source
          ? ` (${e.source
              .replace(/^BZP_?/, '')
              .replace(/_(\d{4})_(\d{4})$/, '$1–$2')
              .replace(/^(\d{4})_(\d{4})$/, '$1–$2')
              .replace(/_/g, ' ')})`
          : ''
      }: ${pl(e.n)} zmian w kategorii „${e.category ?? p.name}”${bits.length ? `, ${bits.join(', ')}` : ''}.`,
    )
  }
  return out
}
