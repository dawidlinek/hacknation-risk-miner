// Pure logic for 1.4 Symulacja (frontend.md §2 1.4). Every number comes from GET /api/analyses/{id}/simulation;
// this file only picks curves for the checked options, reads values off them and formats the KPI row.
import type { Metric, SimMetric, SimOption, SimulationOut } from '@/api/contracts/simulation'
import { fmtDec, fmtMonths, fmtNum, fmtPct, fmtPp } from '@/lib/format'

export type Pt = [number, number]

/** Server extras on top of the frontend contract. */
export type SimulationResponse = SimulationOut & {
  insufficient?: boolean
  message?: string
  seed?: number
  honesty_note?: string
  limitations?: string[]
  cause_source?: string
  programme?: { code: string | null; name: string | null; deadline: string | null; sign_p50: string } | null
}

export const METRIC_FROM_PARAM: Record<string, Metric> = { czas: 'time', koszt: 'cost', konkurencja: 'comp' }
export const PARAM_FROM_METRIC: Record<Metric, string> = { time: 'czas', cost: 'koszt', comp: 'konkurencja' }
export const METRIC_TAB: Record<Metric, string> = { time: 'Termin', cost: 'Koszt', comp: 'Konkurencja' }
export const SCENARIO_COLORS = [
  'var(--scenario-s1)',
  'var(--scenario-s2)',
  'var(--scenario-s3)',
  'var(--scenario-s4)',
] as const

/** Subset key = checked option keys in `options` order joined by "+" ("" = baseline). */
export function subsetKey(options: SimOption[], checked: Iterable<string>): string {
  const on = new Set(checked)
  return options
    .filter((o) => on.has(o.key))
    .map((o) => o.key)
    .join('+')
}

export function parseChecked(param: string | undefined, options: SimOption[]): string[] {
  if (!param) return []
  const known = new Set(options.map((o) => o.key))
  return [...new Set(param.split(',').map((s) => s.trim()))].filter((k) => known.has(k))
}

export const affects = (o: SimOption, m: Metric) => o.affects.includes(m)

export function interp(pts: Pt[], x: number): number {
  if (!pts.length) return Number.NaN
  if (x <= pts[0][0]) return pts[0][1]
  for (let i = 1; i < pts.length; i++) {
    if (pts[i][0] >= x) {
      const [x0, y0] = pts[i - 1]
      const [x1, y1] = pts[i]
      return x1 === x0 ? y1 : y0 + ((x - x0) / (x1 - x0)) * (y1 - y0)
    }
  }
  return pts[pts.length - 1][1]
}

/** x where an increasing curve reaches y. */
export function inverse(pts: Pt[], y: number): number {
  if (!pts.length) return Number.NaN
  for (let i = 1; i < pts.length; i++) {
    if (pts[i][1] >= y) {
      const [x0, y0] = pts[i - 1]
      const [x1, y1] = pts[i]
      return y1 === y0 ? x1 : x0 + ((y - y0) / (y1 - y0)) * (x1 - x0)
    }
  }
  return pts[pts.length - 1][0]
}

/** x where a decreasing curve (survival) falls to y. */
export function inverseDesc(pts: Pt[], y: number): number {
  if (!pts.length) return Number.NaN
  if (pts[0][1] <= y) return pts[0][0]
  for (let i = 1; i < pts.length; i++) {
    if (pts[i][1] <= y) {
      const [x0, y0] = pts[i - 1]
      const [x1, y1] = pts[i]
      return y0 === y1 ? x1 : x0 + ((y0 - y) / (y0 - y1)) * (x1 - x0)
    }
  }
  return pts[pts.length - 1][0]
}

export interface Line {
  key: string
  label: string
  color: string
  width: number
  points: Pt[]
  /** x where the KPI and the end label are read for this line */
  evalX: number
}

export function evalXFor(m: SimMetric, key: string): number {
  return m.eval_x_by_subset?.[key] ?? m.eval_x
}

/**
 * "Teraz" + one line per checked option that affects the metric (its own curve) + "Razem" when two or more
 * checked options affect it. Lines whose curve is missing are dropped and reported in `missing`.
 */
