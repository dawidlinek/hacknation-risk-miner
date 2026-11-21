import type { AskAnswer, Sentence } from './common'

export interface DashboardTile {
  key: 'review' | 'monitoring' | 'analyses'
  label: string
  value: number
  sub: string
  href: string
  attention: boolean
}
export interface DashboardOut {
  headline: Sentence
  tiles: DashboardTile[]
  sources: {
    name: string
    what: string
    count_label: string
    when_label: string
    state: 'ok' | 'not_started' | 'error'
  }[]
  issues: { review_item_id: number; title: string; detail: string; ref: string }[]
  ask: { suggestions: AskSuggestion[]; initial: AskAnswer | null }
}
export interface AskSuggestion {
  id: string
  label: string
  question: string
}
