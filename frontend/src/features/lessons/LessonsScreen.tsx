import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'
import type { CalcNum, LessonCategory, LessonSource } from '@/api/contracts/memory'
import { Page, PageHeader, Panel } from '@/app/Page'
import { EmptyState } from '@/components/common/DataState'
import { StatCard } from '@/components/common/StatCard'
import { SummaryCard } from '@/components/common/SummaryCard'
import { lessonsQuery } from './api'

const nOf = (n: CalcNum) => n.prov.n ?? 0

function Source({ s }: { s: LessonSource }) {
  const quote = s.quote ?? s.text
  return (
    <li className="rounded-item bg-surface px-4 py-3">
      <div className="text-[14px] font-medium">
        {s.text}{' '}
        <span className="t-mono text-muted">
          {s.count} zdarzeń, {s.cases} przypadków
        </span>
      </div>
      {quote ? (
        <blockquote className="m-0 mt-1 text-[13px] text-text-body-muted">„{quote}”</blockquote>
      ) : null}
      <div className="t-mono mt-1 flex flex-wrap gap-3 text-muted">
        {s.href ? <Link to={s.href as never}>{s.title ?? s.case_id}</Link> : null}
        {s.url ? (
          <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1">
            ogłoszenie BZP <ExternalLink aria-hidden className="size-3" />
          </a>
        ) : null}
      </div>
    </li>
  )
}

function Category({ c }: { c: LessonCategory }) {
  return (
    <section
      aria-label={`${c.code} ${c.name}`}
      className="flex flex-col gap-3 rounded-panel border border-divider px-5.5 py-5"
    >
      <h2 className="t-h3 m-0">
        {c.code} {c.name}
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Zdarzenia" value={c.events.display} n={nOf(c.events)} provenance="obliczenie" />
        <StatCard
          label="Mediana opóźnienia"
          value={c.delay_median_days.display}
          n={nOf(c.delay_median_days)}
          provenance="obliczenie"
        />
        <StatCard
          label="Mediana kosztu"
          value={c.cost_median.display}
          n={nOf(c.cost_median)}
          provenance="obliczenie"
        />
        <StatCard label="Przypadki" value={c.cases.display} n={nOf(c.cases)} provenance="obliczenie" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-2">
          <h3 className="t-item m-0">Powtarzające się przyczyny</h3>
          {c.causes.length ? (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {c.causes.map((s) => (
                <Source key={s.event_id} s={s} />
              ))}
            </ul>
          ) : (
            <EmptyState>Brak opisanych przyczyn.</EmptyState>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <h3 className="t-item m-0">Środki, które zadziałały</h3>
          {c.mitigations_measured.length ? (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {c.mitigations_measured.map((s) => (
                <Source key={s.event_id} s={s} />
              ))}
            </ul>
          ) : (
            <EmptyState>Brak zmierzonych środków w przypadkach (za mało danych).</EmptyState>
          )}
          {c.mitigations_proposed.length ? (
            <Panel>
              <span className="t-caption text-muted">założenie eksperta, nie zmierzone</span>
              <ul className="m-0 list-disc pl-5 text-[14px]">
                {c.mitigations_proposed.map((m) => (
                  <li key={m.code}>{m.label}</li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      </div>
    </section>
  )
}

export function LessonsScreen({ sector = 'wod-kan' }: { sector?: string }) {
  const { data } = useSuspenseQuery(lessonsQuery(sector))
  const top = data.categories[0]
  const sentence = top
    ? `W bazie najczęściej powtarza się ryzyko ${top.code} ${top.name} (${top.events.display} zdarzeń w ${top.cases.display} przypadkach).`
    : 'Brak wniosków do pokazania.'
  return (
    <Page>
      <PageHeader title="Wnioski sektorowe" lead={data.scope} subtitle={`sektor ${data.sector}, wod-kan`} />
      <SummaryCard
        eyebrow="Pamięć instytucjonalna"
        sentence={sentence}
        provenance={`obliczenie, n = ${nOf(data.totals.events)} zdarzeń, ${data.totals.approved_events} zatwierdzonych przez eksperta`}
      />
      {data.totals.excluded_events > 0 ? (
        <p className="m-0 text-[14px] text-text-body-muted">
          Pominięto {data.totals.excluded_events} propozycji niezatwierdzonych przez eksperta.
        </p>
      ) : null}
      {data.categories.length === 0 ? (
        <EmptyState>Brak zatwierdzonych wniosków dla tego sektora.</EmptyState>
      ) : (
        data.categories.map((c) => <Category key={c.code} c={c} />)
      )}
    </Page>
  )
}