export function buildLines(
  sim: SimulationOut,
  metric: Metric,
  checked: string[],
): { lines: Line[]; missing: string[] } {
  const m = sim.metrics[metric]
  const lines: Line[] = []
  const missing: string[] = []
  const add = (key: string, label: string, color: string, width: number) => {
    const pts = m.curves[key] as Pt[] | undefined
    if (!pts) {
      missing.push(key)
      return
    }
    lines.push({ key, label, color, width, points: pts, evalX: evalXFor(m, key) })
  }
  add('', 'Teraz', 'var(--scenario-baseline)', 2.5)
  const on = new Set(checked)
  const active = sim.options.filter((o) => on.has(o.key) && affects(o, metric))
  sim.options.forEach((o, i) => {
    if (on.has(o.key) && affects(o, metric)) add(o.key, o.short, SCENARIO_COLORS[i % 4], 2)
  })
  if (active.length >= 2) add(subsetKey(sim.options, checked), 'Razem', 'var(--scenario-combined)', 3.5)
  return { lines, missing }
}

/** Curve of every checked option together (the KPI "after" value), baseline when nothing affects the metric. */
export function combinedKey(sim: SimulationOut, metric: Metric, checked: string[]): string {
  const any = sim.options.some((o) => checked.includes(o.key) && affects(o, metric))
  return any ? subsetKey(sim.options, checked) : ''
}

export interface Kpi {
  label: string
  value: string
  delta: string
  tone: 'good' | 'bad' | 'muted' | 'none'
  attention?: boolean
}

function pctKpi(
  label: string,
  v0: number,
  v1: number,
  changed: boolean,
  upIsGood: boolean,
  attention = false,
): Kpi {
  const d = changed ? fmtPp((v1 - v0) * 100) : ''
  const tone: Kpi['tone'] = d === '' ? 'none' : v1 > v0 === upIsGood ? 'good' : 'bad'
  return { label, value: fmtPct(v1, { fromShare: true }), delta: d, tone, attention }
}

function valKpi(label: string, v0: number, v1: number, changed: boolean, fmt: (x: number) => string): Kpi {
  const same = fmt(v0) === fmt(v1)
  return {
    label,
    value: fmt(v1),
    delta: changed && !same ? `było ${fmt(v0)}` : '',
    tone: changed && !same ? 'muted' : 'none',
  }
}

export interface KpiContext {
  late2: boolean
}

/** KPI row exactly as the mockup: deltas against "Teraz" when any checked option affects the metric. */
export function kpis(
  sim: SimulationOut,
  metric: Metric,
  checked: string[],
  ctx: KpiContext = { late2: false },
): Kpi[] {
  const m = sim.metrics[metric]
  const base = (m.curves[''] ?? []) as Pt[]
  const key = combinedKey(sim, metric, checked)
  const all = (m.curves[key] ?? base) as Pt[]
  const changed = key !== ''
  if (metric === 'time') {
    const out = [
      pctKpi('W terminie z planu', interp(base, m.eval_x), interp(all, evalXFor(m, key)), changed, true),
      valKpi('Połowa umów', inverse(base, 0.5), inverse(all, 0.5), changed, (x) => fmtMonths(x)),
      valKpi('8 na 10 umów', inverse(base, 0.8), inverse(all, 0.8), changed, (x) => fmtMonths(x)),
    ]
    const px = sim.programme_x
    if (px !== null && px !== undefined) {
      const at = ctx.late2 ? px - 2 : px
      const k = pctKpi(
        ctx.late2 ? 'Po terminie programu, przetarg +2 mies.' : 'Po terminie programu',
        1 - interp(base, px),
        1 - interp(all, at),
        changed || ctx.late2,
        false,
        true,
      )
      out.push(k)
    }
    return out
  }
  if (metric === 'cost') {
    const budget = m.markers[0]?.x ?? m.eval_x / 1.1
    const mln = (x: number) => `${fmtDec(x, 2)} mln zł`
    return [
      pctKpi('W budżecie + 10%', interp(base, m.eval_x), interp(all, m.eval_x), changed, true),
      pctKpi('Bez żadnych dopłat', interp(base, budget), interp(all, budget), changed, true),
      valKpi('8 na 10 umów do', inverse(base, 0.8), inverse(all, 0.8), changed, mln),
      valKpi('9 na 10 umów do', inverse(base, 0.9), inverse(all, 0.9), changed, mln),
    ]
  }
  const one = (pts: Pt[]) => (pts.length > 1 ? pts[0][1] - pts[1][1] : Number.NaN)
  const c0 = m.extras?.['']?.cancel_pct
  const c1 = m.extras?.[key]?.cancel_pct ?? c0
  const out = [
    pctKpi('Co najmniej 2 oferty', interp(base, 2), interp(all, 2), changed, true),
    valKpi('Mediana ofert', inverseDesc(base, 0.5), inverseDesc(all, 0.5), changed, (x) => fmtNum(x, 1)),
    pctKpi('Tylko jedna oferta', one(base), one(all), changed, false),
  ]
  if (c0 !== undefined && c1 !== undefined) {
    const d = changed ? fmtPp(c1 - c0) : ''
    out.push({
      label: 'Unieważnienie',
      value: fmtPct(c1, { digits: 0 }),
      delta: d,
      tone: d === '' ? 'none' : c1 < c0 ? 'good' : 'bad',
      attention: true,
    })
  }
  return out
}

