import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo } from 'react'
import { EmptyState, SkeletonBlock } from '@/components/common/DataState'
import { cn } from '@/lib/cn'
import { fmtInt } from '@/lib/format'
import { signalsQuery } from './api'
import { type MonitoringSearch, useMonitoring } from './context'
import { wojGeoQuery } from './geo'
import { RegionOutline, SignalList } from './parts'

/** Level 0: "Wojewodztwa 16" with the active metric name and a ranked list. */
export function NationalPanel() {
  const { scaled, def, mode, search, setSearch, asOf, filters, wojStale, prefetch } = useMonitoring()
  const found = useQuery({ ...signalsQuery(null, null, search.q, asOf, filters), enabled: Boolean(search.q) })
  const geo = useQuery(wojGeoQuery)
  const byTerc = useMemo(
    () => new Map((geo.data?.features ?? []).map((f) => [f.properties.terc, f])),
    [geo.data],
  )
  const rows = useMemo(
    () =>
      [...scaled].sort(
        (a, b) => (b.value ?? Number.NEGATIVE_INFINITY) - (a.value ?? Number.NEGATIVE_INFINITY),
      ),
    [scaled],
  )
  if (search.q) {
    const items = found.data?.items ?? []
    return (
      <section aria-labelledby="mon-h" className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <h1 id="mon-h" className="t-h2 m-0" data-page-title tabIndex={-1}>
            Wyniki: {search.q}
          </h1>
          <button
            type="button"
            className="t-caption text-text-secondary underline"
            onClick={() => setSearch({ q: undefined })}
          >
            Wyczyść
          </button>
        </div>
        {found.isPending ? (
          <SkeletonBlock className="h-40" />
        ) : items.length === 0 ? (
          <EmptyState>Brak sygnałów dla tego zapytania.</EmptyState>
        ) : (
          <>
            <p className="t-caption m-0 text-text-body-muted">
              Pokazano {items.length} z {found.data?.total} sygnałów, od największego opóźnienia.
            </p>
            <SignalList
              signals={items}
              onHover={prefetch.signal}
              hrefFor={(s) => ({
                to: '/monitoring/$woj/$pow/umowa/$umowa',
                params: { woj: s.teryt.woj, pow: s.teryt.pow, umowa: s.id },
              })}
            />
          </>
        )}
      </section>
    )
  }
  if (scaled.length === 0) return <SkeletonBlock className="h-[480px]" />
  return (
    <section
      aria-labelledby="mon-h"
      aria-busy={wojStale}
      className={cn('flex flex-col gap-3 transition-opacity', wojStale && 'opacity-60')}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h1 id="mon-h" className="t-h2 m-0" data-page-title tabIndex={-1}>
          Województwa <span className="t-mono ml-1 text-muted">{scaled.length}</span>
        </h1>
        <span className="t-caption text-muted">{def.label}</span>
      </div>
      <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
        {rows.map((r) => (
          <li key={r.stat.teryt}>
            <Link
              to="/monitoring/$woj"
              params={{ woj: r.stat.teryt }}
              search={((p: MonitoringSearch) => p) as never}
              onMouseEnter={() => prefetch.woj(r.stat.teryt)}
              onFocus={() => prefetch.woj(r.stat.teryt)}
              className="grid grid-cols-[44px_1fr_auto] items-center gap-3 rounded-item bg-surface px-3 py-2 text-text no-underline hover:bg-soft"
            >
              <RegionOutline feature={byTerc.get(r.stat.teryt)} fill={r.fill} />
              <span className="flex min-w-0 flex-col">
                <span className="t-item flex items-center gap-2">
                  <span className="t-mono text-muted">{r.rank ? String(r.rank).padStart(2, '0') : '--'}</span>
                  {r.stat.name}
                </span>
                <span className="t-caption text-text-body-muted">
                  {mode === 'open'
                    ? `${fmtInt(r.stat.signals)} sygnałów`
                    : `${fmtInt(r.stat.completed)} umów zakończonych`}
                </span>
              </span>
              <span className="text-[20px] font-semibold tracking-tight">
                {r.value === null ? (
                  <span className="text-[13px] text-text-secondary">za mało danych</span>
                ) : (
                  def.fmt(r.value)
                )}
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  )
}
