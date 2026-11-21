// Real /api/imports* (D, imports/service.py) -> api/contracts/import.ts.
import type {
  ImporterInfo,
  ImportMappingRow,
  ImportSession,
  ImportStatus,
  ImportTestRun,
  MappingState,
} from '@/api/contracts/import'

interface RealMapping {
  column: string
  field: string | null
  label?: string
  rule: string | null
  status: MappingState
  valid?: number | null
  total?: number | null
}

export interface RealImport {
  code: string
  status: ImportStatus
  status_label: string
  files: { name: string; bytes: number; kind: string; duplicate_of_source_id: number | null }[]
  tool_calls: { call: string; out: string }[]
  mapping: RealMapping[]
  questions: { key: string; text: string; options: { value: string; label: string }[] }[]
  rules: string[]
  importer: { name: string; version: string } | null
  test_run: {
    ok: number
    failed: number
    rows?: number
    review_items_created?: number
    failures?: { row: number; column: string; rule: string }[]
  } | null
  job_id: number | null
  answers?: Record<string, string>
}

const size = (b: number) =>
  b >= 1e6 ? `${(b / 1e6).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(b / 1e3))} kB`

const RULE_PL: Record<string, string> = {
  nip_checksum: 'suma kontrolna NIP',
  money_requires_vat_basis: 'kwota z rodzajem: netto lub brutto',
  text_no_analysis: 'tekst, bez analizy',
  personal_data: 'dane osobowe, pomijane',
  bzp_format: 'format RRRR/BZP NNNNNNNN/VV',
}

function mappingRow(m: RealMapping, answers: Record<string, string>): ImportMappingRow {
  let label = 'zgodne'
  if (m.status === 'question') label = 'pytanie'
  else if (m.status === 'check') label = 'sprawdzić'
  else if (m.status === 'proposal') label = 'propozycja'
  else if (m.status === 'dropped') label = 'pominięte'
  else if (m.total && m.valid !== null && m.valid !== undefined && m.valid < m.total)
    label = `${m.valid} z ${m.total}`
  if (m.rule === 'money_requires_vat_basis' && m.status === 'ok' && answers.value_vat_basis) {
    label = answers.value_vat_basis === 'gross' ? 'brutto' : 'netto'
  }
  return {
    column: m.column,
    field: m.field ?? 'brak',
    rule: m.rule ? (RULE_PL[m.rule] ?? m.rule) : 'bez reguły',
    state: m.status,
    state_label: label,
  }
}

export function adaptImport(raw: RealImport): ImportSession {
  const answers = raw.answers ?? {}
  const testRun: ImportTestRun | null = raw.test_run
    ? {
        ok: raw.test_run.ok,
        failed: raw.test_run.failed,
        rows: raw.test_run.rows ?? raw.test_run.ok + raw.test_run.failed,
        review_items_created: raw.test_run.review_items_created ?? 0,
        failures: raw.test_run.failures ?? [],
      }
    : null
  return {
    code: raw.code,
    status: raw.status,
    status_label: raw.status_label,
    files: raw.files.map((f) => ({
      name: f.name,
      detail: `${size(f.bytes)}, ${f.kind.toUpperCase()}`,
      duplicate: f.duplicate_of_source_id !== null && f.duplicate_of_source_id !== undefined,
    })),
    tool_calls: raw.tool_calls.map((c) => ({ call: c.call, out: c.out })),
    mapping: raw.mapping.map((m) => mappingRow(m, answers)),
    questions: raw.questions.map((q) => ({ key: q.key, title: q.text, options: q.options })),
    answers,
    rules: raw.rules,
    importer: raw.importer,
    test_run: testRun,
    job_id: raw.job_id,
  }
}

export interface RealImporter {
  name: string
  format_label?: string
  uses?: number
  version: string
}

export const adaptImporters = (raw: RealImporter[]): ImporterInfo[] =>
  raw.map((i) => ({
    name: i.name,
    detail: [i.format_label, i.uses ? `użyty ${i.uses} ${i.uses === 1 ? 'raz' : 'razy'}` : null]
      .filter(Boolean)
      .join(', '),
    version: i.version,
  }))
