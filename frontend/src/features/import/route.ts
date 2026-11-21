// Źródła (/zrodla): which dropped files are datasets for the import agent and which are case documents for the document
// pipeline (OCR, facts, automatic project linking). The final call is the backend's (inspect marks tables and project
// records; POST /api/imports/{code}/documents takes the rest), these helpers decide what the screen asks for and says.
import type { RealAnalysis } from '@/features/documents/types'

/** Extensions that may be a case document (or, as text, a project record: the agent's inspect tells them apart). */
export const DOCUMENT_EXT = ['pdf', 'docx', 'doc', 'odt', 'rtf', 'txt', 'md'] as const
/** Always datasets or archives: never sent to the document pipeline. */
export const DATASET_EXT = ['xlsx', 'xlsm', 'xls', 'csv', 'tsv', 'json', 'zip'] as const

export const extOf = (name: string): string => /\.([^.]+)$/.exec(name)?.[1]?.toLowerCase() ?? ''

export const maybeDocument = (name: string): boolean =>
  (DOCUMENT_EXT as readonly string[]).includes(extOf(name))

/** After inspect: ask the backend to route documents when any file could be one. */
export const needsDocumentRouting = (files: { name: string }[]): boolean =>
  files.some((f) => maybeDocument(f.name))

/** After routing: the mapping step runs only when a dataset or project record is left for the agent. */
export const needsMapping = (files: { name: string }[], routed: { tables: number } | null): boolean =>
  routed ? routed.tables > 0 : files.length > 0

export const NO_FILES_IN_DROP =
  'Nie odczytaliśmy pliku z przeciągnięcia. Przeciągnij plik z folderu na dysku albo użyj przycisku „Wybierz pliki”.'

/** What an earlier upload of the same file (same SHA-256) already produced. */
export interface PreviousUpload {
  project_rm_id: string | null
  has_facts: boolean
  linked: boolean
  open_review_items: number
}

export interface RoutedDocument {
  name: string
  document_id: number | null
  duplicate: boolean
  text_status: string | null
  jobs: { kind: string; job_id: number }[]
  error: string | null
  previous?: PreviousUpload | null
}

/** "Ten plik już był: pokazujemy wyniki z pierwszego wczytania (projekt RM-2026-002)." The counts follow below it. */
export function duplicateLine(d: Pick<RoutedDocument, 'duplicate' | 'previous' | 'jobs'>): string | null {
  if (!d.duplicate) return null
  const rm = d.previous?.project_rm_id
  const head =
    d.jobs.length > 0
      ? 'Ten plik już był, ale nie został przetworzony do końca: uruchamiamy to ponownie'
      : 'Ten plik już był: pokazujemy wyniki z pierwszego wczytania'
  return `${head}${rm ? ` (projekt ${rm})` : ''}.`
}

export interface RouteResult {
  code: string
  documents: RoutedDocument[]
  tables: number
}

const LINK_METHOD: Record<string, string> = {
  exact_id: 'numer KPO z dokumentu',
  user_bound: 'dokument wgrany na karcie projektu',
  fuzzy: 'zamawiający i tytuł zadania',
}

const score = (s: number | null | undefined) => (s ?? 0).toFixed(2).replace('.', ',')

/** "RM-2026-002, numer KPO z dokumentu, wynik 1,00" or null before linking. */
export function projectLine(a: Pick<RealAnalysis, 'link'>): string | null {
  const p = a.link?.project
  if (!p) return null
  return `${p.rm_id}, ${LINK_METHOD[p.method] ?? p.method}, wynik ${score(p.score)}`
}

/** "umowa z wykonawcą X, wynik 0,65, do potwierdzenia w Przeglądzie". */
export function contractLine(a: Pick<RealAnalysis, 'link'>): string | null {
  const c = a.link?.contract
  if (!c) return null
  return `umowa z wykonawcą ${c.contractor}, wynik ${score(c.score)}, do potwierdzenia w Przeglądzie`
}

function plural(n: number, one: string, few: string, many: string) {
  return n === 1 ? one : n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14) ? few : many
}
/** "+1 zmiana umowy, +3 zdarzenia ryzyka, 6 propozycji do przeglądu". */
export function resultLine(a: Pick<RealAnalysis, 'growth' | 'review_items'>): string | null {
  const parts: string[] = []
  if (a.growth?.short) parts.push(a.growth.short)
  const open = a.review_items.filter((i) => i.status === 'open').length
  if (open > 0) parts.push(`${open} ${plural(open, 'propozycja', 'propozycje', 'propozycji')} do przeglądu`)
  return parts.length > 0 ? parts.join(', ') : null
}

/** Failed identifier checks, e.g. "NIP 8161571014: suma kontrolna niepoprawna. W rejestrze: 8161570014." */
export function failedChecks(a: Pick<RealAnalysis, 'link'>): string[] {
  return (a.link?.checks ?? [])
    .filter((c) => !c.ok)
    .map(
      (c) =>
        `${c.kind.toUpperCase()} ${c.value}: ${c.detail}${c.expected && c.kind !== 'kpo' ? `. W rejestrze: ${c.expected}.` : '.'}`,
    )
}

/** Link to the document on the project card (Dokumenty tab, the panel with "Co się zmieniło"). */
export const cardHref = (rmId: string, documentId: number) =>
  ({ to: '/projekty/$id/dokumenty', params: { id: rmId }, search: { dok: `doc:${documentId}` } }) as const
