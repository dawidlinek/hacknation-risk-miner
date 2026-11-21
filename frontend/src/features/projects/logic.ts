import type { ProjectFilter, ProjectRow, ProjectSortKey } from '@/api/contracts/projects'

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

export const SORT_KEYS: ProjectSortKey[] = [
  'title',
  'subsector',
  'value',
  'delay',
  'cost',
  'changes',
  'performed',
  'state',
]

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
