import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronRight, Download } from 'lucide-react'
import { toast } from 'sonner'
import { ApiError, contractFetch } from '@/api/client'
import { LoginRequired } from '@/auth/LoginRequired'
import { useSession } from '@/auth/session'
import { EmptyState, SkeletonBlock } from '@/components/common/DataState'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { fmtDate } from '@/lib/dates'
import { downloadFile } from '@/lib/download'
import { fmtDays, fmtInt, fmtMoneyShort } from '@/lib/format'
import { contractQuery, regionDetailQuery, signalsCsvUrl, signalsQuery } from './api'
import { type MonitoringSearch, useMonitoring } from './context'
import { KpiTile, SignalList } from './parts'

const keep = ((p: MonitoringSearch) => p) as never

function Crumbs({ items }: { items: { label: string; to: string; params?: Record<string, string> }[] }) {
  return (
    <nav aria-label="Ścieżka" className="flex flex-wrap items-center gap-1.5">
      {items.map((c, i) => (
        <span key={c.label} className="flex items-center gap-1.5">
          <Link
            to={c.to as never}
            params={c.params as never}
            search={keep}
            className="inline-flex min-h-8 items-center rounded-md bg-soft px-2.5 text-[13px] font-medium text-text no-underline hover:bg-soft-2"
          >
            {i === 0 ? '← ' : ''}
            {c.label}
          </Link>
          {i < items.length - 1 ? <span className="text-muted">/</span> : null}
        </span>
      ))}
    </nav>
  )
}

type Crumb = { label: string; to: string; params?: Record<string, string> }

/** A level whose numbers are still on the way: path and title right away, placeholders for the rest. */
function PanelLoading({
  crumbs,
  title,
  small,
}: {
  crumbs: Crumb[]
  title: string | undefined
  small?: boolean
}) {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <Crumbs items={crumbs} />
      {title ? (
        <h1 className={cn(small ? 't-h2' : 't-h1', 'm-0')} data-page-title tabIndex={-1}>
          {title}
        </h1>
      ) : (
        <SkeletonBlock className="h-10 w-2/3" />
      )}
      <div className="grid grid-cols-2 gap-2">
        {[0, 1, 2, 3].map((i) => (
          <SkeletonBlock key={i} className="h-[74px]" />
        ))}
      </div>
      <SkeletonBlock className="h-56" />
    </div>
  )
}

const KPI_LABEL_SHORT = new Set(['late_pct', 'median_delay', 'signals', 'over_pct'])

