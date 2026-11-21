import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { TimelineStep } from '@/api/contracts/projects'
import { Panel, SectionTitle, TwoCol } from '@/app/Page'
import { EmptyState } from '@/components/common/DataState'
import { ReviewStatusBadge } from '@/components/common/ReviewStatusBadge'
import { StepItem, StepList } from '@/components/common/StepList'
import { SummaryCard } from '@/components/common/SummaryCard'
import { useFeature } from '@/config/features'
import { askProject } from '@/features/ask/api'
import { ChatPanel } from '@/features/ask/ChatPanel'
import { projectCardQuery } from './api'
import { GapList, IdentifierList, LessonList, PlanVsActual, SimilarCaseList } from './parts'

function StepRef({ step }: { step: TimelineStep }) {
  if (!step.ref) return null
  if (step.href.startsWith('/')) {
    // hrefs may carry a query string (documents tab: ?dok=doc:<id>)
    const [to, query] = step.href.split('?')
    const search = query ? Object.fromEntries(new URLSearchParams(query)) : undefined
    return (
      <Link
        to={to as never}
        search={search as never}
        className="t-mono text-muted underline-offset-2 hover:underline"
      >
        {step.ref}
      </Link>
    )
  }
  if (step.href.startsWith('http')) {
    return (
      <a
        href={step.href}
        target="_blank"
        rel="noreferrer"
        className="t-mono text-muted underline-offset-2 hover:underline"
      >
        {step.ref}
      </a>
    )
  }
  return <span className="t-mono text-muted">{step.ref}</span>
}

export function ProjectCardScreen({ id }: { id: string }) {
  const { data: card } = useSuspenseQuery(projectCardQuery(id))
  const chat = useFeature('ask_memory')
  return (
    <TwoCol
      main={
        <>
          <SummaryCard
            eyebrow="Co się stało"
            sentence={card.summary.text}
            provenance={card.summary.provenance}
          />
          {card.plan_vs_actual.length > 0 ? (
            <div
              className="grid gap-3"
              style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}
            >
              {card.plan_vs_actual.map((p) => (
                <PlanVsActual key={p.key} item={p} />
              ))}
            </div>
          ) : null}
          {card.timeline.length === 0 ? (
            <EmptyState>Brak ogłoszeń powiązanych z projektem.</EmptyState>
          ) : (
            <StepList title="Przebieg">
              {card.timeline.map((s, i) => (
                <StepItem
                  key={`${s.ref}-${i}`}
                  state={s.state}
                  title={
                    <span className="flex flex-wrap items-center gap-2">
                      {s.title}
                      <ReviewStatusBadge status={s.review_status} />
                    </span>
                  }
                  text={s.text}
                  meta={<StepRef step={s} />}
                  right={<span className="t-mono text-muted">{s.date_label}</span>}
                />
              ))}
            </StepList>
          )}
          {chat && /^RM-/.test(card.id) ? (
            <ChatPanel
              context="project"
              ask={(q) => askProject(card.id, q)}
              placeholder="Zadaj pytanie o ten projekt"
            />
          ) : null}
        </>
      }
      aside={
        <>
          <Panel>
            <SectionTitle>Podobne przypadki</SectionTitle>
            <SimilarCaseList cases={card.similar_cases} />
          </Panel>
          <LessonList lessons={card.lessons} />
          <GapList gaps={card.gaps} />
          <IdentifierList items={card.identifiers} />
        </>
      }
    />
  )
}
