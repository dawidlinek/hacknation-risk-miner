import type {
  NationalQuery,
  NationalSort,
  NationalStatus,
  ProjectFilter,
  ProjectRow,
  ProjectSortKey,
} from '@/api/contracts/projects'
import { fmtInt } from '@/lib/format'

export const FILTER_VALUES = ['all', 'late', 'discrepancy', 'review'] as const

/** URL slugs (Polish) <-> filter values. */
export const FILTER_SLUG: Record<ProjectFilter, string> = {
  all: 'wszystkie',
  late: 'po-terminie',
  discrepancy: 'rozbieznosc',
  review: 'do-przegladu',
}
export const slugToFilter = (s: string | undefined): ProjectFilter =>
  (Object.entries(FILTER_SLUG).find(([, v]) => v === s)?.[0] as ProjectFilter | undefined) ?? 'all'

/** Sortable table columns (B2). Zmiany, Wykonanie and Stan were dropped from the table, so old links fall back. */
export const SORT_KEYS: ProjectSortKey[] = ['title', 'subsector', 'value', 'delay', 'cost']

export function matchesFilter(r: ProjectRow, f: ProjectFilter): boolean {
  switch (f) {
    case 'all':
      return true
    case 'late':
      return (r.delay_days ?? 0) > 0
    case 'discrepancy':
      return r.state.tone === 'discrepancy'
    case 'review':
      return r.state.tone === 'review'
  }
}

export function filterRows(
  rows: ProjectRow[],
  o: { q?: string; filter?: ProjectFilter; subsector?: string },
): ProjectRow[] {
  const q = (o.q ?? '').trim().toLowerCase()
  return rows.filter(
    (r) =>
      matchesFilter(r, o.filter ?? 'all') &&
      (!o.subsector || r.subsector_label === o.subsector) &&
      (!q || `${r.title} ${r.buyer_name} ${r.rm_id}`.toLowerCase().includes(q)),
  )
}

export function sortValue(r: ProjectRow, key: ProjectSortKey): string | number | null {
  switch (key) {
    case 'title':
      return r.title
    case 'subsector':
      return r.subsector_label
    case 'value':
      return r.contract_value.amount === null ? null : Number(r.contract_value.amount)
    case 'delay':
      return r.delay_days
    case 'cost':
      return r.cost_dev_pct
    case 'changes':
      return r.changes
    case 'performed':
      return r.properly_performed === null ? null : r.properly_performed ? 1 : 0
    case 'state':
      return r.state.label
  }
}

/** Bar widths used in the Opoznienie and Koszt cells (B2 mockup): delay capped at 400 d, cost at 50%. */
export const delayBarPct = (d: number) => Math.round((Math.min(Math.max(d, 0), 400) / 400) * 100)
export const costBarPct = (c: number) => Math.round((Math.min(Math.abs(c), 50) / 50) * 50)

// ---- national tab (URL search params <-> API query) ----

export const NATIONAL_PAGE_SIZE = 50
export const NATIONAL_SORTS: NationalSort[] = ['signed', 'delay', 'value']
export const NATIONAL_STATUS_SLUG: Record<NationalStatus, string> = {
  all: 'wszystkie',
  completed: 'zakonczone',
  ongoing: 'w-toku',
}
export const slugToNationalStatus = (s: string | undefined): NationalStatus =>
  (Object.entries(NATIONAL_STATUS_SLUG).find(([, v]) => v === s)?.[0] as NationalStatus | undefined) ?? 'all'

/** Voivodeships by TERYT code (the API filters on the 2-digit code). */
export const WOJEWODZTWA: { code: string; name: string }[] = [
  { code: '02', name: 'dolnośląskie' },
  { code: '04', name: 'kujawsko-pomorskie' },
  { code: '06', name: 'lubelskie' },
  { code: '08', name: 'lubuskie' },
  { code: '10', name: 'łódzkie' },
  { code: '12', name: 'małopolskie' },
  { code: '14', name: 'mazowieckie' },
  { code: '16', name: 'opolskie' },
  { code: '18', name: 'podkarpackie' },
  { code: '20', name: 'podlaskie' },
  { code: '22', name: 'pomorskie' },
  { code: '24', name: 'śląskie' },
  { code: '26', name: 'świętokrzyskie' },
  { code: '28', name: 'warmińsko-mazurskie' },
  { code: '30', name: 'wielkopolskie' },
  { code: '32', name: 'zachodniopomorskie' },
]

export interface NationalSearch {
  q?: string
  woj?: string
  status?: string
  od?: number
  do?: number
  skladniki?: boolean
  nsort?: NationalSort
  nkier?: 'asc' | 'desc'
  str?: number
}

/** The API sort token: descending is the bare key, ascending adds `_asc`. Default: newest contracts first. */
export function nationalApiSort(sort: NationalSort | undefined, dir: 'asc' | 'desc' | undefined): string {
  const key = sort && NATIONAL_SORTS.includes(sort) ? sort : 'signed'
  const d = dir ?? 'desc'
  return d === 'asc' ? `${key}_asc` : key
}

export function nationalQueryFrom(s: NationalSearch): NationalQuery {
  const status = slugToNationalStatus(s.status)
  return {
    q: s.q?.trim() || undefined,
    woj: s.woj || undefined,
    status: status === 'all' ? undefined : status,
    year_from: s.od,
    year_to: s.do,
    relevance: s.skladniki ? 'all' : undefined,
    sort: nationalApiSort(s.nsort, s.nkier),
    page: Math.max(1, s.str ?? 1),
    page_size: NATIONAL_PAGE_SIZE,
  }
}

/** "1–50 z 18 689" (en dash, grouped with NBSP). */
export function rangeLabel(page: number, pageSize: number, total: number): string {
  if (total === 0) return '0 wyników'
  const from = (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return `${fmtInt(from)}\u2013${fmtInt(to)} z ${fmtInt(total)}`
}
