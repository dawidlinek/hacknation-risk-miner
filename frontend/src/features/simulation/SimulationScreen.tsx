import { useMutation, useSuspenseQuery } from '@tanstack/react-query'
import { MessageSquare, Send } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { ApiError } from '@/api/client'
import type { Metric, SimMarker, SimOption, SimulationOut } from '@/api/contracts/simulation'
import { Panel, TwoCol } from '@/app/Page'
import { EmptyState } from '@/components/common/DataState'
import { ProvenanceTag } from '@/components/common/ProvenanceTag'
import { SummaryCard } from '@/components/common/SummaryCard'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/cn'
import { fmtInt } from '@/lib/format'
import { askAnalysis, simulationQuery } from './api'
import { ScenarioLines } from './ScenarioLines'
import {
  affects,
  buildLines,
  chartAria,
  effectLine,
  type Kpi,
  kpis,
  METRIC_TAB,
  SCENARIO_COLORS,
  type SimulationResponse,
  subsetKey,
  summarySentence,
} from './scenario'

export interface SimulationScreenProps {
  id: string
  metric: Metric
  checked: string[]
  onMetric: (m: Metric) => void
  onChecked: (keys: string[]) => void
}

export function SimulationScreen(props: SimulationScreenProps) {
  const { data } = useSuspenseQuery(simulationQuery(props.id))
  return (
    <div className="flex flex-col gap-7">
      <SimulationBody sim={data} {...props} />
    </div>
  )
}

export function SimulationBody({
  sim,
  id,
  metric,
  checked,
  onMetric,
  onChecked,
}: SimulationScreenProps & { sim: SimulationResponse }) {
  const [late2, setLate2] = useState(false)
  if (sim.insufficient || !sim.metrics?.time) {
    return (
      <EmptyState>
        {sim.message ??
          `Za mało podobnych umów, żeby symulować (n = ${fmtInt(sim.n)}). Pokazujemy tylko zakresy z raportu.`}
      </EmptyState>
    )
  }
  const m = sim.metrics[metric]
  const { lines, missing } = buildLines(sim, metric, checked)
  const late2What = sim.whatifs.find((w) => w.key === 'late2')
  const extra: SimMarker[] =
    metric === 'time' && late2 && late2What?.action.kind === 'marker'
      ? [{ x: late2What.action.x, label: late2What.action.label, tone: 'attention' }]
      : []
  const toggle = (key: string) =>
    onChecked(checked.includes(key) ? checked.filter((k) => k !== key) : [...checked, key])
  return (
    <TwoCol
      main={
        <>
          <SummaryCard
            eyebrow="Co jeśli"
            sentence={summarySentence(sim, metric, checked)}
            provenance={`obliczenie, ${fmtInt(sim.runs)} losowań, n = ${fmtInt(sim.n)}, szablon (bez AI)`}
          />
          <section aria-labelledby="sim-chart" className="flex flex-col gap-4 rounded-panel bg-soft p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="sim-chart" className="t-h3 m-0">
                {m.title}
              </h2>
              <MetricSwitch metric={metric} onMetric={onMetric} />
            </div>
            <ScenarioLines
              metric={metric}
              m={m}
              lines={lines}
              extraMarkers={extra}
              aria={chartAria(sim, metric, checked)}
            />
            {missing.length ? (
              <p className="t-caption m-0 text-muted">brak obliczenia dla tej kombinacji</p>
            ) : null}
            <KpiRow items={kpis(sim, metric, checked, { late2 })} />
            <ProvenanceTag
              origin="CALC"
              text={metricBasis(metric, (m as { n?: number }).n ?? sim.n, sim.n)}
            />
          </section>
          <Toggles sim={sim} metric={metric} checked={checked} onToggle={toggle} />
        </>
      }
      aside={
        <>
          <WhatIfPanel
            id={id}
            sim={sim}
            metric={metric}
            checked={checked}
            late2={late2}
            onLate2={(v) => {
              setLate2(v)
              if (v) onMetric('time')
            }}
            onMetric={onMetric}
          />
          <Drivers sim={sim} metric={metric} checked={checked} />
          <MethodNote sim={sim} />
        </>
      }
    />
  )
}

/** Which contracts feed the curve: the class (n) minus those without complete dates or amounts. */
export function metricBasis(metric: Metric, nMetric: number, nClass: number): string {
  if (metric === 'comp') return `symulacja, ${fmtInt(nMetric)} przetargów z ostatnich 24 mies.`
  const what = metric === 'time' ? 'pełnymi terminami' : 'pełnymi kwotami'
  return nMetric === nClass
    ? `symulacja, n = ${fmtInt(nClass)}`
    : `symulacja, ${fmtInt(nMetric)} z ${fmtInt(nClass)} umów (z ${what})`
}

