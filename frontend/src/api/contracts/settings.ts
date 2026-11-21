// Contract for D4 Ustawienia (adapter-free: the real /api/settings/llm shape is used directly, trimmed to what the screen reads).
export interface LlmTask {
  task: string
  label: string
  data_label: string
  sensitivity: 'public' | 'confidential'
  alias: string
  provider: string
  model: string
  data_location: string
  sovereign: boolean
  enforced: boolean
}

export interface LlmProvider {
  id: string
  kind: string
  data_location: string
  configured: boolean
  sovereign: boolean
  health: { status: string; latency_ms: number | null }
}

export interface LlmSettings {
  tasks: LlmTask[]
  providers: LlmProvider[]
  usage_24h: {
    calls: { value: number | null; display: string }
    tokens_in: number
    tokens_out: number
    cost_usd: number
  }
  budget?: { usd_per_day: number; spent_today_usd: number; warn: boolean }
}
