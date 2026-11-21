import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronDown, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { ProjectFilter, ProjectRow, ProjectSortKey } from '@/api/contracts/projects'
import { Page, PageHeader } from '@/app/Page'
import { useSession } from '@/auth/session'
import { EmptyState } from '@/components/common/DataState'
import { type DataColumn, DataTable } from '@/components/common/DataTable'
import { ExportMenu } from '@/components/common/ExportMenu'
import { FilterPills } from '@/components/common/FilterPills'
import { StatCard } from '@/components/common/StatCard'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/cn'
import { fmtDays, fmtMoneyShort, fmtPct } from '@/lib/format'
import { plural } from '@/lib/plural'
import { projectsTableQuery } from './api'
import { costBarPct, delayBarPct, FILTER_SLUG, filterRows, SORT_KEYS, slugToFilter, sortValue } from './logic'

export interface ProjectsSearch {
  q?: string
  filtr?: string
  podsektor?: string
  sort?: ProjectSortKey
  kier?: 'asc' | 'desc'
  str?: number
}

const PAGE_SIZE = 10

export function ProjectsScreen({
  search,
  onSearch,
}: {
  search: ProjectsSearch
  onSearch: (patch: Partial<ProjectsSearch>) => void
}) {
  const { data } = useSuspenseQuery(projectsTableQuery)
  const { isPublic } = useSession()
  const filter: ProjectFilter = slugToFilter(search.filtr)
  const sortId: ProjectSortKey = search.sort && SORT_KEYS.includes(search.sort) ? search.sort : 'delay'
  const desc = (search.kier ?? 'desc') === 'desc'
  const page = Math.max(0, (search.str ?? 1) - 1)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [qDraft, setQDraft] = useState(search.q ?? '')

  useEffect(() => setQDraft(search.q ?? ''), [search.q])
  // selection is cleared when the filter changes
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset on filter inputs only
  useEffect(() => setSelected(new Set()), [search.q, search.filtr, search.podsektor])

  const rows = useMemo(
    () => filterRows(data.items, { q: search.q, filter, subsector: search.podsektor }),
    [data.items, search.q, filter, search.podsektor],
  )

  const columns = useMemo<DataColumn<ProjectRow>[]>(
    () => [
      {
        id: 'title',
        header: 'Projekt',
        sortValue: (r) => sortValue(r, 'title'),
        className: 'w-[46%] min-w-[300px] whitespace-normal',
        cell: (r) => (
          <div className="flex flex-col gap-0.5">
            <Link
              to="/projekty/$id"
              params={{ id: r.rm_id }}
              className="t-item line-clamp-2 text-text no-underline hover:underline"
            >
              {r.title}
            </Link>
            <span className="t-mono line-clamp-1 text-muted">
              {r.rm_id}, {r.buyer_name}
            </span>
          </div>
        ),
      },
      {
        id: 'subsector',
        header: 'Podsektor',
        className: 'w-[18%] whitespace-normal',
        sortValue: (r) => sortValue(r, 'subsector'),
        cell: (r) => r.subsector_label,
      },
      {
        id: 'value',
        header: 'Wartość umowy',
        className: 'whitespace-nowrap',
        align: 'right',
        sortValue: (r) => sortValue(r, 'value'),
        cell: (r) =>
          r.contract_value.amount === null
            ? 'brak'
            : fmtMoneyShort(Number(r.contract_value.amount) / 1e6, 'mln'),
      },
      {
        id: 'delay',
        header: 'Opóźnienie',
        className: 'whitespace-nowrap',
        align: 'right',
        sortValue: (r) => sortValue(r, 'delay'),
        cell: (r) => (
          <div className="flex flex-col items-end gap-1">
            <span className={cn('font-medium', (r.delay_days ?? 0) > 0 && 'text-attention-text')}>
              {r.delay_days === null ? 'brak' : fmtDays(r.delay_days, { short: true })}
            </span>
            {r.delay_days !== null && r.delay_days > 0 ? (
              <span aria-hidden className="h-1 w-16 overflow-hidden rounded-pill bg-soft-2">
                <span
                  className={cn('block h-full', r.delay_days > 90 ? 'bg-attention' : 'bg-text-secondary')}
                  style={{ width: `${delayBarPct(r.delay_days)}%` }}
                />
              </span>
            ) : null}
          </div>
        ),
      },
      {
        id: 'cost',
        header: 'Koszt wobec umowy',
        className: 'whitespace-nowrap',
        align: 'right',
        sortValue: (r) => sortValue(r, 'cost'),
        cell: (r) => (
          <div className="flex flex-col items-end gap-1">
            <span className={cn('font-medium', (r.cost_dev_pct ?? 0) > 0.5 && 'text-attention-text')}>
              {r.cost_dev_pct === null ? 'brak' : fmtPct(r.cost_dev_pct, { signed: true })}
            </span>
            {r.cost_dev_pct !== null && r.cost_dev_pct !== 0 ? (
              <span aria-hidden className="relative h-1 w-16 overflow-hidden rounded-pill bg-soft-2">
                <span
                  className={cn(
                    'absolute top-0 h-full',
                    r.cost_dev_pct >= 0 ? 'left-1/2 bg-attention' : 'right-1/2 bg-text-secondary',
                  )}
                  style={{ width: `${costBarPct(r.cost_dev_pct)}%` }}
                />
              </span>
            ) : null}
          </div>
        ),
      },
    ],
    [],
  )

  const subsectors = data.facets.subsectors
  const total = rows.length
  const shown = Math.min(PAGE_SIZE, Math.max(0, total - page * PAGE_SIZE))
  const ids = [...selected]

  return (
    <Page>
      <PageHeader
        title="Projekty"
        actions={
          <ExportMenu
            label="Eksportuj zaznaczone"
            formats={['csv', 'json']}
            disabled={selected.size === 0}
            urlFor={(f) =>
              `/api/export/projects.${f}?rm_ids=${encodeURIComponent(ids.join(','))}${f === 'csv' ? '&sep=semicolon' : ''}`
            }
            filename={(f) => `projekty.${f}`}
          />
        }
      />

      {data.stats.length > 0 ? (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          {data.stats.map((s) => (
            <StatCard key={s.label} label={s.label} value={s.value} note={s.note} />
          ))}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        {/* biome-ignore lint/a11y/noLabelWithoutControl: the Input component renders the control */}
        <label className="relative min-w-[260px] flex-1">
          <span className="sr-only">Szukaj projektu</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted"
          />
          <Input
            type="search"
            value={qDraft}
            onChange={(e) => setQDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSearch({ q: qDraft.trim() || undefined, str: undefined })
            }}
            onBlur={() =>
              qDraft !== (search.q ?? '') && onSearch({ q: qDraft.trim() || undefined, str: undefined })
            }
            placeholder="Szukaj: gmina, NIP, numer BZP lub KPO"
            className="h-10 w-full pl-10"
          />
        </label>
        <FilterPills
          label="Filtry projektów"
          value={filter}
          onChange={(v) => onSearch({ filtr: v === 'all' ? undefined : FILTER_SLUG[v], str: undefined })}
          options={[
            { value: 'all', label: 'Wszystkie', count: data.facets.all },
            { value: 'late', label: 'Po terminie', count: data.facets.late },
            { value: 'discrepancy', label: 'Z rozbieżnością', count: data.facets.discrepancy },
            { value: 'review', label: 'Do przeglądu', hidden: isPublic },
          ]}
        >
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="lg" className={cn(search.podsektor && 'border-ink')}>
                {search.podsektor ?? 'Podsektor'}
                <ChevronDown aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onSelect={() => onSearch({ podsektor: undefined, str: undefined })}>
                Wszystkie podsektory
              </DropdownMenuItem>
              {subsectors.map((s) => (
                <DropdownMenuItem
                  key={s.key}
                  onSelect={() => onSearch({ podsektor: s.label, str: undefined })}
                >
                  {s.label} <span className="t-mono ml-2 text-muted">{s.n}</span>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </FilterPills>
      </div>

      {rows.length === 0 ? (
        <EmptyState>
          Brak projektów dla tych filtrów.{' '}
          <Button
            variant="link"
            className="h-auto p-0"
            onClick={() => onSearch({ q: undefined, filtr: undefined, podsektor: undefined, str: undefined })}
          >
            Wyczyść filtry
          </Button>
        </EmptyState>
      ) : (
        <div className="rounded-panel border border-divider px-2 py-1">
          <DataTable
            caption="Projekty wodno-kanalizacyjne z porównaniem terminu i kosztu do umowy"
            data={rows}
            columns={columns}
            getRowId={(r) => r.rm_id}
            sort={{ id: sortId, desc }}
            onSort={(id) =>
              onSearch(
                id === sortId
                  ? { kier: desc ? 'asc' : 'desc', str: undefined }
                  : { sort: id as ProjectSortKey, kier: 'desc', str: undefined },
              )
            }
            selected={selected}
            onSelectedChange={setSelected}
            pageIndex={page}
            pageSize={PAGE_SIZE}
          />
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 text-[14px] text-text-body-muted">
        <span>
          Pokazano {shown} z {total} {plural(total, ['projektu', 'projektów', 'projektów'])}. Kwoty brutto z
          ogłoszeń BZP.
        </span>
        <span className="flex gap-2">
          <Button
            variant="outline"
            disabled={page === 0}
            onClick={() => onSearch({ str: page === 0 ? undefined : page })}
          >
            Poprzednie
          </Button>
          <Button
            variant="outline"
            disabled={(page + 1) * PAGE_SIZE >= total}
            onClick={() => onSearch({ str: page + 2 })}
          >
            Następne
          </Button>
        </span>
      </div>
    </Page>
  )
}
