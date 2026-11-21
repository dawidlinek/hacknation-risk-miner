import { type SankeyLink, type SankeyNode, sankey, sankeyLinkHorizontal } from 'd3-sankey'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { EvidenceFlow as FlowData, FlowNode } from '@/api/contracts/graph'
import { cn } from '@/lib/cn'
import { bandColor, CSS_COLOR, feedsOf, flowOpacity, linkStage, nodeMap, spreadLabels } from './logic'

type N = FlowNode & SankeyNode<FlowNode, object>
type L = SankeyLink<FlowNode, object> & { stage: 1 | 2 }

const BASE_H = 640
/** The unspecified-cause code reads as a phrase, not as "N-UNSPEC ryzyko". */
const nodeLabel = (l: string) => l.replace(/^N-UNSPEC\b.*$/, 'Przyczyna nieustalona')
const LABEL_GAP_CONCL = 54 // a 2-line conclusion label plus its sub line
const NODE_W = 12
const MIN_W = 520
const DEFAULT_W = 1000

/** Column geometry in pixels for a container of width `w`: label gutters left (sources) and right (conclusions). */
function geometry(w: number) {
  const left = Math.min(210, Math.max(120, w * 0.18))
  const right = Math.min(240, Math.max(150, w * 0.24))
  const x0 = left
  const x2 = w - right - NODE_W
  return { x: [x0, (x0 + x2) / 2, x2] as const, left, right }
}

const NODE_FILL = (n: FlowNode) => {
  if (n.column === 1) return 'var(--ink)'
  if (n.role === 'organiser') return 'var(--ink)'
  if (n.role === 'ai' || n.origin === 'AI') return 'var(--prov-ai)'
  if (n.role === 'calc') return 'var(--prov-calc)'
  return 'var(--prov-source)'
}

/**
 * Three-column Sankey: Zrodla -> Fakty w bazie -> Wnioski. d3-sankey computes the layout only (columns are fixed by
 * `column`), React renders. Conclusion labels are buttons (aria-pressed) laid over the SVG.
 */
