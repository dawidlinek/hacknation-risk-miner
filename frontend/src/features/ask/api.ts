import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, contractFetch } from '@/api/client'
import type { AgentStep, AskAnswer } from '@/api/contracts/common'
import { isRateLimited, RATE_LIMIT_MSG } from '@/auth/session'

interface RealRef {
  kind: string
  id: string
  label: string
}

export interface RealAnswer {
  id: string
  code: string | null
  role: 'calc' | 'ai' | 'no_data'
  role_label: string
  text: string
  bars: { label: string; value: number; display: string; highlight: boolean }[]
  method: {
    kind: 'sql' | 'template' | 'llm'
    sql: string | null
    template: string | null
  }
  sources: RealRef[]
  n: number | null
  missing: string[]
  actions: { kind: string; label: string; href: string | null }[]
}

const ROLE: Record<RealAnswer['role'], AskAnswer['role']> = {
  calc: 'obliczenie',
  ai: 'wniosek_ai',
  no_data: 'brak_danych',
}
const KIND: Record<string, AskAnswer['actions'][number]['kind']> = {
  save: 'save',
  rows_csv: 'export_csv',
  open_list: 'open_list',
  open_map: 'open_map',
  open_project: 'open_project',
  open_review: 'open_review',
  compare: 'compare',
}

export function adaptAnswer(raw: RealAnswer, question: string): AskAnswer {
  const bars = raw.bars ?? []
  // one chip per distinct source: chats often cite the same class or catalogue entry for several facts
  const sources = [
    ...new Set([
      ...(raw.sources ?? []).map((s) => s.label),
      ...(raw.n !== null && raw.n !== undefined && !(raw.sources ?? []).some((s) => /n = /.test(s.label))
        ? [`n = ${raw.n}`]
        : []),
    ]),
  ]
  return {
    id: raw.id,
    question,
    role: ROLE[raw.role],
    role_label: raw.role_label,
    text: raw.text,
    bars: bars.map((b) => ({
      label: b.label,
      value: b.value,
      display: b.display,
      attention: b.highlight,
    })),
    sql: raw.method?.sql ?? null,
    method: raw.method ? (raw.method.template ?? raw.method.kind) : null,
    sources,
    actions: (raw.actions ?? [])
      .filter((a) => KIND[a.kind])
      .map((a) => ({
        kind: KIND[a.kind],
        label: a.label,
        href: a.href ?? undefined,
      })),
    saved_id: raw.code,
  }
}

export const askErrorMessage = (e: unknown) =>
  isRateLimited(e)
    ? RATE_LIMIT_MSG
    : e instanceof ApiError && e.detail
      ? e.detail
      : 'Nie udało się odpowiedzieć. Spróbuj inaczej sformułować pytanie.'

export const suggestionsQuery = (context: 'pulpit' | 'zapytaj' | 'analysis' | 'project') =>
  queryOptions({
    queryKey: ['ask', 'suggestions', context],
    queryFn: () =>
      contractFetch<{ key: string; label: string }[]>('/api/ask/suggestions', {
        query: { context },
      }),
    staleTime: Number.POSITIVE_INFINITY,
  })

/** Zapytaj as an agent: the model plans, calls tools (app guide, data, documents, projects, monitoring) and answers;
 * the visible steps come back with the answer. The current screen is sent so "co mogę tu zrobić?" works anywhere. */
export const askQuestion = async (question: string): Promise<AskAnswer> => {
  const route = typeof window === 'undefined' ? '/zapytaj' : window.location.pathname
  const res = await contractFetch<{ answer: RealAnswer; steps: AgentStep[] }>('/api/ask/agent', {
    method: 'POST',
    json: { question, route },
  })
  // the agent's own label ("odpowiedź asystenta na podstawie narzędzi"), not the approved-events label of AI answers
  return {
    ...adaptAnswer(res.answer, question),
    role_label: res.answer.role_label,
    steps: res.steps ?? [],
  }
}

export const askProject = async (rmId: string, message: string): Promise<AskAnswer> =>
  adaptAnswer(
    await contractFetch<RealAnswer>(`/api/projects/${encodeURIComponent(rmId)}/chat`, {
      method: 'POST',
      json: { message },
    }),
    message,
  )

export const askAnalysis = async (
  code: string,
  message: string,
  context?: 'report' | 'simulation' | 'redpen',
): Promise<AskAnswer> =>
  adaptAnswer(
    await contractFetch<RealAnswer>(`/api/analyses/${encodeURIComponent(code)}/chat`, {
      method: 'POST',
      json: { message, context },
    }),
    message,
  )

export interface SavedQuestion {
  code: string
  title: string
  saved_at: string
  role: string | null
  n: number | null
}

export const savedQuestionsQuery = queryOptions({
  queryKey: ['questions'],
  queryFn: () =>
    contractFetch<{ total: number; items: SavedQuestion[] }>('/api/questions', {
      query: { mine: false, limit: 50 },
    }),
})

export const savedQuestionQuery = (code: string) =>
  queryOptions({
    queryKey: ['questions', code],
    queryFn: async () =>
      adaptAnswer(await contractFetch<RealAnswer>(`/api/questions/${encodeURIComponent(code)}`), ''),
  })

export function useSaveQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (answerId: string) =>
      contractFetch<{ code: string; title: string }>('/api/questions', {
        method: 'POST',
        json: { question_id: answerId },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['questions'] }),
  })
}

export const rowsCsvUrl = (code: string) => `/api/questions/${encodeURIComponent(code)}/rows.csv`

/** "Zadaj ponownie": re-runs the stored SQL; the saved snapshot stays (`before`), `after` is today's answer. */
export async function rerunQuestion(code: string): Promise<{ answer: AskAnswer; changed: boolean }> {
  const r = await contractFetch<{
    before: RealAnswer
    after: RealAnswer
    changed?: boolean
  }>(`/api/questions/${encodeURIComponent(code)}/rerun`, {
    method: 'POST',
    json: {},
  })
  return { answer: adaptAnswer(r.after, ''), changed: r.changed !== false }
}
