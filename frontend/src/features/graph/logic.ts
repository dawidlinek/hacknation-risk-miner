import type { EvidenceFlow, FlowLink, FlowNode } from '@/api/contracts/graph'

export type LinkStage = 1 | 2

/** Stage 1 = source -> fact group, stage 2 = fact group -> conclusion. */
export const linkStage = (l: FlowLink, nodes: Map<string, FlowNode>): LinkStage =>
  nodes.get(l.source)?.column === 0 ? 1 : 2

/**
 * Link opacity for the "skad wiemy" flow (frontend.md 2.4).
 * Nothing selected: stage 1 at 0.28, stage 2 at 0.22. A selected conclusion lights its own stage 2 links (0.55) and the stage 1
 * links that feed the fact groups it draws from (0.5); everything else drops to 0.08 / 0.06.
 */
export function flowOpacity(
  link: FlowLink,
  stage: LinkStage,
  selected: string | null,
  feeds: Set<string>,
): number {
  if (!selected) return stage === 1 ? 0.28 : 0.22
  if (stage === 2) return link.target === selected ? 0.55 : 0.06
  return feeds.has(link.target) ? 0.5 : 0.08
}

/** Fact groups that feed a conclusion. */
export function feedsOf(links: FlowLink[], selected: string | null): Set<string> {
  return new Set(selected ? links.filter((l) => l.target === selected).map((l) => l.source) : [])
}

export type BandColor = 'ink' | 'source' | 'ai' | 'calc' | 'attention'

/** Stage 1 bands take the source role colour; stage 2 bands the conclusion status (AI violet, others grey). */
export function bandColor(link: FlowLink, stage: LinkStage, nodes: Map<string, FlowNode>): BandColor {
  if (stage === 1) {
    const s = nodes.get(link.source)
    if (s?.role === 'organiser') return 'ink'
    if (s?.role === 'ai') return 'ai'
    if (s?.role === 'calc') return 'calc'
    return 'source'
  }
  const t = nodes.get(link.target)
  return t?.origin === 'AI' ? 'ai' : 'source'
}

export const CSS_COLOR: Record<BandColor, string> = {
  ink: 'var(--ink)',
  source: 'var(--prov-source)',
  ai: 'var(--prov-ai)',
  calc: 'var(--prov-calc)',
  attention: 'var(--attention)',
}

export const nodeMap = (flow: EvidenceFlow) => new Map(flow.nodes.map((n) => [n.id, n]))

/** Facts in the flow (for the empty state). */
export const hasFlow = (flow: EvidenceFlow) => flow.links.length > 0

/**
 * Pushes label centres apart so neighbours are at least `gap` px apart (labels are taller than small nodes).
 * Input order is preserved in the output; a forward pass pushes down, a backward pass pulls back inside `max`.
 */
export function spreadLabels(ys: number[], gap: number, min = 0, max = Number.POSITIVE_INFINITY): number[] {
  const order = ys.map((y, i) => [y, i] as const).sort((a, b) => a[0] - b[0])
  const out = order.map(([y]) => y)
  for (let i = 0; i < out.length; i++) {
    const lo = i === 0 ? min : out[i - 1] + gap
    if (out[i] < lo) out[i] = lo
  }
  for (let i = out.length - 1; i >= 0; i--) {
    const hi = i === out.length - 1 ? max : out[i + 1] - gap
    if (out[i] > hi) out[i] = hi
  }
  const res = new Array<number>(ys.length)
  order.forEach(([, idx], k) => {
    res[idx] = out[k]
  })
  return res
}