function MetricSwitch({ metric, onMetric }: { metric: Metric; onMetric: (m: Metric) => void }) {
  return (
    <div role="tablist" aria-label="Co pokazać" className="flex gap-1 rounded-pill bg-surface p-1">
      {(['time', 'cost', 'comp'] as Metric[]).map((k) => (
        <button
          key={k}
          type="button"
          role="tab"
          aria-selected={metric === k}
          onClick={() => onMetric(k)}
          className={cn(
            'min-h-[34px] rounded-pill px-4 text-[14px] font-medium',
            metric === k ? 'bg-ink text-on-ink' : 'text-text-secondary hover:text-text',
          )}
        >
          {METRIC_TAB[k]}
        </button>
      ))}
    </div>
  )
}

const TONE: Record<Kpi['tone'], string> = {
  good: 'text-success-text',
  bad: 'text-attention-text',
  muted: 'text-muted',
  none: 'text-muted',
}

export function KpiRow({ items }: { items: Kpi[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="kpi-row">
      {items.map((k) => (
        <div key={k.label} className="flex flex-col gap-1 rounded-item bg-surface px-3.5 py-3">
          <span className="t-caption text-text-body-muted">{k.label}</span>
          <span className="flex flex-wrap items-baseline gap-2">
            <span className={cn('t-stat', k.attention && 'text-attention-text')}>{k.value}</span>
            {k.delta ? <span className={cn('t-mono', TONE[k.tone])}>{k.delta}</span> : null}
          </span>
        </div>
      ))}
    </div>
  )
}

function Toggles({
  sim,
  metric,
  checked,
  onToggle,
}: {
  sim: SimulationOut
  metric: Metric
  checked: string[]
  onToggle: (key: string) => void
}) {
  return (
    <section aria-labelledby="sim-toggles" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="sim-toggles" className="t-h3 m-0">
          Co możesz zmienić przed przetargiem
        </h2>
        <span className="t-caption text-muted">każda zaznaczona zmiana rysuje własną linię</span>
      </div>
      {sim.options.map((o, i) => (
        <ToggleRow
          key={o.key}
          o={o}
          color={SCENARIO_COLORS[i % 4]}
          metric={metric}
          checked={checked.includes(o.key)}
          onToggle={onToggle}
        />
      ))}
    </section>
  )
}

function ToggleRow({
  o,
  color,
  metric,
  checked,
  onToggle,
}: {
  o: SimOption
  color: string
  metric: Metric
  checked: boolean
  onToggle: (key: string) => void
}) {
  const on = affects(o, metric)
  const id = `opt-${o.key}`
  const review = (o as SimOption & { status?: string }).status === 'approved' ? 'approved' : 'proposed'
  return (
    <label
      htmlFor={id}
      className="flex cursor-pointer items-start gap-3 rounded-item bg-surface px-4 py-3 hover:bg-soft-2"
    >
      <Checkbox id={id} checked={checked} onCheckedChange={() => onToggle(o.key)} className="mt-0.5" />
      <span
        aria-hidden
        className="mt-1 h-3 w-5 shrink-0 rounded-chip"
        style={{ background: on ? color : 'var(--border)' }}
      />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="t-item">{o.label}</span>
        <span className="t-small text-text-body-muted">{o.detail}</span>
        <ProvenanceTag
          origin="SOURCE"
          label="założenie eksperta"
          text={review === 'approved' ? 'zatwierdzone' : 'do zatwierdzenia'}
        />
      </span>
      <span className={cn('t-mono shrink-0 text-right', on ? 'text-text-body-muted' : 'text-muted')}>
        {effectLine(o, metric)}
      </span>
    </label>
  )
}

function WhatIfPanel({
  id,
  sim,
  metric,
  checked,
  late2,
  onLate2,
  onMetric,
}: {
  id: string
  sim: SimulationOut
  metric: Metric
  checked: string[]
  late2: boolean
  onLate2: (v: boolean) => void
  onMetric: (m: Metric) => void
}) {
  const [q, setQ] = useState(sim.whatifs[0]?.key ?? 'late2')
  const [text, setText] = useState('')
  const chat = useMutation({ mutationFn: (msg: string) => askAnalysis(id, msg, metric, checked) })
  const w = sim.whatifs.find((x) => x.key === q) ?? sim.whatifs[0]
  if (!w) return null
  const key = subsetKey(sim.options, checked)
  const answer = w.answer_by_subset[key] ?? w.answer_by_subset[''] ?? ''
  const active = w.key === 'late2' ? late2 : w.action.kind === 'metric' && metric === w.action.metric
  const act = () => {
    if (w.action.kind === 'marker') onLate2(!late2)
    else onMetric(w.action.metric)
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (text.trim().length >= 3) chat.mutate(text.trim())
  }
  return (
    <Panel
      aria-labelledby="sim-ask"
      className="rounded-[22px] border border-divider bg-surface shadow-composer"
    >
      <div className="flex items-center gap-2">
        <MessageSquare className="size-4" aria-hidden />
        <h2 id="sim-ask" className="t-h3 m-0">
          Zapytaj: co jeśli
        </h2>
      </div>
      <div className="self-end rounded-item bg-ink px-4 py-2.5 text-on-ink t-small">{w.question}</div>
      <div className="flex flex-col gap-2 rounded-item bg-soft px-4 py-3">
        <p className="t-small m-0">{answer}</p>
        <ProvenanceTag origin="CALC" text={w.provenance.replace(/^obliczenie, /, '')} />
        <Button
          variant={active ? 'default' : 'outline'}
          size="sm"
          className="self-start"
          aria-pressed={active}
          onClick={act}
        >
          {active && w.cta_active ? w.cta_active : w.cta}
        </Button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {sim.whatifs
          .filter((x) => x.key !== w.key)
          .map((x) => (
            <Button
              key={x.key}
              variant="outline"
              size="sm"
              className="h-auto whitespace-normal py-1.5 text-left"
              onClick={() => setQ(x.key)}
            >
              {x.question}
            </Button>
          ))}
      </div>
      <form
        onSubmit={submit}
        className="flex items-center gap-2 rounded-pill border border-border bg-surface py-1 pr-1 pl-4"
      >
        <label htmlFor="sim-q" className="sr-only">
          Pytanie co jeśli
        </label>
        <input
          id="sim-q"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Co jeśli…"
          className="min-w-0 flex-1 bg-transparent text-[14px] outline-none"
        />
        <Button type="submit" size="icon-sm" aria-label="Wyślij" disabled={chat.isPending}>
          <Send aria-hidden />
        </Button>
      </form>
      {chat.isPending ? <p className="t-caption m-0 text-muted">Liczymy odpowiedź…</p> : null}
      {chat.data ? (
        <div className="flex flex-col gap-1 rounded-item bg-soft px-4 py-3">
          <p className="t-small m-0">{chat.data.text}</p>
          <ProvenanceTag origin="AI" reviewStatus="proposed" label={chat.data.role_label ?? 'wniosek AI'} />
        </div>
      ) : null}
      {chat.isError ? (
        <p className="t-caption m-0 text-attention-text">
          {chat.error instanceof ApiError && chat.error.status === 503
            ? 'Czat jest chwilowo niedostępny. Gotowe pytania powyżej działają.'
            : 'Nie udało się odpowiedzieć.'}
        </p>
      ) : null}
    </Panel>
  )
}

function Drivers({ sim, metric, checked }: { sim: SimulationOut; metric: Metric; checked: string[] }) {
  const m = sim.metrics[metric]
  const d = m.drivers[subsetKey(sim.options, checked)] ?? m.drivers['']
  if (!d) return null
  return (
    <Panel aria-labelledby="sim-drivers">
      <h2 id="sim-drivers" className="t-h3 m-0">
        {d.title}
      </h2>
      <span className="t-caption text-muted">{d.desc}</span>
      <HBarList rows={d.rows} />
      <ProvenanceTag origin="CALC" text={d.provenance.replace(/^obliczenie, /, '')} />
    </Panel>
  )
}

export function HBarList({ rows }: { rows: { label: string; value: number; display: string }[] }) {
  const max = Math.max(...rows.map((r) => r.value), 0) || 1
  if (!rows.length) return <EmptyState>Brak ryzyk z rozpoznaną przyczyną w tej grupie.</EmptyState>
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {rows.map((r, i) => (
        // full risk name on its own line (the side column is too narrow to truncate it usefully), bar and value below
        <li key={r.label} className="flex flex-col gap-1">
          <span className="t-small">{r.label}</span>
          <span className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
            <span className="h-2 rounded-pill bg-soft-2">
              <span
                className={cn('block h-2 rounded-pill', i === 0 ? 'bg-attention' : 'bg-text-body-muted')}
                style={{ width: `${Math.max(2, Math.round((Math.max(r.value, 0) / max) * 100))}%` }}
              />
            </span>
            <span className="t-mono text-text-body-muted">{r.display}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

function MethodNote({ sim }: { sim: SimulationResponse }) {
  return (
    <Panel aria-labelledby="sim-method">
      <h2 id="sim-method" className="t-h3 m-0">
        Skąd te linie
      </h2>
      <p className="t-small m-0 text-text-body-muted">
        {fmtInt(sim.runs)} losowań całych umów z grupy porównawczej (n = {fmtInt(sim.n)}), więc opóźnienie,
        koszt i przyczyny zmian pozostają powiązane. Wpływ każdej zmiany to założenie eksperta z Katalogu.
      </p>
      {sim.honesty_note ? <p className="t-caption m-0 text-muted">{sim.honesty_note}</p> : null}
      <a href="/katalog?czesc=zalozenia" className="t-small text-text underline underline-offset-4">
        Założenia w Katalogu
      </a>
    </Panel>
  )
}
