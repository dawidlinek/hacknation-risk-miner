// Contract for 2.1 Import i zrodla as the UI consumes it (adapter: api/adapters/imports.ts, real /api/imports*).
import type { Page } from './common'

export type ImportStatus =
  | 'uploaded'
  | 'inspected'
  | 'awaiting_answer'
  | 'mapped'
  | 'tested'
  | 'approved'
  | 'running'
  | 'done'
  | 'failed'

export interface ImportFile {
  name: string
  detail: string // '1,8 MB, XLSX' (+ ', ten plik był już wczytany')
  duplicate: boolean
}

export interface ImportToolCall {
  call: string // mono: 'list_archive("paczka_powiat.zip")'
  out: string // '2 341 plików, 14 typów'
}

export type MappingState = 'ok' | 'question' | 'check' | 'proposal' | 'dropped'

export interface ImportMappingRow {
  column: string
  field: string
  rule: string
  state: MappingState
  state_label: string // 'zgodne' | '309 z 312' | 'pytanie' | 'brutto'
}

export interface ImportQuestion {
  key: string
  title: string
  options: { value: string; label: string }[]
}

export interface ImportTestRun {
  ok: number
  failed: number
  rows: number
  review_items_created: number
  failures: { row: number; column: string; rule: string }[]
}

export interface ImportSession {
  code: string
  status: ImportStatus
  status_label: string
  files: ImportFile[]
  tool_calls: ImportToolCall[]
  mapping: ImportMappingRow[]
  questions: ImportQuestion[]
  answers: Record<string, string>
  rules: string[]
  importer: { name: string; version: string } | null
  test_run: ImportTestRun | null
  job_id: number | null
}

export interface ImporterInfo {
  name: string
  detail: string // 'XLSX, 23 kolumny, użyty 3 razy'
  version: string // 'v2'
}

// Backend objects that already exist (JobOut, RunOut in backend/riskminer/api/schemas.py).
export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'error' | 'cancelled' | (string & {})

export interface JobOut {
  id: number
  kind: string
  payload: Record<string, unknown>
  status: JobStatus
  priority: number
  attempts: number
  run_after: string
  started_at: string | null
  finished_at: string | null
  result: Record<string, unknown> | null
  error: string | null
  created_at: string
}

export interface RunOut {
  id: number | string
  connector: string
  stage: string
  params: Record<string, unknown>
  started_at: string
  finished_at: string | null
  status: string
  stats: Record<string, unknown>
  error: string | null
  job_id: number | null
}

export type RunsOut = Page<RunOut>
