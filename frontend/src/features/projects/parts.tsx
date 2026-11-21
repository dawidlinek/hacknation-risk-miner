import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { EVIDENCE_STATE_LABEL, type SimFeature, type SimilarCase } from '@/api/contracts/common'
import type {
  PlanVsActual as PlanVsActualData,
  ProjectGap,
  ProjectIdentifier,
  ProjectLesson,
} from '@/api/contracts/projects'
import { Item, Panel, SectionTitle } from '@/app/Page'
import { LoginRequired } from '@/auth/LoginRequired'
import { useSession } from '@/auth/session'
import { EmptyState } from '@/components/common/DataState'
import { ReviewStatusBadge } from '@/components/common/ReviewStatusBadge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { fmtDays, fmtPct, fmtScore } from '@/lib/format'

/** Plan bar + overrun bar (B3). Plan share = plan / actual when the actual exceeds the plan. */
export function PlanVsActual({ item }: { item: PlanVsActualData }) {
  const over = item.actual > item.plan
  const planPct = over && item.actual > 0 ? (item.plan / item.actual) * 100 : 100
  return (
    <Item className="flex flex-col gap-2 bg-soft">
      <div className="flex items-baseline justify-between gap-2">
        <span className="t-item">{item.label}</span>
        <span className={cn('t-h3', over && 'text-attention-text')}>{item.delta_label}</span>
      </div>
      <div
        role="img"
        aria-label={`${item.label}: ${item.note}`}
        className="relative h-2.5 w-full overflow-hidden rounded-pill bg-soft-2"
      >
        <span className="absolute inset-y-0 left-0 bg-text-secondary" style={{ width: `${planPct}%` }} />
        {over ? (
          <span className="absolute inset-y-0 right-0 bg-attention" style={{ left: `${planPct}%` }} />
        ) : null}
      </div>
      <span className="t-mono text-muted">{item.note}</span>
    </Item>
  )
}

const SIM_COLOR: Record<SimFeature, string> = {
  podsektor: 'var(--sim-podsektor)',
  formula: 'var(--sim-formula)',
  zakres: 'var(--sim-zakres)',
  wartosc: 'var(--sim-wartosc)',
  tekst: 'var(--sim-tekst)',
}
const SIM_LABEL: Record<SimFeature, string> = {
  podsektor: 'podsektor',
  formula: 'formuła',
  zakres: 'zakres',
  wartosc: 'wartość',
  tekst: 'opis',
}

/** "Podobne przypadki": score, title, why, outcome, stacked contribution bar. F1's CaseRow replaces this once it lands. */
export function SimilarCaseList({ cases }: { cases: SimilarCase[] }) {
  if (cases.length === 0)
    return <EmptyState>Brak podobnych przypadków z zatwierdzonymi zdarzeniami.</EmptyState>
  return (
    <div className="flex flex-col gap-2">
      {cases.map((c) => (
        <Item key={c.project_id} className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between gap-3">
            <Link
              to="/projekty/$id"
              params={{ id: c.project_id }}
              className="t-item text-text no-underline hover:underline"
            >
              {c.title}
            </Link>
            <span className="t-mono text-muted">{fmtScore(c.score)}</span>
          </div>
          <span className="text-[13px] text-text-body-muted">{c.why}</span>
          <div
            role="img"
            aria-label={`Podobieństwo ${fmtScore(c.score)}: ${c.contributions.map((x) => `${SIM_LABEL[x.feature]} ${fmtScore(x.value)}`).join(', ')}`}
            className="flex h-1.5 w-full overflow-hidden rounded-pill bg-soft-2"
          >
            {c.contributions.map((x) => (
              <span
                key={x.feature}
                style={{ flex: `${Math.max(x.value, 0)} 1 0`, background: SIM_COLOR[x.feature] }}
              />
            ))}
          </div>
          <div className="t-mono flex gap-4 text-muted">
            <span className={cn((c.delay_days ?? 0) > 0 && 'text-attention-text')}>
              {c.delay_days === null ? 'brak' : fmtDays(c.delay_days)}
            </span>
            <span className={cn((c.cost_dev_pct ?? 0) > 0.5 && 'text-attention-text')}>
              {c.cost_dev_pct === null ? 'brak' : fmtPct(c.cost_dev_pct, { signed: true })}
            </span>
          </div>
        </Item>
      ))}
    </div>
  )
}

/** Public mode keeps only reviewed lessons (second line of defence; the backend filters first). */
export function visibleLessons(lessons: ProjectLesson[], isPublic: boolean): ProjectLesson[] {
  return isPublic
    ? lessons.filter(
        (l) => l.review_status === 'approved' || l.review_status === 'edited' || l.review_status === 'auto',
      )
    : lessons
}

/** Unspecified model labels (N-UNSPEC) get a Polish phrase instead of the raw catalogue code. */
export function lessonTitle(title: string): string {
  return title.replace(/przyczyna według modelu N-UNSPEC \([^)]*\)/, 'przyczyna nieustalona')
}

export interface LessonGroup {
  key: string
  title: string
  items: ProjectLesson[]
}

/** Near-duplicate lessons (same cleaned title, risk code and review status) collapse into one group with a count. */
export function groupLessons(lessons: ProjectLesson[]): LessonGroup[] {
  const groups = new Map<string, LessonGroup>()
  for (const l of lessons) {
    const title = lessonTitle(l.title)
    const key = `${title}|${l.risk_code ?? ''}|${l.review_status}`
    const g = groups.get(key)
    if (g) g.items.push(l)
    else groups.set(key, { key, title, items: [l] })
  }
  return [...groups.values()]
}

export function LessonList({ lessons }: { lessons: ProjectLesson[] }) {
  const { isPublic } = useSession()
  const shown = visibleLessons(lessons, isPublic)
  return (
    <Panel>
      <SectionTitle>Lekcje z tej umowy</SectionTitle>
      {shown.length === 0 ? (
        <EmptyState>
          {isPublic
            ? 'Lekcje pojawią się po przeglądzie eksperta.'
            : 'Nie ma jeszcze zdarzeń ryzyka dla tej umowy.'}
        </EmptyState>
      ) : (
        groupLessons(shown).map(({ key, title, items }) => {
          const l = items[0]
          return (
            <Item key={key} className="flex flex-col gap-1">
              <div className="flex items-start justify-between gap-3">
                <span className="t-item">
                  {title}
                  {items.length > 1 ? (
                    <span className="t-mono ml-2 font-normal text-muted">{items.length} zdarzeń</span>
                  ) : null}
                </span>
                <ReviewStatusBadge
                  status={l.review_status}
                  reviewItemId={l.review_item_id}
                  className="shrink-0"
                />
              </div>
              {items.length === 1 ? <span className="text-[14px] text-text-body-muted">{l.text}</span> : null}
              <span className="t-mono text-muted">{l.code_label}</span>
            </Item>
          )
        })
      )}
    </Panel>
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
