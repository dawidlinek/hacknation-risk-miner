import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { Page } from '@/app/Page'
import { PillTabs } from '@/components/common/PillTabs'
import { Button } from '@/components/ui/button'
import { reportQuery } from './api'

/** Shared frame of an analysis record (1.2–1.5): mono record line, actions, section tabs, then the section. */
export function AnalysisLayout({ id, children }: { id: string; children: ReactNode }) {
  const r = useQuery(reportQuery(id))
  const base = `/analizy/${encodeURIComponent(id)}`
  const firstDoc = r.data?.documents?.[0]?.document_id
  return (
    <Page className="gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="t-mono text-muted" data-testid="analysis-record">
          {r.data?.subtitle || id}
        </span>
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
