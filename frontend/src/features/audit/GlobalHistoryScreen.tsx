import { useQuery } from '@tanstack/react-query'
import { Page, PageHeader } from '@/app/Page'
import { DataState, EmptyState } from '@/components/common/DataState'
import { ExportMenu } from '@/components/common/ExportMenu'
import { FilterPills } from '@/components/common/FilterPills'
import { auditExportUrl, globalAuditQuery } from './api'
import { GLOBAL_OPTIONS } from './logic'
import { AuditList } from './parts'
import type { GlobalKind } from './types'

export function GlobalHistoryScreen({
  kind,
  day,
  onKind,
  onDay,
}: {
  kind: GlobalKind
  day: string | null
  onKind: (k: GlobalKind) => void
  onDay: (d: string | null) => void
}) {
  const q = useQuery(globalAuditQuery(kind, day))
  return (
    <Page>
      <PageHeader
        title="Historia zmian"
        lead="Wszystko, co zmienili ekspert, model i system. Dziennik jest tylko do dopisywania."
        actions={
          <ExportMenu
            formats={['csv', 'json']}
            label="Eksportuj"
            urlFor={(f) => auditExportUrl(f, kind, day)}
            filename={(f) => `historia.${f}`}
          />
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <FilterPills options={GLOBAL_OPTIONS} value={kind} onChange={onKind} label="Rodzaj zmian" />
        <label className="ml-auto inline-flex min-h-10 items-center gap-2 rounded-pill border border-border px-3.5">
          <span className="text-[13px] text-muted">dzień</span>
          <input
            type="date"
            value={day ?? ''}
            onChange={(e) => onDay(e.target.value || null)}
            className="border-0 bg-transparent text-[14px] font-medium outline-none"
          />
        </label>
      </div>
      <DataState query={q} isEmpty={(d) => d.entries.length === 0} empty="Brak wpisów dla tych filtrów.">
        {(d) => (
          <>
            <AuditList entries={d.entries} variant="global" label="Dziennik zmian" />
            {d.total > d.entries.length ? (
              <EmptyState>
                Pokazano {d.entries.length} z {d.total} wpisów. Pełny dziennik jest w eksporcie.
              </EmptyState>
            ) : null}
          </>
        )}
      </DataState>
    </Page>
  )
}