export function EvidenceFlow({
  flow,
  selected,
  onSelect,
}: {
  flow: FlowData
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(DEFAULT_W)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => setWidth(Math.max(MIN_W, Math.round(el.clientWidth)))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const W = width
  // tall enough that every conclusion label fits between the header and the bottom (13+ conclusions overflowed 640)
  const H = useMemo(
    () => Math.max(BASE_H, 40 + 24 + LABEL_GAP_CONCL * flow.nodes.filter((n) => n.column === 2).length),
    [flow.nodes],
  )
  const geo = useMemo(() => geometry(W), [W])
  const COLX = geo.x

  const layout = useMemo(() => {
    const gen = sankey<FlowNode, object>()
      .nodeId((d) => d.id)
      .nodeAlign((n) => (n as FlowNode).column)
      .nodeSort(null)
      .linkSort(null)
      .nodeWidth(NODE_W)
      .nodePadding(36)
      .extent([
        [COLX[0], 24],
        [COLX[2] + NODE_W, H - 24],
      ])
    const g = gen({
      nodes: flow.nodes.map((n) => ({ ...n })),
      links: flow.links.map((l) => ({ ...l })),
    })
    return g as unknown as { nodes: N[]; links: L[] }
  }, [flow, COLX, H])

  const nodes = useMemo(() => nodeMap(flow), [flow])
  const feeds = useMemo(() => feedsOf(flow.links, selected), [flow.links, selected])
  const path = sankeyLinkHorizontal()
  // label centres per column, spread so that 2-3 line labels of small nodes do not overlap
  const labelY = useMemo(() => {
    const out = new Map<string, number>()
    for (const col of [0, 1, 2] as const) {
      const ns = layout.nodes.filter((n) => n.column === col)
      const ys = spreadLabels(
        ns.map((n) => ((n.y0 ?? 0) + (n.y1 ?? 0)) / 2),
        col === 2 ? LABEL_GAP_CONCL : 40,
        40,
        H - 24,
      )
      for (const [i, n] of ns.entries()) out.set(n.id, ys[i])
    }
    return out
  }, [layout, H])

  return (
    <div ref={ref} className="relative w-full" style={{ height: H }}>
      <div className="t-eyebrow absolute top-0 left-0 w-full text-muted" aria-hidden>
        <span className="absolute" style={{ right: W - COLX[0] + 8, textAlign: 'right' }}>
          Źródła
        </span>
        <span className="absolute" style={{ left: COLX[1] + 20 }}>
          Fakty w bazie
        </span>
        <span className="absolute" style={{ left: COLX[2] + 20 }}>
          Wnioski
        </span>
      </div>
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Przepływ od źródeł przez fakty w bazie do wniosków"
        className="absolute inset-0"
      >
        <g fill="none">
          {layout.links.map((l, i) => {
            const stage = linkStage(l as never, nodes)
            const src = l.source as N
            const tgt = l.target as N
            const key = `${src.id}-${tgt.id}`
            return (
              <path
                key={key}
                d={path(l as never) ?? ''}
                stroke={
                  CSS_COLOR[bandColor({ source: src.id, target: tgt.id, value: l.value }, stage, nodes)]
                }
                strokeWidth={Math.max(1, l.width ?? 1)}
                strokeOpacity={flowOpacity(
                  { source: src.id, target: tgt.id, value: l.value },
                  stage,
                  selected,
                  feeds,
                )}
                data-stage={stage}
                data-i={i}
              />
            )
          })}
        </g>
        {layout.nodes.map((n) => (
          <rect
            key={n.id}
            x={n.x0}
            y={n.y0}
            width={(n.x1 ?? 0) - (n.x0 ?? 0)}
            height={Math.max(2, (n.y1 ?? 0) - (n.y0 ?? 0))}
            rx={3}
            fill={NODE_FILL(n)}
          />
        ))}
      </svg>
      {layout.nodes.map((n) => {
        const y = labelY.get(n.id) ?? 0
        const on = selected === n.id
        const base =
          'absolute flex -translate-y-1/2 flex-col gap-0 rounded-md border px-2.5 py-0.5 text-left bg-surface/90'
        const pos =
          n.column === 0
            ? {
                right: W - (n.x0 ?? 0) + 6,
                alignItems: 'flex-end' as const,
                textAlign: 'right' as const,
                maxWidth: geo.left - 14,
              }
            : {
                left: (n.x1 ?? 0) + 8,
                alignItems: 'flex-start' as const,
                maxWidth: n.column === 2 ? geo.right - 20 : Math.min(200, (COLX[2] - COLX[0]) / 2 - 24),
              }
        const body = (
          <>
            <span
              className="text-[13px] leading-tight font-medium text-text"
              title={nodeLabel(n.label)}
              style={{
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }}
            >
              {nodeLabel(n.label)}
            </span>
            <span
              className={cn(
                't-caption leading-tight',
                n.column === 2 && n.origin === 'AI'
                  ? 'text-prov-ai'
                  : n.column === 2 && n.review_status === 'proposed'
                    ? 'text-attention-text'
                    : 'text-muted',
              )}
            >
              {n.sub}
            </span>
          </>
        )
        if (n.selectable) {
          return (
            <button
              key={n.id}
              type="button"
              aria-pressed={on}
              onClick={() => onSelect(on ? null : n.id)}
              className={cn(
                base,
                'cursor-pointer',
                on ? 'border-2 border-ink' : 'border-transparent hover:border-border',
              )}
              style={{ top: y, ...pos }}
            >
              {body}
            </button>
          )
        }
        return (
          <div key={n.id} className={cn(base, 'border-transparent')} style={{ top: y, ...pos }}>
            {body}
          </div>
        )
      })}
    </div>
  )
}
