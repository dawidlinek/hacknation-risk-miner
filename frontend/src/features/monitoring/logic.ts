import type { MetricKey, MonitoringMode, RegionStat, Signal } from '@/api/contracts/monitoring'
import { fmtDays, fmtDec, fmtInt } from '@/lib/format'

const pct1 = (v: number) => `${fmtDec(v, 1)}%`

export interface MetricDef {
  key: MetricKey
  label: string
  description: string
  get: (r: RegionStat) => number | null
  fmt: (v: number) => string
}

export const METRICS: Record<MetricKey, MetricDef> = {
  late: {
    key: 'late',
    label: 'Po terminie',
    description: 'odsetek umów zakończonych po terminie z umowy',
    get: (r) => r.late_pct,
    fmt: pct1,
  },
  delay: {
    key: 'delay',
    label: 'Opóźnienie',
    description: 'mediana dni opóźnienia wśród umów, które się spóźniły',
    get: (r) => r.median_delay_days,
    fmt: (v) => fmtDays(v, { short: true }),
  },
  over: {
    key: 'over',
    label: 'Dopłaty',
    description: 'zapłacono ponad wartość umów, w % ich łącznej wartości',
    get: (r) => r.over_pct,
    fmt: pct1,
  },
  chg: {
    key: 'chg',
    label: 'Zmiany umów',
    description: 'odsetek umów z co najmniej jednym ogłoszeniem o zmianie',
    get: (r) => r.changed_pct,
    fmt: pct1,
  },
  imp: {
    key: 'imp',
    label: 'Nienależyte wykonanie',
    description: 'odsetek umów oznaczonych w ogłoszeniu jako wykonane nienależycie',
    get: (r) => r.improper_pct,
    fmt: pct1,
  },
  sig: {
    key: 'sig',
    label: 'Sygnały',
    description: 'umowy ponad 90 dni po terminie z umowy, bez ogłoszenia o wykonaniu',
    get: (r) => r.signals,
    fmt: (v) => fmtInt(v),
  },
}

/** Metrics offered in the toolbar segmented control and the "..." menu. */
export const SEGMENT_METRICS: MetricKey[] = ['late', 'delay', 'over']
export const MENU_METRICS: MetricKey[] = ['late', 'delay', 'over', 'chg', 'imp']

export const parseMetric = (s: string | undefined | null): MetricKey =>
  s && s in METRICS ? (s as MetricKey) : 'late'

/** In "W toku" mode the map always shows signals. */
export const effectiveMetric = (mode: MonitoringMode, metric: MetricKey): MetricKey =>
  mode === 'open' ? 'sig' : metric

export type Rgb = [number, number, number]
/** Completed-contract metrics: light to deep brand blue (the user asked for a colourful map, not grey). */
export const BLUE_STOPS: Rgb[] = [
  [232, 238, 255],
  [159, 178, 250],
  [48, 86, 245],
  [28, 52, 150],
]
/** Signals ("W toku"): yellow (the attention colour) to red. */
export const HEAT_STOPS: Rgb[] = [
  [255, 246, 209],
  [255, 210, 63],
  [245, 158, 11],
  [220, 38, 38],
  [153, 27, 27],
]

const mix = (a: Rgb, b: Rgb, t: number): Rgb =>
  [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * t)) as Rgb
export const rgb = (c: Rgb) => `rgb(${c.join(',')})`

/** t in [0,1] to a colour: ink ramp for completed-contract metrics, heat ramp for signals. */
export function colorAt(t: number, mode: MonitoringMode): string {
  const x = Math.min(1, Math.max(0, t))
  const stops = mode === 'open' ? HEAT_STOPS : BLUE_STOPS
  const seg = x * (stops.length - 1)
  const i = Math.min(stops.length - 2, Math.floor(seg))
  return rgb(mix(stops[i], stops[i + 1], seg - i))
}

export interface ScaledRegion {
  stat: RegionStat
  value: number | null
  t: number
  fill: string
  /** white text on dark fills (t > 0.55 on the ink ramp) */
  lightText: boolean
  rank: number
}

export const INSUFFICIENT_FILL = '#F6F6F6'

/** Values, colour and rank per region for one metric. Regions with too little data stay neutral and unranked. */
export function scaleRegions(
  items: RegionStat[],
  metric: MetricKey,
  mode: MonitoringMode,
): { regions: ScaledRegion[]; lo: number; hi: number } {
  const def = METRICS[metric]
  const raw = items.map((s) => ({ s, v: s.insufficient && metric !== 'sig' ? null : def.get(s) }))
  const vals = raw.map((r) => r.v).filter((v): v is number => v !== null)
  const lo = vals.length ? Math.min(...vals) : 0
  const hi = vals.length ? Math.max(...vals) : 0
  const ranked = [...raw].filter((r) => r.v !== null).sort((a, b) => (b.v as number) - (a.v as number))
  const rankOf = new Map(ranked.map((r, i) => [r.s.teryt, i + 1]))
  const regions = raw.map(({ s, v }) => {
    const t = v === null ? 0 : (v - lo) / (hi - lo || 1)
    return {
      stat: s,
      value: v,
      t,
      fill: v === null ? INSUFFICIENT_FILL : colorAt(t, mode),
      lightText: mode === 'done' && v !== null && t > 0.55,
      rank: rankOf.get(s.teryt) ?? 0,
    }
  })
  return { regions, lo, hi }
}

/** Which level of the drill-down a URL is at: 0 Polska, 1 voivodeship, 2 powiat, 3 single contract. */
export function levelOf(p: { woj?: string; pow?: string; umowa?: string }): 0 | 1 | 2 | 3 {
  if (p.umowa) return 3
  if (p.pow) return 2
  if (p.woj) return 1
  return 0
}

/** Signals inside the current view: L0 all, L1 the voivodeship, L2/L3 the powiat. */
export function signalsInView(signals: Signal[], p: { woj?: string; pow?: string }): Signal[] {
  if (p.pow) return signals.filter((s) => s.teryt.pow === p.pow)
  if (p.woj) return signals.filter((s) => s.teryt.woj === p.woj)
  return signals
}

/** Signals per gmina, for stacking "+N d" pills: the n-th pill of a gmina sits 14 px higher. */
export function pillStacks(signals: Signal[]): Map<string, number> {
  const seen = new Map<string, number>()
  const out = new Map<string, number>()
  for (const s of signals) {
    const g = s.teryt.gmi ?? s.teryt.pow
    const n = (seen.get(g) ?? 0) + 1
    seen.set(g, n)
    out.set(s.id, n - 1)
  }
  return out
}

/** Powiat tint by signal count: 1, 2, 3+ (4.1a). */
export const POWIAT_TINT = ['#FFF6D1', '#FFE27A', '#FFD23F'] as const
export const tintFor = (n: number): string | null => (n <= 0 ? null : POWIAT_TINT[Math.min(2, n - 1)])
