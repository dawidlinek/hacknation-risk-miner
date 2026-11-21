import type { AskAnswer } from './common'

export type { AskSuggestion } from './dashboard'

export interface AskIn {
  question: string
  context?: { analysis_id?: string; project_id?: string; thread_id?: string }
}
export interface SavedQuestion {
  id: string
  title: string
  created_at: string
}
export interface SavedQuestionDetail extends SavedQuestion {
  answer: AskAnswer
}
export type { AskAnswer }
