import { keepPreviousData, queryOptions, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pause, Play, RotateCcw } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { adaptSignals, type RealSignals } from '@/api/adapters/monitoring'
import { contractFetch } from '@/api/client'
import type { RegionLevel, SignalsOut } from '@/api/contracts/monitoring'
import { ProvenanceTag } from '@/components/common/ProvenanceTag'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { fmtDate } from '@/lib/dates'
import { fmtInt, fmtPlnAuto } from '@/lib/format'
import { daysBetween, deltaLabel, monthLabel, monthSteps, newInStep } from './logic'

export const replayQuery = (asOf: string, terc?: string | null, level?: RegionLevel | null) =>
  queryOptions({
    queryKey: ['monitoring', 'replay', asOf, terc ?? null, level ?? null],
    queryFn: async (): Promise<SignalsOut> =>
      adaptSignals(
        await contractFetch<RealSignals>('/api/monitoring/signals', {
          query: {
            as_of: asOf,
            sort: 'days_overdue',
            limit: 60,
            terc: terc ?? undefined,
            level: level ?? undefined,
          },
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
  })

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/**
 * Monitoring time machine (W6): a month slider that replays the BZP notices up to each date. Every step shows how
 * many contracts were past their planned end without a performance notice on that day, and which ones just crossed
 * it ("nowe sygnały"). Self-contained; `onAsOf` lets the map replay too.
 */
export function TimeMachine({
  terc,
  level,
  onAsOf,
  from = '2023-01',
  today = todayIso(),
  stepMs = 1400,
  debounceMs = 300,
}: {
  terc?: string | null
  level?: RegionLevel | null
  onAsOf?: (d: string | null) => void
  from?: string
  today?: string
  stepMs?: number
  debounceMs?: number
}) {
  const steps = useMemo(() => monthSteps(from, today), [from, today])
  const [i, setI] = useState(steps.length - 1)
  const [playing, setPlaying] = useState(false)
  const reduced = useRef(prefersReducedMotion())
  const qc = useQueryClient()
  // the slider label moves at once; the step that drives the requests follows 300 ms after the last move,
  // so holding an arrow key sends one request instead of one per month
  const [qi, setQi] = useState(i)
  useEffect(() => {
    if (qi === i) return
    const t = setTimeout(() => setQi(i), playing ? 0 : debounceMs)
    return () => clearTimeout(t)
  }, [i, qi, playing, debounceMs])
  const asOf = steps[i]
  const qAsOf = steps[qi]
  const prevAsOf = steps[Math.max(0, qi - 1)]
  const settled = qi === i
  const cur = useQuery({ ...replayQuery(qAsOf, terc, level), placeholderData: keepPreviousData })
  const prev = useQuery({ ...replayQuery(prevAsOf, terc, level), enabled: qi > 0 && settled })

  useEffect(() => {
    onAsOf?.(qi === steps.length - 1 && !playing ? null : qAsOf)
  }, [qAsOf, qi, playing, steps.length, onAsOf])

  // prefetch the next step while playing
  useEffect(() => {
    if (playing && i + 1 < steps.length) void qc.prefetchQuery(replayQuery(steps[i + 1], terc, level))
  }, [playing, i, steps, qc, terc, level])

  useEffect(() => {
    if (!playing) return
    if (i >= steps.length - 1) {
      setPlaying(false)
      return
    }
    const t = setTimeout(() => setI((x) => Math.min(x + 1, steps.length - 1)), stepMs)
    return () => clearTimeout(t)
  }, [playing, i, steps.length, stepMs])

  const stepDays = qi > 0 ? daysBetween(prevAsOf, qAsOf) : 31
  // never show numbers of another date: while the step loads (or the slider is still moving) show "liczę…"
  const loading = !settled || cur.isPending || cur.isPlaceholderData
  const data = loading ? undefined : cur.data
  const fresh = data ? newInStep(data.items, stepDays) : []
  const total = data?.total ?? null
  const delta = qi > 0 && !loading && !prev.isPending ? deltaLabel(total, prev.data?.total ?? null) : ''

  return (
    <section
      aria-labelledby="tm-h"
      className="flex flex-col gap-3 rounded-panel border border-divider bg-surface p-4"
      data-testid="time-machine"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="tm-h" className="t-h3 m-0">
          Wehikuł czasu
        </h2>
        <span className="t-caption text-muted">odtwarza ogłoszenia z BZP opublikowane do wybranego dnia</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="icon-sm"
          aria-label={playing ? 'Zatrzymaj' : 'Odtwórz'}
          onClick={() => {
            if (!playing && i >= steps.length - 1) setI(0)
            setPlaying((p) => !p)
          }}
        >
          {playing ? <Pause aria-hidden /> : <Play aria-hidden />}
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="Wróć do dziś"
          onClick={() => {
            setPlaying(false)
            setI(steps.length - 1)
          }}
        >
          <RotateCcw aria-hidden />
        </Button>
        <input
          type="range"
          min={0}
          max={steps.length - 1}
          step={1}
          value={i}
          onChange={(e) => {
            setPlaying(false)
            setI(Number(e.target.value))
          }}
          aria-label="Data, do której odtwarzamy ogłoszenia"
          aria-valuetext={fmtDate(asOf)}
          className="min-w-[180px] flex-1 accent-[var(--ink)]"
        />
        <span className="t-mono w-[110px] text-right" aria-live="polite">
          {fmtDate(asOf)}
          {loading ? <span className="block text-muted">liczę…</span> : null}
        </span>
      </div>
      <div className="t-mono flex justify-between text-muted">
        <span>{monthLabel(steps[0])}</span>
        <span>dziś</span>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="t-small text-text-body-muted">Sygnały na ten dzień:</span>
        <span className="t-stat" data-testid="tm-total">
          {total === null ? '…' : fmtInt(total)}
        </span>
        {delta ? (
          <span className={cn('t-mono', delta.startsWith('+') ? 'text-attention-text' : 'text-muted')}>
            {delta} od {fmtDate(prevAsOf)}
          </span>
        ) : null}
      </div>
      {fresh.length ? (
        <ul
          className="m-0 flex max-h-[260px] list-none flex-col gap-1.5 overflow-y-auto p-0"
          aria-label="Nowe sygnały w tym kroku"
          // biome-ignore lint/a11y/noNoninteractiveTabindex: scrollable list must be keyboard-scrollable (axe scrollable-region-focusable)
          tabIndex={0}
          data-testid="tm-new"
        >
          {fresh.slice(0, 12).map((s) => (
            <li
              key={`${qAsOf}-${s.id}`}
              className={cn(
                'flex items-start justify-between gap-3 rounded-item bg-attention-soft px-3 py-2',
                !reduced.current && 'animate-in fade-in slide-in-from-left-2 duration-500',
              )}
            >
              <span className="flex min-w-0 flex-col">
                <span className="t-small line-clamp-1 font-medium">{s.object}</span>
                <span className="t-mono text-muted">
                  {s.buyer}, {s.bzp}
                </span>
              </span>
              <span className="t-mono shrink-0 text-right">
                <span className="block text-attention-text">koniec {fmtDate(s.planned_end)}</span>
                <span className="block text-muted">{fmtPlnAuto(s.value.amount)}</span>
              </span>
            </li>
          ))}
          {fresh.length > 12 ? <li className="t-mono text-muted">i {fresh.length - 12} kolejnych</li> : null}
        </ul>
      ) : loading ? (
        <p className="t-small m-0 text-muted" role="status">
          Wczytujemy stan na {fmtDate(asOf)}…
        </p>
      ) : data ? (
        <p className="t-small m-0 text-muted">
          W tym kroku żadna umowa nie przekroczyła planowanego terminu.
        </p>
      ) : null}
      <ProvenanceTag
        origin="CALC"
        text="sygnał = umowa po planowanym terminie bez ogłoszenia o wykonaniu na ten dzień; sygnał, nie dowód"
      />
    </section>
  )
}
