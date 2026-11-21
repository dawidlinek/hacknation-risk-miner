import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { EVIDENCE_STATE_LABEL, type SimFeature, type SimilarCase } from '@/api/contracts/common'
import type {
  PlanVsActual as PlanVsActualData,
  ProjectGap,
  ProjectIdentifier,
} from '@/api/contracts/projects'
import { Item, OutlinePanel, Panel, SectionTitle } from '@/app/Page'
import { LoginRequired } from '@/auth/LoginRequired'
import { EmptyState } from '@/components/common/DataState'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { fmtDays, fmtInt, fmtScore } from '@/lib/format'
import { plural } from '@/lib/plural'

/** Plan bar + overrun bar (B3). Plan share = plan / actual when the actual exceeds the plan. */
export function PlanVsActual({ item }: { item: PlanVsActualData }) {
  const over = item.actual > item.plan
  const planPct = over && item.actual > 0 ? (item.plan / item.actual) * 100 : 100
  return (
    <Item className="flex flex-col gap-2.5 rounded-[22px] bg-soft px-5 py-4.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[14px] text-text-muted">{item.label}</span>
        <span className="font-semibold text-[28px] leading-none tracking-[-0.04em]">{item.delta_label}</span>
      </div>
      <div
        role="img"
        aria-label={`${item.label}: ${item.note}`}
        className="relative h-2.5 w-full overflow-hidden rounded-pill bg-border"
      >
        <span className="absolute inset-y-0 left-0 rounded-pill bg-ink" style={{ width: `${planPct}%` }} />
        {over ? (
          <span className="absolute inset-y-0 right-0 bg-attention" style={{ left: `${planPct}%` }} />
        ) : null}
      </div>
      <span className="t-mono text-muted">{item.note}</span>
    </Item>
  )
}

const SIM_LABEL: Record<SimFeature, string> = {
  podsektor: 'podsektor',
  formula: 'formuła',
  zakres: 'zakres',
  wartosc: 'wartość',
  tekst: 'opis',
}

/** "Podobne przypadki" (B3): completed contracts like this one; score tile, name, buyer and year, why, delay and annexes. */
export function SimilarCaseList({ cases }: { cases: SimilarCase[] }) {
  const pool = cases.find((c) => c.pool_n)?.pool_n
  return (
    <OutlinePanel aria-labelledby="similar-cases" className="gap-1.5">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="similar-cases" className="t-h3 m-0">
          Podobne przypadki
        </h2>
        {pool ? (
          <span className="t-caption text-muted">
            spośród {fmtInt(pool)} {plural(pool, ['wykonanej umowy', 'wykonanych umów', 'wykonanych umów'])} z
            tego podsektora
          </span>
        ) : null}
      </div>
      {cases.length === 0 ? (
        <EmptyState>Brak podobnych wykonanych umów w bazie.</EmptyState>
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          {cases.map((c) => (
            <li key={c.project_id} className="border-divider border-t">
              <Link
                to="/projekty/$id"
                params={{ id: c.project_id }}
                className="flex items-start gap-3 px-1 py-2.5 text-text no-underline hover:bg-soft"
              >
                <span
                  className="t-mono inline-flex size-10 flex-none items-center justify-center rounded-[12px] bg-soft font-semibold text-[14px] text-text"
                  title={`Podobieństwo ${fmtScore(c.score)}: ${c.contributions.map((x) => `${SIM_LABEL[x.feature]} ${fmtScore(x.value)}`).join(', ')}`}
                >
                  {fmtScore(c.score)}
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="t-item line-clamp-3">{c.title}</span>
                  {c.buyer || c.year ? (
                    <span className="t-mono text-muted">
                      {[c.buyer, c.year ? `zakończenie ${c.year}` : null].filter(Boolean).join(', ')}
                    </span>
                  ) : null}
                  <span className="t-mono flex flex-wrap gap-x-3 text-[13px]">
                    <span
                      className={cn((c.delay_days ?? 0) > 0 ? 'text-attention-text' : 'text-text-secondary')}
                    >
                      {c.delay_days === null
                        ? 'termin: brak danych'
                        : c.delay_days === 0
                          ? 'w terminie'
                          : `${fmtDays(c.delay_days)} po terminie`}
                    </span>
                    {c.changes != null ? (
                      <span className="text-text-secondary">
                        {c.changes === 0
                          ? 'bez aneksów'
                          : `${fmtInt(c.changes)} ${plural(c.changes, ['aneks', 'aneksy', 'aneksów'])}`}
                      </span>
                    ) : null}
                  </span>
                  <span className="text-[13px] text-text-body-muted">Podobne: {c.why}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </OutlinePanel>
  )
}

export function GapList({ gaps }: { gaps: ProjectGap[] }) {
  return (
    <Panel>
      <SectionTitle>Czego nie wiemy</SectionTitle>
      {gaps.length === 0 ? (
        <EmptyState>Mamy komplet dokumentów z listy kontrolnej.</EmptyState>
      ) : (
        gaps.map((g) => (
          <Item key={g.doc} className="flex flex-col gap-0.5">
            <span className="t-item">
              {g.doc} <span className="font-normal text-muted">({EVIDENCE_STATE_LABEL[g.state]})</span>
            </span>
            <span className="text-[14px] text-text-body-muted">{g.limits}</span>
          </Item>
        ))
      )}
      <LoginRequired>
        <Button variant="outline" asChild>
          <Link to={'/zrodla' as never}>Dodaj brakujący dokument</Link>
        </Button>
      </LoginRequired>
    </Panel>
  )
}

export function IdentifierList({ items }: { items: ProjectIdentifier[] }) {
  return (
    <Panel>
      <SectionTitle>Identyfikatory</SectionTitle>
      <dl className="m-0 flex flex-col gap-2">
        {items.map((i) => (
          <div key={i.key} className="flex flex-col gap-0.5">
            <dt className="t-caption text-muted">{i.key}</dt>
            <dd className="t-mono m-0 break-all text-text">
              {i.value}
              {i.check === 'ok'
                ? ', suma kontrolna zgodna'
                : i.check === 'bad'
                  ? ', suma kontrolna błędna'
                  : ''}
            </dd>
          </div>
        ))}
      </dl>
    </Panel>
  )
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="t-mono text-muted">{children}</span>
}
