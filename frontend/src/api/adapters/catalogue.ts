// Real GET /api/catalogue/view (J11) -> api/contracts/catalogue.ts.
import type { CatalogueItem, CatalogueOut, CatalogueRisk } from '@/api/contracts/catalogue'
import { fmtDateTime } from '@/lib/dates'
import type { RealNum } from './real'

interface RealRisk {
  code: string
  name: string
  effects: string | null
  description: string | null
  version: number
  parts: { k: string; v: string }[]
  counts: { approved: number; proposed: number }
  quality?: { note: string; precision?: RealNum; recall?: RealNum; review_href?: string } | null
}

export interface RealCatalogue {
  version: string
  risks: RealRisk[]
  proposals: {
    id: number
    review_item_id: number | null
    title: string
    description: string | null
    evidence_text: string | null
    merge_suggestion: string | null
  }[]
  weights: { feature: string; label: string; w: number; main?: boolean }[]
  subsectors: { code: string; name: string }[]
  doc_types: { code: string; name: string; phase?: string }[]
  checklists: { code: string; phase?: string; text: string }[]
  clauses: { code: string; title?: string; name?: string; text?: string }[]
  versions: { label: string; summary: string | null; actor: string | null; at: string }[]
}

const countsLabel = (c: { approved: number; proposed: number }) => {
  const parts = [
    c.approved > 0 ? `${c.approved} zatw.` : null,
    c.proposed > 0 ? `${c.proposed} do przeglądu` : null,
  ].filter(Boolean)
  return parts.length ? parts.join(', ') : 'brak zdarzeń'
}

function reviewTarget(href: string | undefined): { rodzaj: string; ryzyko: string } | null {
  if (!href) return null
  const code = /code=([A-Z0-9.]+)/.exec(href)?.[1]
  return code ? { rodzaj: 'zdarzenia', ryzyko: code } : null
}

const adaptRisk = (r: RealRisk): CatalogueRisk => {
  const q = r.quality
  const detailBits = [
    q?.precision ? `precyzja ${q.precision.display}` : null,
    q?.recall ? `pokrycie ${q.recall.display}` : null,
  ].filter(Boolean)
  const n = q?.precision?.prov?.n
  // Orange means "needs attention": only when a measured precision or recall is below 0.6.
  const measured = [q?.precision?.value, q?.recall?.value].filter((x): x is number => typeof x === 'number')
  const attention = measured.length > 0 && Math.min(...measured) < 0.6
  return {
    code: r.code,
    title: r.name,
    effect: r.effects ?? r.description ?? '',
    counts_label: countsLabel(r.counts),
    parts: r.parts,
    quality: q
      ? {
          badge: q.note,
          attention,
          detail: `W zbiorze wzorcowym${n ? ` (n = ${n})` : ''} reguły mają ${detailBits.join(', ')}. Pozostałe przypadki ocenia model, a zatwierdzasz Ty.`,
          review: reviewTarget(q.review_href),
        }
      : null,
  }
}

const who = (actor: string | null, at: string) => `${actor ?? 'system'}, ${fmtDateTime(at, { short: true })}`

export function adaptCatalogue(raw: RealCatalogue): CatalogueOut {
  const item = (code: string, name: string, detail?: string): CatalogueItem => ({ code, name, detail })
  return {
    version: raw.version,
    updated_at: raw.versions[0]?.at ?? null,
    risks: raw.risks.map(adaptRisk),
    proposals: raw.proposals.map((p) => ({
      id: p.id,
      review_item_id: p.review_item_id,
      title: p.title,
      detail: p.description,
      source_label: p.evidence_text,
      merge_target: p.merge_suggestion,
    })),
    weights: raw.weights.map((w) => ({
      key: w.feature,
      label: w.label,
      value: Math.round(w.w * 100),
      main: Boolean(w.main),
    })),
    versions: raw.versions.map((v) => ({
      label: v.label,
      summary: v.summary ?? '',
      who: who(v.actor, v.at),
    })),
    subsectors: raw.subsectors.map((s) => item(s.code, s.name)),
    doc_types: raw.doc_types.map((d) => item(d.code, d.name, d.phase)),
    checklists: raw.checklists.map((c) => item(c.code, c.text, c.phase)),
    clauses: raw.clauses.map((c) => item(c.code, c.title ?? c.name ?? c.text ?? c.code, c.text)),
  }
}
