import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { Page } from '@/app/Page'
import { PillTabs } from '@/components/common/PillTabs'
import { Button } from '@/components/ui/button'
import { useFeature } from '@/config/features'
import { JellyDigger } from '@/features/jelly/JellyDigger'
import { reportQuery } from './api'

/** Shared frame of an analysis record (1.2–1.5): title, mono record line, actions, section tabs, then the section. */
export function AnalysisLayout({ id, children }: { id: string; children: ReactNode }) {
  const r = useQuery(reportQuery(id))
  const base = `/analizy/${encodeURIComponent(id)}`
  const pathname = useRouterState({ select: (st) => st.location.pathname })
  const onDocs = pathname.includes('/dokumenty')
  // A2 mockup: the master jelly in its koparka sits before the project name on the summary only
  const onSummary = pathname.replace(/\/$/, '') === base
  const jelly = useFeature('jelly')
  const title = r.data?.title || id
  const firstDoc = r.data?.documents?.[0]?.document_id
  return (
    <Page className="gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-2">
          {onDocs ? (
            <div className="t-h1 m-0">{title}</div>
          ) : (
            <div className="flex items-end gap-4">
              {jelly && onSummary ? <JellyDigger /> : null}
              <h1 className="t-h1 m-0 outline-none" tabIndex={-1} data-page-title>
                {title}
              </h1>
            </div>
          )}
          <span className="t-mono text-muted" data-testid="analysis-record">
            {r.data?.subtitle || id}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to="/analizy/nowa" search={{ z: id }}>
              Edytuj założenia
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <a href={`${base}/pakiet`}>Pakiet do akt</a>
          </Button>
        </div>
      </div>
      <PillTabs
        label="Sekcje analizy"
        tabs={[
          { label: 'Podsumowanie', href: base, exact: true },
          {
            label: 'Czerwony długopis',
            href: firstDoc ? `${base}/dokumenty/${firstDoc}` : `${base}/dokumenty`,
            match: [`${base}/dokumenty`],
            flag: 'red_pen',
          },
          { label: 'Symulacja', href: `${base}/symulacja`, flag: 'monte_carlo' },
          { label: 'Podział ryzyk i pakiet', href: `${base}/pakiet`, flag: 'allocation' },
        ]}
      />
      {children}
    </Page>
  )
}
