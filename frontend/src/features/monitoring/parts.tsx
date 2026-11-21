import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { MoreHorizontal } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import type { MetricKey, MonitoringMode, Signal } from '@/api/contracts/monitoring'
import { cn } from '@/lib/cn'
import { fmtDays, fmtMoneyShort } from '@/lib/format'
import { type MonFilters, subsectorsQuery, VALUE_BUCKETS, YEARS } from './api'
import type { GeoFeature } from './geo'
import { outlinePath } from './geo'
import { MENU_METRICS, METRICS, SEGMENT_METRICS } from './logic'

/** Thumbnail of a region filled with its map colour. */
export function RegionOutline({ feature, fill }: { feature: GeoFeature | undefined; fill: string }) {
  if (!feature) return <span aria-hidden className="size-11 shrink-0 rounded-md bg-soft" />
  return (
    <svg viewBox="0 0 100 100" className="size-11 shrink-0" aria-hidden>
      <path d={outlinePath(feature)} fill={fill} stroke="#9a9a9a" strokeWidth={1} strokeLinejoin="round" />
    </svg>
  )
}

export function Segmented<V extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: V; label: string }[]
  value: V
  onChange: (v: V) => void
  label: string
}) {
  return (
    <fieldset className="m-0 inline-flex gap-1 rounded-inner border-0 bg-soft p-1">
      <legend className="sr-only">{label}</legend>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            'min-h-8.5 rounded-[10px] px-3.5 text-[14px] font-medium',
            o.value === value ? 'bg-ink text-on-ink' : 'text-text-secondary hover:text-text',
          )}
        >
          {o.label}
        </button>
      ))}
    </fieldset>
  )
}

export function ModeSwitch({
  mode,
  onChange,
}: {
  mode: MonitoringMode
  onChange: (m: MonitoringMode) => void
}) {
  return (
    <fieldset className="m-0 inline-flex gap-1 rounded-inner border-0 bg-soft-2 p-1">
      <legend className="sr-only">Które umowy pokazać</legend>
      {(
        [
          ['done', 'Zakończone'],
          ['open', 'W toku'],
        ] as const
      ).map(([v, l]) => (
        <button
          key={v}
          type="button"
          aria-pressed={mode === v}
          onClick={() => onChange(v)}
          className={cn(
            'min-h-8.5 rounded-[10px] px-4 text-[14px] font-medium',
            mode === v ? 'bg-surface text-text shadow-sm' : 'text-text-secondary hover:text-text',
          )}
        >
          {l}
        </button>
      ))}
    </fieldset>
  )
}

