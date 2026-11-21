import {
  type ColumnDef,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  type SortingFn,
  useReactTable,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { type ReactNode, useMemo } from 'react'
import { Checkbox } from '@/components/ui/checkbox'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/cn'

export interface DataColumn<T> {
  id: string
  header: string
  align?: 'left' | 'right'
  /** sortable when given; null values sort last in both directions */
  sortValue?: (row: T) => string | number | null
  cell: (row: T) => ReactNode
  className?: string
}

export interface SortState {
  id: string
  desc: boolean
}

// null/undefined always last, regardless of direction (TanStack inverts the result for desc, so compensate).
const nullsLast: SortingFn<unknown> = (a, b, id) => {
  const x = a.getValue(id) as string | number | null
  const y = b.getValue(id) as string | number | null
  if (x === null && y === null) return 0
  if (x === null) return 1
  if (y === null) return -1
  if (typeof x === 'string' && typeof y === 'string') return x.localeCompare(y, 'pl')
  return (x as number) > (y as number) ? 1 : (x as number) < (y as number) ? -1 : 0
}

/**
 * TanStack Table wrapper: aria-sort headers, optional row selection, client-side paging.
 * Sorting and paging state are controlled (the route keeps them in the URL).
 */
export function DataTable<T>({
  data,
  columns,
  getRowId,
  sort,
  onSort,
  selected,
  onSelectedChange,
  pageIndex = 0,
  pageSize = 10,
  caption,
  className,
}: {
  data: T[]
  columns: DataColumn<T>[]
  getRowId: (row: T) => string
  sort: SortState
  onSort: (id: string) => void
  selected?: Set<string>
  onSelectedChange?: (next: Set<string>) => void
  pageIndex?: number
  pageSize?: number
  caption: string
  className?: string
}) {
  const defs = useMemo<ColumnDef<T>[]>(
    () =>
      columns.map((c) => ({
        id: c.id,
        accessorFn: (row: T) => (c.sortValue ? c.sortValue(row) : null),
        enableSorting: Boolean(c.sortValue),
        sortingFn: nullsLast as SortingFn<T>,
        sortUndefined: 'last' as const,
      })),
    [columns],
  )
  const table = useReactTable({
    data,
    columns: defs,
    getRowId,
    state: { sorting: [sort], pagination: { pageIndex, pageSize } },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualPagination: false,
    enableSortingRemoval: false,
  })
  const rows = table.getRowModel().rows
  const all = data.length > 0 && selected && data.every((r) => selected.has(getRowId(r)))
  const some = selected && selected.size > 0 && !all

  return (
    <Table className={cn('text-[14px]', className)}>
      <caption className="sr-only">{caption}</caption>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {selected && onSelectedChange ? (
            <TableHead className="w-10 pl-3">
              <Checkbox
                aria-label="Zaznacz wszystkie projekty"
                checked={all ? true : some ? 'indeterminate' : false}
                onCheckedChange={(v) =>
                  onSelectedChange(v === true ? new Set(data.map(getRowId)) : new Set())
                }
              />
            </TableHead>
          ) : null}
          {columns.map((c) => {
            const active = sort.id === c.id
            return (
              <TableHead
                key={c.id}
                aria-sort={
                  c.sortValue ? (active ? (sort.desc ? 'descending' : 'ascending') : 'none') : undefined
                }
                className={cn(
                  'px-3 text-[12.5px] font-semibold text-text-secondary',
                  c.align === 'right' && 'text-right',
                )}
              >
                {c.sortValue ? (
                  <button
                    type="button"
                    onClick={() => onSort(c.id)}
                    className={cn(
                      'inline-flex items-center gap-1.5 text-[12.5px] font-semibold',
                      c.align === 'right' && 'flex-row-reverse',
                    )}
                  >
                    {c.header}
                    {active ? (
                      sort.desc ? (
                        <ArrowDown className="size-3.5 text-text" aria-hidden />
                      ) : (
                        <ArrowUp className="size-3.5 text-text" aria-hidden />
                      )
                    ) : (
                      <ArrowUpDown className="size-3.5 text-muted" aria-hidden />
                    )}
                  </button>
                ) : (
                  c.header
                )}
              </TableHead>
            )
          })}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => {
          const id = row.id
          const isSel = selected?.has(id) ?? false
          return (
            <TableRow key={id} data-state={isSel ? 'selected' : undefined}>
              {selected && onSelectedChange ? (
                <TableCell className="w-10 pl-3">
                  <Checkbox
                    aria-label={`Zaznacz ${id}`}
                    checked={isSel}
                    onCheckedChange={(v) => {
                      const next = new Set(selected)
                      if (v === true) next.add(id)
                      else next.delete(id)
                      onSelectedChange(next)
                    }}
                  />
                </TableCell>
              ) : null}
              {columns.map((c) => (
                <TableCell
                  key={c.id}
                  className={cn('px-3 py-3 align-middle', c.align === 'right' && 'text-right', c.className)}
                >
                  {c.cell(row.original)}
                </TableCell>
              ))}
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
