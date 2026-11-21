import { useIsFetching, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { History, Search } from 'lucide-react'
import {
  type CSSProperties,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { RegionStat, Signal } from '@/api/contracts/monitoring'
import { Input } from '@/components/ui/input'
import { useFeature } from '@/config/features'
import { TimeMachine } from '@/features/replay/TimeMachine'
import { cn } from '@/lib/cn'
import { fmtInt } from '@/lib/format'
import { contractQuery, type MonFilters, regionDetailQuery, regionsQuery, signalsQuery } from './api'
import { ChoroplethMap } from './ChoroplethMap'
import { MonitoringContext, type MonitoringSearch } from './context'
import { gmiGeoQuery, hasWebGL, labelsQuery, powGeoQuery, wojGeoQuery } from './geo'
import {
  colorAt,
  effectiveMetric,
  levelOf,
  METRICS,
  POWIAT_TINT,
  parseMetric,
  scaleRegions,
  signalsInView,
} from './logic'
import { FilterBar, MapToolbar, ModeSwitch } from './parts'

/** Layout of /monitoring: filter bar, left panel (the Outlet) and the persistent map. */
export function MonitoringLayout({ children }: { children: ReactNode }) {
  const params = useParams({ strict: false }) as { woj?: string; pow?: string; umowa?: string }
  const search = useSearch({ from: '/monitoring' }) as MonitoringSearch
  const navigate = useNavigate()
  const level = levelOf(params)
  const mode = search.tryb ?? 'done'
  const metric = effectiveMetric(mode, parseMetric(search.miara))
  const pins = Boolean(search.sygnaly) || mode === 'open'
  const replay = useFeature('monitoring_replay')
  // Wehikuł czasu opens on demand under the map, so the map keeps the viewport
  const [replayOpen, setReplayOpen] = useState(false)
  const [asOfRaw, setAsOf] = useState<string | null>(null)
  // replay steps can arrive faster than the API answers: only the settled date drives the queries
  const [asOf, setAsOfSettled] = useState<string | null>(null)
  useEffect(() => {
    const t = setTimeout(() => setAsOfSettled(asOfRaw), 350)
    return () => clearTimeout(t)
  }, [asOfRaw])
  const filters: MonFilters = useMemo(
    () => ({ subsector: search.podsektor, value: search.wartosc, year: search.rok }),
    [search.podsektor, search.wartosc, search.rok],
  )
  // the map view fills the viewport under the app header (no page scroll on desktop); the panels scroll inside
  const shell = useRef<HTMLDivElement>(null)
  const [top, setTop] = useState(70)
  useLayoutEffect(() => {
    const measure = () => {
      const el = shell.current
      if (el) setTop(Math.round(el.getBoundingClientRect().top + window.scrollY))
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])
  const [qDraft, setQDraft] = useState(search.q ?? '')
  useEffect(() => setQDraft(search.q ?? ''), [search.q])

  const setSearch = useCallback(
    (patch: Partial<MonitoringSearch>) =>
      navigate({
        to: '.',
        search: ((prev: MonitoringSearch) => ({ ...prev, ...patch })) as never,
        replace: true,
      }),
    [navigate],
  )

  const woj = useQuery(regionsQuery('woj', undefined, asOf, filters))
  const wojGeo = useQuery(wojGeoQuery)
  const powRegions = useQuery({ ...regionsQuery('pow', params.woj, asOf, filters), enabled: level >= 1 })
  const gmiRegions = useQuery({ ...regionsQuery('gmi', params.pow, asOf, filters), enabled: level >= 2 })
  const powGeoNames = useMemo(
    () => new Map((powRegions.data?.items ?? []).map((r) => [r.teryt, r.name])),
    [powRegions.data],
  )

  // signals: whole country (top 500) at level 0 when pins are on; the voivodeship at level 1; the powiat at levels 2-3
  const sigScope =
    level >= 2
      ? { terc: params.pow as string, lvl: 'pow' as const }
      : level === 1
        ? { terc: params.woj as string, lvl: 'woj' as const }
        : { terc: null, lvl: null }
  const signals = useQuery({
    ...signalsQuery(sigScope.terc, sigScope.lvl, search.q, asOf, filters),
    enabled: level >= 1 || pins || Boolean(search.q),
  })
  const inView: Signal[] = useMemo(
    () => signalsInView(signals.data?.items ?? [], params),
    [signals.data, params],
  )

  const def = METRICS[metric]
  const scaled = useMemo(() => scaleRegions(woj.data?.items ?? [], metric, mode), [woj.data, metric, mode])

  const powCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of powRegions.data?.items ?? []) if (r.signals > 0) m.set(r.teryt, r.signals)
    return m
  }, [powRegions.data])
  const gmiCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of gmiRegions.data?.items ?? []) if (r.signals > 0) m.set(r.teryt, r.signals)
    return m
  }, [gmiRegions.data])
  const gmiNames = useMemo(
    () => new Map((gmiRegions.data?.items ?? []).map((r: RegionStat) => [r.teryt, r.name])),
    [gmiRegions.data],
  )

  // names and signals the map already has, so a panel can title itself before its own request lands
  const regionName = useCallback(
    (terc: string) =>
      terc.length === 2
        ? woj.data?.items.find((r) => r.teryt === terc)?.name
        : (powGeoNames.get(terc) ?? gmiNames.get(terc)),
    [woj.data, powGeoNames, gmiNames],
  )
  const signalById = useCallback((id: string) => signals.data?.items.find((s) => s.id === id), [signals.data])

  // hover intent prefetches everything the next level reads (the API needs ~0.5-1.2 s per call)
  const qc = useQueryClient()
  const prefetch = useMemo(() => {
    const seen = new Set<string>()
    const once = (key: string, run: () => void) => {
      if (seen.has(key)) return
      seen.add(key)
      run()
    }
    const pow = (terc: string) =>
      once(`p${terc}|${asOf}|${JSON.stringify(filters)}`, () => {
        qc.prefetchQuery(regionDetailQuery(terc, asOf, filters))
        qc.prefetchQuery(signalsQuery(terc, 'pow', undefined, asOf, filters))
        qc.prefetchQuery(regionsQuery('gmi', terc, asOf, filters))
        qc.prefetchQuery(gmiGeoQuery(terc))
        qc.prefetchQuery(labelsQuery('gmi-centroids'))
      })
    return {
      woj: (terc: string) =>
        once(`w${terc}|${asOf}|${JSON.stringify(filters)}`, () => {
          qc.prefetchQuery(regionDetailQuery(terc, asOf, filters))
          qc.prefetchQuery(signalsQuery(terc, 'woj', undefined, asOf, filters))
          qc.prefetchQuery(regionsQuery('pow', terc, asOf, filters))
          qc.prefetchQuery(powGeoQuery(terc))
          qc.prefetchQuery(labelsQuery('pow-centroids'))
        }),
      pow,
      signal: (s: Signal) =>
        once(`s${s.id}`, () => {
          qc.prefetchQuery(contractQuery(s.id))
          if (s.teryt.pow !== params.pow) pow(s.teryt.pow)
        }),
    }
  }, [qc, asOf, filters, params.pow])
  // only requests something on screen waits for (prefetches do not count)
  const fetching =
    useIsFetching({ queryKey: ['monitoring'], predicate: (q) => q.getObserversCount() > 0 }) > 0
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!fetching) return setBusy(false)
    const t = setTimeout(() => setBusy(true), 250)
    return () => clearTimeout(t)
  }, [fetching])

  const target = { level, woj: params.woj, pow: params.pow, signalId: params.umowa }
  const goWoj = (terc: string) =>
    navigate({ to: '/monitoring/$woj', params: { woj: terc }, search: ((p: MonitoringSearch) => p) as never })
  const goPow = (terc: string) =>
    navigate({
      to: '/monitoring/$woj/$pow',
      params: { woj: terc.slice(0, 2), pow: terc },
      search: ((p: MonitoringSearch) => p) as never,
    })
  const goSignal = (s: Signal) =>
    navigate({
      to: '/monitoring/$woj/$pow/umowa/$umowa',
      params: { woj: s.teryt.woj, pow: s.teryt.pow, umowa: s.id },
      search: ((p: MonitoringSearch) => p) as never,
    })
  const up = () => {
    if (level === 3)
      navigate({
        to: '/monitoring/$woj/$pow',
        params: { woj: params.woj as string, pow: params.pow as string },
        search: ((p: MonitoringSearch) => p) as never,
      })
    else if (level === 2) goWoj(params.woj as string)
    else if (level === 1) navigate({ to: '/monitoring', search: ((p: MonitoringSearch) => p) as never })
  }

  const totalLabel =
    mode === 'open'
      ? `${fmtInt((woj.data?.items ?? []).reduce((a, r) => a + r.signals, 0))} umów po terminie, bez ogłoszenia o wykonaniu`
      : (woj.data?.total_label ?? '')
  const shownPins = inView.filter((s) => s.lon !== null).length
  const gl = useMemo(() => hasWebGL(), [])

  return (
    <MonitoringContext.Provider
      value={{
        asOf,
        mode,
        metric,
        def,
        wojRegions: woj.data,
        scaled: scaled.regions,
        wojGeo: wojGeo.data,
        pins,
        search,
        filters,
        setSearch,
        wojStale: woj.isPlaceholderData,
        regionName,
        signalById,
        prefetch,
      }}
    >
      <div
        ref={shell}
        style={{ '--mon-h': `calc(100dvh - ${top}px)` } as CSSProperties}
        className="mx-auto flex w-full max-w-[1480px] flex-col gap-3 px-6 pt-4 pb-3 lg:h-(--mon-h) lg:min-h-[560px]"
      >
        <div className="flex flex-wrap items-center gap-3">
          <ModeSwitch
            mode={mode}
            onChange={(m) =>
              setSearch({ tryb: m === 'done' ? undefined : m, sygnaly: m === 'open' ? 1 : search.sygnaly })
            }
          />
          {/* biome-ignore lint/a11y/noLabelWithoutControl: the Input component renders the control */}
          <label className="relative min-w-[260px] flex-1">
            <span className="sr-only">Szukaj sygnału</span>
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted"
            />
            <Input
              type="search"
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && setSearch({ q: qDraft.trim() || undefined })}
              onBlur={() => qDraft !== (search.q ?? '') && setSearch({ q: qDraft.trim() || undefined })}
              placeholder="Szukaj: gmina, zamawiający, wykonawca, numer BZP"
              className="h-10 w-full pl-10"
            />
          </label>
          <FilterBar
            filters={filters}
            onChange={(f) => setSearch({ podsektor: f.subsector, wartosc: f.value, rok: f.year })}
          />
          {replay ? (
            <button
              type="button"
              aria-expanded={replayOpen}
              onClick={() => {
                if (replayOpen) setAsOf(null)
                setReplayOpen((o) => !o)
              }}
              className={cn(
                'inline-flex h-10 items-center gap-2 rounded-inner border px-3 text-[14px] font-medium',
                replayOpen ? 'border-ink bg-ink text-on-ink' : 'border-border bg-surface hover:bg-soft',
              )}
            >
              <History aria-hidden className="size-4" />
              Wehikuł czasu
            </button>
          ) : null}
          <span className="t-caption ml-auto text-text-body-muted">{totalLabel}</span>
        </div>

        <div className="grid items-stretch gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(340px,420px)_1fr]">
          <div className="min-h-0 overflow-y-auto pr-1 lg:h-full">{children}</div>
          <div className="relative h-[60vh] min-h-[420px] lg:h-full lg:min-h-0">
            {gl ? (
              <ChoroplethMap
                target={target}
                mode={mode}
                regions={scaled.regions}
                powCounts={powCounts}
                gmiCounts={gmiCounts}
                powReady={
                  Boolean(powRegions.data) && powRegions.data?.items[0]?.teryt.slice(0, 2) === params.woj
                }
                powNames={powGeoNames}
                gmiNames={gmiNames}
                signals={inView}
                showPins={pins}
                fmt={def.fmt}
                onSelectWoj={goWoj}
                onSelectPow={goPow}
                onSelectSignal={goSignal}
                prefetch={prefetch}
                onUp={up}
              />
            ) : (
              <div className="grid h-full place-items-center rounded-card bg-soft p-6 text-center text-[14px] text-text-body-muted">
                Mapa wymaga WebGL. Lista po lewej działa bez niej.
              </div>
            )}
            {busy ? (
              <div
                role="status"
                className="pointer-events-none absolute top-3 left-3 rounded-pill bg-surface/95 px-3 py-1.5 text-[13px] text-text-secondary shadow-sm animate-in fade-in"
              >
                Wczytujemy dane…
              </div>
            ) : null}
            <MapToolbar
              level={level}
              mode={mode}
              metric={metric}
              onMetric={(m) => setSearch({ miara: m === 'late' ? undefined : m })}
              legend={{
                lo: def.fmt(scaled.lo),
                hi: def.fmt(scaled.hi),
                gradient: `linear-gradient(90deg, ${colorAt(0, mode)}, ${colorAt(0.5, mode)}, ${colorAt(1, mode)})`,
                tints: POWIAT_TINT,
              }}
              pins={pins}
              onPins={() => setSearch({ sygnaly: pins ? undefined : 1 })}
              pinsLabel={`${pins ? 'Sygnały na mapie' : 'Pokaż sygnały'}: ${level === 0 && !signals.data ? '…' : fmtInt(shownPins || inView.length)}`}
              pinsDisabled={signals.isError}
            />
          </div>
        </div>
        {replay && replayOpen ? (
          <div className="shrink-0 overflow-y-auto lg:max-h-[42%]">
            <TimeMachine terc={sigScope.terc} level={sigScope.lvl} onAsOf={setAsOf} />
          </div>
        ) : null}
      </div>
    </MonitoringContext.Provider>
  )
}