/** Floating toolbar over the map: colour metric, "..." menu with all metrics, legend and pins toggle. */
export function MapToolbar({
  mode,
  metric,
  onMetric,
  legend,
  pins,
  onPins,
  pinsLabel,
  pinsDisabled,
}: {
  mode: MonitoringMode
  metric: MetricKey
  onMetric: (m: MetricKey) => void
  legend: { lo: string; hi: string; gradient: string }
  pins: boolean
  onPins: () => void
  pinsLabel: string
  pinsDisabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  return (
    <div className="absolute right-3 bottom-3 left-3 flex flex-wrap items-center gap-3 rounded-item bg-surface/95 px-3 py-2 shadow-composer">
      {mode === 'done' ? (
        <span className="flex items-center gap-2">
          <span className="text-[13px] text-text-secondary">Kolor regionów:</span>
          <Segmented
            label="Metryka koloru regionów"
            value={SEGMENT_METRICS.includes(metric) ? metric : ('' as MetricKey)}
            onChange={onMetric}
            options={SEGMENT_METRICS.map((k) => ({ value: k, label: METRICS[k].label }))}
          />
          <div ref={box} className="relative">
            <button
              type="button"
              aria-label="Więcej miar"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
              className="grid size-9 place-items-center rounded-inner border border-border bg-surface hover:bg-soft"
            >
              <MoreHorizontal className="size-4" aria-hidden />
            </button>
            {open ? (
              <div
                role="menu"
                className="absolute bottom-11 left-0 z-20 flex w-[320px] flex-col rounded-item bg-surface p-1.5 shadow-popover"
              >
                {MENU_METRICS.map((k) => (
                  <button
                    key={k}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      onMetric(k)
                      setOpen(false)
                    }}
                    className={cn(
                      'flex flex-col items-start gap-0.5 rounded-inner px-3 py-2.5 text-left',
                      k === metric ? 'bg-soft' : 'hover:bg-soft',
                    )}
                  >
                    <span className="text-[14px] font-medium">{METRICS[k].label}</span>
                    <span className="t-caption text-text-body-muted">{METRICS[k].description}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </span>
      ) : (
        <span className="text-[13px] text-text-secondary">Kolor regionów: liczba sygnałów</span>
      )}
      <span className="flex items-center gap-2 text-[12px] text-text-secondary" aria-hidden>
        {legend.lo}
        <span className="h-2 w-28 rounded-pill" style={{ background: legend.gradient }} />
        {legend.hi}
      </span>
      <button
        type="button"
        aria-pressed={pins}
        disabled={pinsDisabled}
        onClick={onPins}
        className={cn(
          'ml-auto inline-flex min-h-8.5 items-center gap-2 rounded-inner border px-3 text-[14px] font-medium disabled:opacity-50',
          pins ? 'border-ink text-text' : 'border-border text-muted',
        )}
      >
        {pinsLabel}
      </button>
    </div>
  )
}

export function KpiTile({
  label,
  value,
  attention,
}: {
  label: string
  value: ReactNode
  attention?: boolean
}) {
  return (
    <div className="flex flex-col gap-1 rounded-item bg-soft px-4 py-3">
      <span className="t-eyebrow text-muted">{label}</span>
      <span
        className={cn(
          'text-[22px] leading-tight font-semibold tracking-tight',
          attention && 'text-attention-text',
        )}
      >
        {value}
      </span>
    </div>
  )
}

/** Signal rows (rank, buyer, object, value, days late) as links to the contract. */
export function SignalList({
  signals,
  hrefFor,
  limit,
  onPick,
}: {
  signals: Signal[]
  hrefFor: (s: Signal) => { to: string; params: Record<string, string> }
  limit?: number
  onPick?: (s: Signal) => void
}) {
  const rows = limit ? signals.slice(0, limit) : signals
  return (
    <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
      {rows.map((s, i) => {
        const h = hrefFor(s)
        return (
          <li key={s.id}>
            <Link
              to={h.to as never}
              params={h.params as never}
              search={((prev: Record<string, unknown>) => prev) as never}
              onClick={() => onPick?.(s)}
              className="grid grid-cols-[28px_1fr_auto] items-start gap-3 rounded-item bg-surface px-3.5 py-2.5 text-text no-underline hover:bg-soft"
            >
              <span className="t-mono pt-0.5 text-muted">{String(i + 1).padStart(2, '0')}</span>
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="t-item truncate">{s.buyer}</span>
                <span className="line-clamp-2 text-[13px] text-text-body-muted">{s.object}</span>
                <span className="t-mono text-muted">
                  {s.bzp}, {fmtMoneyShort(Number(s.value.amount ?? 0) / 1e6, 'mln')}
                  {s.parts > 1 ? `, ${s.parts} części` : ''}
                </span>
              </span>
              <span className={cn('t-item whitespace-nowrap', i === 0 && 'text-attention-text')}>
                {s.days_late === null ? 'brak' : fmtDays(s.days_late, { short: true })}
              </span>
            </Link>
          </li>
        )
      })}
    </ol>
  )
}

const selectCls = (on: boolean) =>
  cn(
    'h-10 rounded-inner border bg-surface px-3 text-[14px] font-medium',
    on ? 'border-ink text-text' : 'border-border text-text',
  )

/** Podsektor, Wartość and Lata dropdowns of the map (D2); the API filters regions, panels and signals by them. */
export function FilterBar({ filters, onChange }: { filters: MonFilters; onChange: (f: MonFilters) => void }) {
  const subs = useQuery(subsectorsQuery)
  return (
    <fieldset className="m-0 flex flex-wrap items-center gap-2 border-0 p-0">
      <legend className="sr-only">Filtry mapy</legend>
      <select
        aria-label="Podsektor"
        value={filters.subsector ?? ''}
        onChange={(e) => onChange({ ...filters, subsector: e.target.value || undefined })}
        className={selectCls(Boolean(filters.subsector))}
      >
        <option value="">Podsektor: wszystkie</option>
        {(subs.data ?? []).map((s) => (
          <option key={s.code} value={s.code}>
            {s.name}
          </option>
        ))}
      </select>
      <select
        aria-label="Wartość umowy"
        value={filters.value ?? ''}
        onChange={(e) => onChange({ ...filters, value: e.target.value || undefined })}
        className={selectCls(Boolean(filters.value))}
      >
        <option value="">Wartość: każda</option>
        {VALUE_BUCKETS.map((b) => (
          <option key={b.key} value={b.key}>
            {b.label} brutto
          </option>
        ))}
      </select>
      <select
        aria-label="Lata"
        value={filters.year ?? ''}
        onChange={(e) => onChange({ ...filters, year: e.target.value ? Number(e.target.value) : undefined })}
        className={selectCls(Boolean(filters.year))}
      >
        <option value="">
          Lata {YEARS[0]}–{YEARS.at(-1)}
        </option>
        {YEARS.map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>
    </fieldset>
  )
}
