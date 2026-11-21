export type Metric = 'time' | 'cost' | 'comp'
export interface SimOption {
  key: string
  short: string
  label: string
  detail: string
  risk_code: string
  affects: Metric[]
  effect_label: Partial<Record<Metric, string>>
  default_on: boolean
  assumption: true
}
export interface SimMarker {
  x: number
  label: string
  tone: 'ink' | 'attention' | 'muted'
}
export interface SimDrivers {
  title: string
  desc: string
  rows: { label: string; value: number; display: string }[]
  provenance: string
}
export interface SimMetric {
  title: string
  x_label: string
  y_label: string
  x_domain: [number, number]
  x_ticks: [number, string][]
  shape: 'cdf' | 'survival'
  eval_x: number
  eval_x_by_subset?: Record<string, number>
  markers: SimMarker[]
  curves: Record<string, [number, number][]>
  extras?: Record<string, { cancel_pct?: number }>
  drivers: Record<string, SimDrivers>
}
export interface SimWhatIf {
  key: 'late2' | 'one' | 'price'
  question: string
  answer_by_subset: Record<string, string>
  provenance: string
  cta: string
  cta_active?: string
  action: { kind: 'marker'; metric: 'time'; x: number; label: string } | { kind: 'metric'; metric: Metric }
}
export interface SimulationOut {
  n: number
  runs: number
  options: SimOption[]
  metrics: Record<Metric, SimMetric>
  whatifs: SimWhatIf[]
  plan_x?: number
  programme_x?: number | null
}
