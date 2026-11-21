import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { Search } from 'lucide-react'
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import type { RegionStat, Signal } from '@/api/contracts/monitoring'
import { Page } from '@/app/Page'
import { Input } from '@/components/ui/input'
import { useFeature } from '@/config/features'
import { TimeMachine } from '@/features/replay/TimeMachine'
import { fmtInt } from '@/lib/format'
import { regionsQuery, signalsQuery } from './api'
import { ChoroplethMap } from './ChoroplethMap'
import { MonitoringContext, type MonitoringSearch } from './context'
import { hasWebGL, wojGeoQuery } from './geo'
import { colorAt, effectiveMetric, levelOf, METRICS, parseMetric, scaleRegions, signalsInView } from './logic'
import { MapToolbar, ModeSwitch } from './parts'

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
  const [asOfRaw, setAsOf] = useState<string | null>(null)
  // replay steps can arrive faster than the API answers: only the settled date drives the queries
  const [asOf, setAsOfSettled] = useState<string | null>(null)
  useEffect(() => {
    const t = setTimeout(() => setAsOfSettled(asOfRaw), 350)
    return () => clearTimeout(t)
  }, [asOfRaw])
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

  const woj = useQuery(regionsQuery('woj', undefined, asOf))
  const wojGeo = useQuery(wojGeoQuery)
  const powRegions = useQuery({ ...regionsQuery('pow', params.woj, asOf), enabled: level >= 1 })
  const gmiRegions = useQuery({ ...regionsQuery('gmi', params.pow, asOf), enabled: level >= 2 })
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
    ...signalsQuery(sigScope.terc, sigScope.lvl, search.q, asOf),
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
        setSearch,
      }}
    >
      <Page className="max-w-[1480px] gap-4 pt-5 pb-8">
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
          <span className="t-caption text-text-body-muted">{totalLabel}</span>
        </div>

        <div className="grid items-stretch gap-4 lg:h-[820px] lg:grid-cols-[minmax(340px,420px)_1fr]">
          <div className="min-h-0 overflow-y-auto pr-1 lg:h-full">{children}</div>
          <div className="relative h-[60vh] min-h-[420px] lg:h-full">
            {gl ? (
              <ChoroplethMap
                target={target}
                mode={mode}
                regions={scaled.regions}
                powCounts={powCounts}
                gmiCounts={gmiCounts}
                powNames={powGeoNames}
                gmiNames={gmiNames}
                signals={inView}
                showPins={pins}
                fmt={def.fmt}
                onSelectWoj={goWoj}
                onSelectPow={goPow}
                onSelectSignal={goSignal}
                onUp={up}
              />
            ) : (
              <div className="grid h-full place-items-center rounded-card bg-soft p-6 text-center text-[14px] text-text-body-muted">
                Mapa wymaga WebGL. Lista po lewej działa bez niej.
              </div>
            )}
            <MapToolbar
              mode={mode}
              metric={metric}
              onMetric={(m) => setSearch({ miara: m === 'late' ? undefined : m })}
              legend={{
                lo: def.fmt(scaled.lo),
                hi: def.fmt(scaled.hi),
                gradient: `linear-gradient(90deg, ${colorAt(0, mode)}, ${colorAt(1, mode)})`,
              }}
              pins={pins}
              onPins={() => setSearch({ sygnaly: pins ? undefined : 1 })}
              pinsLabel={`${pins ? 'Sygnały na mapie' : 'Pokaż sygnały'}: ${level === 0 && !signals.data ? '…' : fmtInt(shownPins || inView.length)}`}
              pinsDisabled={signals.isError}
            />
          </div>
        </div>
        {replay ? <TimeMachine terc={sigScope.terc} level={sigScope.lvl} onAsOf={setAsOf} /> : null}
        <p className="t-caption m-0 text-muted">
          Granice: PRG, uproszczone. Umowy wod-kan z BZP, 2021–2026. Brak ogłoszenia o wykonaniu to sygnał,
          nie dowód opóźnienia.
        </p>
      </Page>
    </MonitoringContext.Provider>
  )
}
