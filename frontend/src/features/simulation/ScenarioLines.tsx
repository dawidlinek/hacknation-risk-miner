import { scaleLinear } from 'd3-scale'
import { line as d3line } from 'd3-shape'
import type { Metric, SimMarker, SimMetric } from '@/api/contracts/simulation'
import { endLabels, type Line } from './scenario'

const W = 680
const H = 300
const L = 48
const R = 520
const T = 20
const B = 250

const MARK_COLOR: Record<SimMarker['tone'], { line: string; text: string }> = {
  ink: { line: 'var(--ink)', text: 'var(--ink)' },
  attention: { line: 'var(--attention)', text: 'var(--attention-text)' },
  muted: { line: 'var(--chart-p50)', text: 'var(--text-body-muted)' },
}

/** Custom SVG (README pattern: labelled axes, 25% grid, markers, one path per series, end labels). */
export function ScenarioLines({
  metric,
  m,
  lines,
  extraMarkers = [],
  aria,
}: {
  metric: Metric
  m: SimMetric
  lines: Line[]
  extraMarkers?: SimMarker[]
  aria: string
}) {
  const [x0, x1] = m.x_domain
  const sx = scaleLinear().domain([x0, x1]).range([L, R]).clamp(true)
  const sy = scaleLinear().domain([0, 1]).range([B, T])
  const path = d3line<[number, number]>()
    .x((d) => sx(d[0]))
    .y((d) => sy(d[1]))
  const grid = [1, 0.75, 0.5, 0.25, 0]
  const markers = [...m.markers, ...extraMarkers]
  const ends = endLabels(lines, metric, sx, sy)
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={aria}
      className="h-auto w-full"
      data-testid="scenario-lines"
    >
      {grid.map((g) => (
        <g key={g}>
          <line x1={L} y1={sy(g)} x2={R} y2={sy(g)} stroke="var(--chart-grid)" />
          {g === 0 || g === 0.5 || g === 1 ? (
            <text
              x={L - 6}
              y={sy(g) + 4}
              textAnchor="end"
              className="font-mono"
              fontSize={11}
              fill="var(--chart-axis)"
            >
              {Math.round(g * 100)}%
            </text>
          ) : null}
        </g>
      ))}
      <line x1={L} y1={T} x2={L} y2={B} stroke="var(--chart-axis)" />
      <line x1={L} y1={B} x2={R} y2={B} stroke="var(--chart-axis)" />
      {m.x_ticks.map(([x, label]) => (
        <g key={x}>
          <line x1={sx(x)} y1={B} x2={sx(x)} y2={B + 6} stroke="var(--chart-axis)" />
          <text
            x={sx(x)}
            y={B + 20}
            textAnchor="middle"
            className="font-mono"
            fontSize={11}
            fill="var(--text-body-muted)"
          >
            {label}
          </text>
        </g>
      ))}
      <text
        x={(L + R) / 2}
        y={H - 8}
        textAnchor="middle"
        fontSize={12}
        fontWeight={500}
        fill="var(--text-secondary)"
      >
        {m.x_label}
      </text>
      <text
        x={12}
        y={(T + B) / 2}
        textAnchor="middle"
        transform={`rotate(-90 12 ${(T + B) / 2})`}
        fontSize={12}
        fontWeight={500}
        fill="var(--text-secondary)"
      >
        {m.y_label}
      </text>
      {markers.map((mk, i) => {
        const c = MARK_COLOR[mk.tone] ?? MARK_COLOR.muted
        const x = sx(mk.x)
        const right = x > R - 90
        return (
          <g key={`${mk.label}-${i}`}>
            <line x1={x} y1={T} x2={x} y2={B} stroke={c.line} strokeWidth={1.5} strokeDasharray="4 4" />
            <text
              x={right ? x - 6 : x + 6}
              y={34 + i * 18}
              textAnchor={right ? 'end' : 'start'}
              fontSize={11.5}
              fontWeight={600}
              fill={c.text}
            >
              {mk.label}
            </text>
          </g>
        )
      })}
      {lines.map((l) => (
        <path
          key={l.key || 'base'}
          d={path(l.points as [number, number][]) ?? ''}
          fill="none"
          stroke={l.color}
          strokeWidth={l.width}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ))}
      {ends.map((e) => (
        <g key={e.key || 'base'}>
          <line x1={e.x} y1={e.y0} x2={R + 10} y2={e.y} stroke={e.color} />
          <text x={R + 14} y={e.y + 4} fontSize={11.5} fontWeight={600} fill={e.color}>
            {e.text}
          </text>
        </g>
      ))}
    </svg>
  )
}