/** 4.1a: voivodeship. KPIs, powiats with signals, biggest signals, CSV. */
export function RegionPanel({ woj }: { woj: string }) {
  const { asOf, setSearch, filters, regionName, prefetch } = useMonitoring()
  const detail = useQuery(regionDetailQuery(woj, asOf, filters))
  const sig = useQuery(signalsQuery(woj, 'woj', undefined, asOf, filters))
  // the title comes with the map data, so the panel switches together with the map and only the numbers wait
  if (detail.isPending)
    return <PanelLoading crumbs={[{ label: 'Polska', to: '/monitoring' }]} title={regionName(woj)} />
  if (detail.isError || !detail.data) return <EmptyState>Nie znaleziono tego województwa.</EmptyState>
  const d = detail.data
  const kpis = d.kpis.filter((k) => KPI_LABEL_SHORT.has(k.key))
  const kids = [...d.children]
    .filter((c) => c.signals > 0)
    .sort((a, b) => b.signals - a.signals)
    .slice(0, 5)
  return (
    <div
      aria-busy={detail.isPlaceholderData}
      className={cn('flex flex-col gap-4 transition-opacity', detail.isPlaceholderData && 'opacity-60')}
    >
      <Crumbs items={[{ label: 'Polska', to: '/monitoring' }]} />
      <h1 className="t-h1 m-0" data-page-title tabIndex={-1}>
        {d.name}
      </h1>
      <div className="grid grid-cols-2 gap-2">
        {kpis.map((k) => (
          <KpiTile key={k.key} label={k.label} value={k.value} attention={k.attention} />
        ))}
      </div>
      {d.signals_total > 0 ? (
        <Button
          size="lg"
          className="self-start"
          onClick={() => {
            setSearch({ sygnaly: 1 })
            document.getElementById('sygnaly-woj')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }}
        >
          Pokaż umowy: {d.name} →
        </Button>
      ) : null}
      {d.signals_total === 0 ? (
        <EmptyState>W tym województwie nie ma teraz sygnałów.</EmptyState>
      ) : (
        <>
          {kids.length > 0 ? (
            <section className="flex flex-col gap-2">
              <h2 className="t-h3 m-0">
                Powiaty <span className="t-caption font-normal text-muted">z sygnałami na mapie</span>
              </h2>
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {kids.map((c) => (
                  <li key={c.terc}>
                    <Link
                      to="/monitoring/$woj/$pow"
                      params={{ woj, pow: c.terc }}
                      search={keep}
                      onMouseEnter={() => prefetch.pow(c.terc)}
                      onFocus={() => prefetch.pow(c.terc)}
                      className="flex items-center gap-3 rounded-item bg-surface px-3.5 py-2.5 text-text no-underline hover:bg-soft"
                    >
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="t-item">{c.name}</span>
                        <span className="t-caption truncate text-text-body-muted">
                          {c.buyers.slice(0, 3).join(', ')}
                        </span>
                      </span>
                      <span className="t-item">{c.signals}</span>
                      <ChevronRight aria-hidden className="size-4 text-muted" />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <section id="sygnaly-woj" className="flex scroll-mt-2 flex-col gap-2">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="t-h3 m-0">Sygnały</h2>
              <span className="t-caption text-muted">po terminie, bez ogłoszenia o wykonaniu</span>
            </div>
            {sig.data ? (
              <SignalList
                signals={sig.data.items}
                limit={5}
                onHover={prefetch.signal}
                hrefFor={(s) => ({
                  to: '/monitoring/$woj/$pow/umowa/$umowa',
                  params: { woj: s.teryt.woj, pow: s.teryt.pow, umowa: s.id },
                })}
              />
            ) : (
              <SkeletonBlock className="h-40" />
            )}
            <CsvButton
              terc={woj}
              level="woj"
              label={`Pobierz CSV: wszystkie ${fmtInt(d.signals_total)} sygnałów w regionie ${d.name}`}
            />
            <p className="t-caption m-0 text-text-body-muted">{d.note}</p>
          </section>
        </>
      )}
    </div>
  )
}

function CsvButton({ terc, level, label }: { terc: string; level: 'woj' | 'pow'; label: string }) {
  return (
    <Button
      variant="outline"
      aria-label={label}
      className="self-start"
      onClick={async () => {
        try {
          await downloadFile(signalsCsvUrl(terc, level), `sygnaly-${terc}.csv`)
        } catch {
          toast.error('Nie udało się pobrać pliku CSV.')
        }
      }}
    >
      <Download aria-hidden />
      Pobierz CSV
    </Button>
  )
}

/** 4.1b: powiat. KPIs and every signal in it. */
export function PowiatPanel({ woj, pow }: { woj: string; pow: string }) {
  const { asOf, filters, regionName, prefetch } = useMonitoring()
  const detail = useQuery(regionDetailQuery(pow, asOf, filters))
  const sig = useQuery(signalsQuery(pow, 'pow', undefined, asOf, filters))
  const crumbs: Crumb[] = [
    { label: 'Polska', to: '/monitoring' },
    { label: regionName(woj) ?? woj, to: '/monitoring/$woj', params: { woj } },
  ]
  if (detail.isPending || sig.isPending) return <PanelLoading crumbs={crumbs} title={regionName(pow)} />
  if (detail.isError || !detail.data) return <EmptyState>Nie znaleziono tego powiatu.</EmptyState>
  const d = detail.data
  const items = sig.data?.items ?? []
  const maxDays = items.reduce((a, s) => Math.max(a, s.days_late ?? 0), 0)
  const total = items.reduce((a, s) => a + Number(s.value.amount ?? 0), 0)
  const gminas = new Set(items.map((s) => s.teryt.gmi).filter(Boolean)).size
  return (
    <div
      aria-busy={detail.isPlaceholderData || sig.isPlaceholderData}
      className={cn(
        'flex flex-col gap-4 transition-opacity',
        (detail.isPlaceholderData || sig.isPlaceholderData) && 'opacity-60',
      )}
    >
      <Crumbs items={crumbs} />
      <h1 className="t-h1 m-0" data-page-title tabIndex={-1}>
        {d.name}
      </h1>
      <div className="grid grid-cols-2 gap-2">
        <KpiTile label="SYGNAŁY" value={fmtInt(items.length)} attention />
        <KpiTile label="WARTOŚĆ UMÓW" value={fmtMoneyShort(total / 1e6, 'mln')} />
        <KpiTile label="NAJDŁUŻEJ PO TERMINIE" value={fmtDays(maxDays, { short: true })} />
        <KpiTile label="GMINY Z SYGNAŁAMI" value={`${gminas}`} />
      </div>
      {items.length === 0 ? (
        <EmptyState>W tym powiecie nie ma teraz sygnałów.</EmptyState>
      ) : (
        <section className="flex flex-col gap-2">
          <h2 className="t-h3 m-0">Sygnały</h2>
          <SignalList
            signals={items}
            onHover={prefetch.signal}
            hrefFor={(s) => ({
              to: '/monitoring/$woj/$pow/umowa/$umowa',
              params: { woj: s.teryt.woj, pow: s.teryt.pow, umowa: s.id },
            })}
          />
          <CsvButton terc={pow} level="pow" label={`Pobierz CSV: sygnały w ${d.name}`} />
          <p className="t-caption m-0 text-text-body-muted">Kliknij umowę na liście albo na mapie.</p>
        </section>
      )}
    </div>
  )
}

/** Plan bar (days from the contract to the deadline) followed by the overdue stretch. */
export function PlanOverdueBar({
  plan,
  late,
  signedOn,
  plannedEnd,
}: {
  plan: number
  late: number
  signedOn: string | null
  plannedEnd: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="img"
        aria-label={`Plan ${fmtInt(plan)} dni, po terminie ${fmtInt(late)} dni`}
        className="flex h-3 w-full overflow-hidden rounded-pill"
      >
        <span className="bg-ink" style={{ flex: `${plan} 1 0` }} />
        <span className="bg-attention" style={{ flex: `${late} 1 0` }} />
      </div>
      <div className="t-mono flex justify-between text-muted">
        <span>umowa {signedOn ? fmtDate(signedOn) : 'brak'}</span>
        <span>termin {fmtDate(plannedEnd)}</span>
        <span>dziś</span>
      </div>
    </div>
  )
}

/** 4.1c: one investment. */
export function ContractPanel({ woj, pow, id }: { woj: string; pow: string; id: string }) {
  const { readOnly } = useSession()
  const { regionName, signalById } = useMonitoring()
  const q = useQuery(contractQuery(id))
  const wojName = regionName(woj) ?? woj
  const powName = regionName(pow) ?? pow
  const crumbs: Crumb[] = [
    { label: 'Polska', to: '/monitoring' },
    { label: wojName, to: '/monitoring/$woj', params: { woj } },
    { label: powName, to: '/monitoring/$woj/$pow', params: { woj, pow } },
  ]
  const watch = useMutation({
    mutationFn: () =>
      contractFetch('/api/monitoring/watches', { method: 'POST', json: { contract_id: Number(id) } }),
    onSuccess: () => toast.success('Obserwujesz tę umowę.'),
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : 'Nie udało się dodać do obserwowanych.'),
  })
  const report = useMutation({
    mutationFn: () =>
      contractFetch(`/api/monitoring/contracts/${id}/report-case`, { method: 'POST', json: { note: '' } }),
    onSuccess: () => toast.success('Zgłoszone. Sprawa trafiła do Przeglądu.'),
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : 'Nie udało się zgłosić umowy.'),
  })
  if (q.isPending) return <PanelLoading crumbs={crumbs} title={signalById(id)?.object} small />
  if (q.isError || !q.data) return <EmptyState>Nie ma takiej umowy.</EmptyState>
  const c = q.data
  const s = c.signal
  const late = s.days_late
  const plan = c.planned_days ?? 0
  const hasPerformance = c.sources.some((x) => x.k === 'ogłoszenie o wykonaniu' && !x.missing)
  return (
    <div className="flex flex-col gap-4">
      <Crumbs items={crumbs} />
      <h1 className="t-h2 m-0" data-page-title tabIndex={-1}>
        {s.object}
      </h1>
      <p className="t-mono m-0 text-muted">
        {s.buyer}, {powName}, {wojName}
      </p>
      {hasPerformance ? (
        <div role="note" className="rounded-item bg-soft px-4 py-3 text-[14px]">
          Ta umowa ma już ogłoszenie o wykonaniu.{' '}
          <Link to={c.card_href as never} className="font-medium">
            Otwórz kartę umowy
          </Link>
        </div>
      ) : null}
      <div className="grid grid-cols-2 gap-2">
        <KpiTile
          label="PO TERMINIE"
          value={late === null ? 'brak' : fmtDays(late, { short: true })}
          attention={late !== null}
        />
        <KpiTile label="WARTOŚĆ UMOWY" value={fmtMoneyShort(Number(s.value.amount ?? 0) / 1e6, 'mln')} />
        <KpiTile label="OGŁOSZENIA O ZMIANIE" value={fmtInt(s.changes)} />
        <KpiTile label="TERMIN Z UMOWY" value={fmtDate(s.planned_end)} />
      </div>
      {late !== null && plan > 0 ? (
        <PlanOverdueBar plan={plan} late={late} signedOn={s.signed_on} plannedEnd={s.planned_end} />
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button asChild size="lg">
          <Link to={c.card_href as never}>Otwórz kartę umowy</Link>
        </Button>
        {c.can_watch ? (
          <LoginRequired>
            <Button
              variant="outline"
              size="lg"
              onClick={() => watch.mutate()}
              disabled={watch.isPending || readOnly}
              title={readOnly ? 'Konto tylko do odczytu' : undefined}
            >
              Obserwuj
            </Button>
          </LoginRequired>
        ) : null}
        {c.can_report ? (
          <LoginRequired>
            <Button
              variant="outline"
              size="lg"
              onClick={() => report.mutate()}
              disabled={report.isPending || readOnly}
              title={readOnly ? 'Konto tylko do odczytu' : undefined}
            >
              Zgłoś jako przypadek
            </Button>
          </LoginRequired>
        ) : null}
      </div>
      <p className="m-0 text-[15px]">{c.sentence}</p>
      <section className="flex flex-col gap-1.5" aria-label="Źródła">
        <h2 className="t-h3 m-0">Źródła</h2>
        {c.sources.map((x) => (
          <div
            key={x.k}
            className="flex items-baseline justify-between gap-3 rounded-item bg-surface px-3.5 py-2.5"
          >
            <span className="text-[14px] text-text-secondary">{x.k}</span>
            <span className={x.missing ? 't-mono text-attention-text' : 't-mono'}>
              {x.missing ? 'brak' : x.v}
            </span>
          </div>
        ))}
      </section>
    </div>
  )
}
