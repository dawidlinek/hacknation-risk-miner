// Real GET /api/projects/{rm_id}/graph (J8) -> EvidenceFlow.
import type { Origin, ReviewStatus } from '@/api/contracts/common'
import type { EvidenceFlow, FlowDetail, FlowNode, FlowRole } from '@/api/contracts/graph'
import { plural as pl, W } from '@/lib/plural'
import type { RealRef } from './real'

interface RealNode {
  id: string
  column: 0 | 1 | 2
  label: string
  sub: string
  role?: 'source' | 'calc' | 'ai' | 'case'
  review_status?: ReviewStatus
  review_item_id?: number | null
  value?: number
}

interface RealDetail {
  kind: string
  title: string
  rows: { k: string; v: string }[]
  evidence?: RealRef[]
  cta?: { label: string; href: string } | null
}

export interface RealGraph {
  nodes: RealNode[]
  links: { source: string; target: string; value: number }[]
  details: Record<string, RealDetail>
  summary: { facts: number; conclusions: number; by_role: Record<string, number> }
}

const ORIGIN: Record<string, Origin> = { source: 'SOURCE', calc: 'CALC', ai: 'AI', case: 'CASE' }

function flowRole(n: RealNode): FlowRole {
  if (n.column === 2) return 'conclusion'
  if (n.column === 1) return 'group'
  return n.id === 'src:xlsx' ? 'organiser' : ((n.role ?? 'source') as FlowRole)
}

const reviewIdFromHref = (href: string | undefined | null) => {
  const m = href ? /(?:item|sprawa)=(\d+)/.exec(href) : null
  return m ? Number(m[1]) : null
}

export function adaptGraph(raw: RealGraph): EvidenceFlow {
  const nodes: FlowNode[] = raw.nodes.map((n) => ({
    id: n.id,
    column: n.column,
    label: n.label,
    sub: n.sub,
    role: flowRole(n),
    status_label: n.column === 2 ? n.sub : undefined,
    review_status: n.review_status,
    origin: n.role ? ORIGIN[n.role] : undefined,
    selectable: n.column === 2,
  }))
  const details: Record<string, FlowDetail> = {}
  for (const [id, d] of Object.entries(raw.details)) {
    const node = raw.nodes.find((n) => n.id === id)
    details[id] = {
      kind: d.kind,
      title: d.title,
      rows: d.rows,
      review_item_id: node?.review_item_id ?? reviewIdFromHref(d.cta?.href),
      evidence: (d.evidence ?? []).map((e) => ({
        label: `${e.id}, ${e.label}`,
        url: e.url ?? null,
        field: e.field_code ?? null,
      })),
    }
  }
  const byRole = raw.summary.by_role
  return {
    nodes,
    links: raw.links.map((l) => ({ source: l.source, target: l.target, value: l.value })),
    details,
    overview: {
      kind: 'podsumowanie',
      title: `${raw.summary.facts} ${pl(raw.summary.facts, ['fakt', 'fakty', 'faktów'])}, ${raw.summary.conclusions} ${pl(raw.summary.conclusions, [...W.wniosek])}`,
      rows: [
        { k: 'ze źródeł', v: `${byRole.source ?? 0} ${pl(byRole.source ?? 0, ['fakt', 'fakty', 'faktów'])}` },
        {
          k: 'z odczytu modelu',
          v: `${byRole.ai ?? 0} ${pl(byRole.ai ?? 0, ['fakt', 'fakty', 'faktów'])}, do przeglądu`,
        },
        { k: 'z obliczeń', v: `${byRole.calc ?? 0} ${pl(byRole.calc ?? 0, ['fakt', 'fakty', 'faktów'])}` },
      ],
    },
    default_selected: null,
  }
}
