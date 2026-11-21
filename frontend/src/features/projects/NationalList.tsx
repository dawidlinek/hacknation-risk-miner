import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronDown, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { NationalRow, NationalSort } from '@/api/contracts/projects'
import { EmptyState } from '@/components/common/DataState'
import { type DataColumn, DataTable } from '@/components/common/DataTable'
import { FilterPills } from '@/components/common/FilterPills'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/cn'
import { fmtDays, fmtPlnAuto } from '@/lib/format'
import { nationalQuery } from './api'
import {
  NATIONAL_PAGE_SIZE,
  NATIONAL_SORTS,
  type NationalSearch,
  nationalQueryFrom,
  rangeLabel,
  slugToNationalStatus,
  WOJEWODZTWA,
} from './logic'

const STATUS_PILLS = [
  { value: 'all', label: 'Wszystkie', slug: undefined },
  { value: 'completed', label: 'Zakończone', slug: 'zakonczone' },
  { value: 'ongoing', label: 'W toku', slug: 'w-toku' },
] as const

const YEARS = Array.from({ length: 8 }, (_, i) => 2020 + i)

/** Whole-country list (server-side paging, search, filters and sort). Each row opens that procedure's automatic card. */
export function NationalList({
  search,
  onSearch,
}: {
  search: NationalSearch
  onSearch: (patch: Partial<NationalSearch>) => void
}) {
  const query = useMemo(() => nationalQueryFrom(search), [search])
  const { data, isError, error, isFetching } = useQuery({
    ...nationalQuery(query),
    placeholderData: keepPreviousData,
  })
  const [qDraft, setQDraft] = useState(search.q ?? '')
  useEffect(() => setQDraft(search.q ?? ''), [search.q])

  const status = slugToNationalStatus(search.status)
  const sortId: NationalSort = search.nsort && NATIONAL_SORTS.includes(search.nsort) ? search.nsort : 'signed'
  const desc = (search.nkier ?? 'desc') === 'desc'
  const page = query.page ?? 1
  const wojName = WOJEWODZTWA.find((w) => w.code === search.woj)?.name
  const reset = { str: undefined }

  const columns = useMemo<DataColumn<NationalRow>[]>(
    () => [
      {
        id: 'title',
        header: 'Postępowanie',
        className: 'w-[40%] min-w-[280px] whitespace-normal',
        cell: (r) => (
          <div className="flex flex-col gap-0.5">
            <Link
              to="/projekty/$id"
              params={{ id: r.id }}
              className="t-item line-clamp-2 text-text no-underline hover:underline"
            >
              {r.title ?? r.id}
            </Link>
            <span className="line-clamp-1 text-[13px] text-muted">
              {[r.buyer, r.gmina].filter(Boolean).join(', ')}
            </span>
          </div>
        ),
      },
      {
        id: 'status',
        header: 'Status',
        className: 'whitespace-nowrap',
        cell: (r) => r.status_label,
      },
      {
        id: 'signed',
        header: 'Podpisano',
        className: 'whitespace-nowrap',
        sortValue: (r) => r.signed_on,
        cell: (r) => <span className="t-mono">{r.signed_on ?? 'brak'}</span>,
      },
      {
        id: 'planned',
        header: 'Termin z umowy',
        className: 'whitespace-nowrap',
        cell: (r) => <span className="t-mono">{r.planned_end_on ?? 'brak'}</span>,
      },
      {
        id: 'actual',
        header: 'Zakończenie',
        className: 'whitespace-nowrap',
        cell: (r) => (
          <span className={cn('t-mono', r.status === 'ongoing' && 'text-text-secondary')}>
            {r.actual_end_label ?? 'brak'}
          </span>
        ),
      },
      {
        id: 'value',
        header: 'Wartość umowy',
        className: 'whitespace-nowrap',
        align: 'right',
        sortValue: (r) => (r.value.amount === null ? null : Number(r.value.amount)),
        cell: (r) => (r.value.amount === null ? 'brak' : fmtPlnAuto(r.value.amount)),
      },
      {
        id: 'delay',
        header: 'Opóźnienie',
        className: 'whitespace-nowrap',
        align: 'right',
        sortValue: (r) => r.delay_days.value,
        cell: (r) => {
          const d = r.delay_days.value
          return (
            <span className={cn('font-medium', (d ?? 0) > 0 && 'text-attention-text')}>
              {d === null ? r.delay_days.display : fmtDays(d, { short: true })}
            </span>
          )
        },
      },
      {
        id: 'changes',
        header: 'Zmiany',
        className: 'whitespace-nowrap',
        align: 'right',
        cell: (r) => r.changes.value ?? 0,
      },
    ],
    [],
  )

  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / NATIONAL_PAGE_SIZE))

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        {/* biome-ignore lint/a11y/noLabelWithoutControl: the Input component renders the control */}
        <label className="relative min-w-[260px] flex-1">
          <span className="sr-only">Szukaj w całej Polsce</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted"
          />
          <Input
            type="search"
            value={qDraft}
            onChange={(e) => setQDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSearch({ q: qDraft.trim() || undefined, ...reset })
            }}
            onBlur={() =>
              qDraft !== (search.q ?? '') && onSearch({ q: qDraft.trim() || undefined, ...reset })
            }
            placeholder="Szukaj: tytuł, zamawiający lub gmina"
            className="h-10 w-full pl-10"
          />
        </label>
        <FilterPills
          label="Status umowy"
          value={status}
          onChange={(v) => onSearch({ status: STATUS_PILLS.find((p) => p.value === v)?.slug, ...reset })}
          options={STATUS_PILLS.map((p) => ({ value: p.value, label: p.label }))}
        >
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="lg" className={cn(search.woj && 'border-ink')}>
                {wojName ? `Woj. ${wojName}` : 'Województwo'}
                <ChevronDown aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
              <DropdownMenuItem onSelect={() => onSearch({ woj: undefined, ...reset })}>
                Cała Polska
              </DropdownMenuItem>
              {WOJEWODZTWA.map((w) => (
                <DropdownMenuItem key={w.code} onSelect={() => onSearch({ woj: w.code, ...reset })}>
                  {w.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <YearMenu label="Od roku" value={search.od} onChange={(v) => onSearch({ od: v, ...reset })} />
          <YearMenu label="Do roku" value={search.do} onChange={(v) => onSearch({ do: v, ...reset })} />
        </FilterPills>
      </div>

      <label className="flex items-center gap-2 text-[14px] text-text-body-muted">
        <input
          type="checkbox"
          checked={Boolean(search.skladniki)}
          onChange={(e) => onSearch({ skladniki: e.target.checked || undefined, ...reset })}
        />
        Pokaż także postępowania, w których wod-kan jest tylko częścią zakresu
      </label>

      {isError ? (
        <EmptyState>{error instanceof Error ? error.message : 'Nie udało się pobrać listy.'}</EmptyState>
      ) : !data ? (
        <div className="rounded-panel border border-divider p-6 text-text-body-muted">Ładowanie listy...</div>
      ) : data.items.length === 0 ? (
        <EmptyState>
          Brak postępowań dla tych filtrów.{' '}
          <Button
            variant="link"
            className="h-auto p-0"
            onClick={() =>
              onSearch({
                q: undefined,
                woj: undefined,
                status: undefined,
                od: undefined,
                do: undefined,
                skladniki: undefined,
                ...reset,
              })
            }
          >
            Wyczyść filtry
          </Button>
        </EmptyState>
      ) : (
        <div className={cn('rounded-panel border border-divider px-2 py-1', isFetching && 'opacity-70')}>
          <DataTable
            caption="Wszystkie postępowania wodno-kanalizacyjne w Polsce z terminem, wartością i opóźnieniem"
            data={data.items}
            columns={columns}
            getRowId={(r) => r.id}
            sort={{ id: sortId, desc }}
            onSort={(id) =>
              onSearch(
                id === sortId
                  ? { nkier: desc ? 'asc' : 'desc', ...reset }
                  : { nsort: id as NationalSort, nkier: 'desc', ...reset },
              )
            }
            pageIndex={0}
            pageSize={NATIONAL_PAGE_SIZE}
          />
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 text-[14px] text-text-body-muted">
        <span>
          {data ? rangeLabel(page, NATIONAL_PAGE_SIZE, total) : ''}. Wartości brutto z umów w BZP, opóźnienie
          to wyliczenie z ogłoszeń.
        </span>
        <span className="flex items-center gap-2">
          <span>
            Strona {page} z {pages}
          </span>
          <Button
            variant="outline"
            disabled={page <= 1}
            onClick={() => onSearch({ str: page <= 2 ? undefined : page - 1 })}
          >
            Poprzednie
          </Button>
          <Button variant="outline" disabled={page >= pages} onClick={() => onSearch({ str: page + 1 })}>
            Następne
          </Button>
        </span>
      </div>
    </div>
  )
}

function YearMenu({
  label,
  value,
  onChange,
}: {
  label: string
  value: number | undefined
  onChange: (v: number | undefined) => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="lg" className={cn(value && 'border-ink')}>
          {value ? `${label} ${value}` : label}
          <ChevronDown aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem onSelect={() => onChange(undefined)}>Dowolny</DropdownMenuItem>
        {YEARS.map((y) => (
          <DropdownMenuItem key={y} onSelect={() => onChange(y)}>
            {y}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