/** Value read at the line's eval x (end label, summary). */
export function lineValue(line: Line, metric: Metric): number {
  return metric === 'comp' ? interp(line.points, 2) : interp(line.points, line.evalX)
}

export interface EndLabel {
  key: string
  text: string
  color: string
  x: number
  y: number
  y0: number
}

/** End labels "<label> <pct>" sorted by y and pushed down to keep `gap` px apart (svg coordinates). */
export function endLabels(
  lines: Line[],
  metric: Metric,
  sx: (x: number) => number,
  sy: (y: number) => number,
  gap = 16,
): EndLabel[] {
  const labels = lines
    .map((l) => {
      const v = lineValue(l, metric)
      const x = metric === 'comp' ? 2 : l.evalX
      return {
        key: l.key,
        text: `${l.label} ${fmtPct(v, { fromShare: true })}`,
        color: l.color,
        x: sx(x),
        y: sy(v),
        y0: sy(v),
      }
    })
    .sort((a, b) => a.y - b.y)
  for (let i = 1; i < labels.length; i++)
    if (labels[i].y - labels[i - 1].y < gap) labels[i].y = labels[i - 1].y + gap
  return labels
}

/** Summary sentence (client template over API numbers, never LLM). */
export function summarySentence(sim: SimulationOut, metric: Metric, checked: string[]): string {
  const { lines } = buildLines(sim, metric, checked)
  const base = lines[0]
  if (!base) return 'Brak krzywej dla tej miary.'
  const v0 = lineValue(base, metric)
  const key = combinedKey(sim, metric, checked)
  const anyM = key !== ''
  const allLine = lines.find((l) => l.key === key) ?? lines[lines.length - 1]
  const v1 = lineValue(allLine, metric)
  const pct = (v: number) => fmtPct(v, { fromShare: true })
  let s =
    metric === 'time'
      ? `Teraz skończysz w terminie z planu w ${pct(v0)} przypadków.`
      : metric === 'cost'
        ? `Teraz ${pct(v0)} takich umów mieści się w budżecie z 10% rezerwy.`
        : `Teraz w ${pct(v0)} przetargów przychodzą co najmniej 2 oferty.`
  s += anyM ? ` Z zaznaczonymi zmianami: ${pct(v1)}.` : ' Zaznacz zmianę poniżej, żeby zobaczyć jej linię.'
  const planOpt = sim.options.find(
    (o) => checked.includes(o.key) && sim.metrics.time.eval_x_by_subset?.[o.key],
  )
  if (metric === 'time' && planOpt && sim.programme_x) {
    s +=
      ' Uwaga: dłuższy termin zbliża koniec robót do końca programu, więc rośnie ryzyko utraty dofinansowania.'
  }
  return s
}

export function effectLine(o: SimOption, metric: Metric): string {
  const e = o.effect_label[metric]
  const none = {
    time: 'bez wpływu na termin',
    cost: 'bez wpływu na koszt',
    comp: 'bez wpływu na konkurencję',
  }[metric]
  return `${o.risk_code}, ${affects(o, metric) && e ? e : none}`
}

export function chartAria(sim: SimulationOut, metric: Metric, checked: string[]): string {
  const { lines } = buildLines(sim, metric, checked)
  const title = sim.metrics[metric].title
  if (!lines.length) return title
  const v0 = lineValue(lines[0], metric)
  const key = combinedKey(sim, metric, checked)
  const after = lines.find((l) => l.key === key)
  const pct = (v: number) => fmtPct(v, { fromShare: true })
  return `${title}: teraz ${pct(v0)}${key && after ? `, ze zmianami ${pct(lineValue(after, metric))}` : ''}`
}
