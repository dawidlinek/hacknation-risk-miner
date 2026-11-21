import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'
import { TwoCol } from '@/app/Page'
import { useSession } from '@/auth/session'
import { EmptyState } from '@/components/common/DataState'
import { DetailPanel } from '@/components/common/DetailPanel'
import { Button } from '@/components/ui/button'
import { projectGraphQuery } from './api'
import { EvidenceFlow } from './EvidenceFlow'
import { hasFlow } from './logic'

function Legend() {
  const item = (cls: string, label: string) => (
    <span className="inline-flex items-center gap-1.5 text-[13px] text-text-secondary">
      <span aria-hidden className={`size-2.5 rounded-[2px] ${cls}`} />
      {label}
    </span>
  )
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
      {item('bg-prov-source', 'źródło')}
      {item('bg-prov-ai', 'odczyt modelu')}
      {item('bg-prov-calc', 'obliczenie')}
      <span className="t-caption w-full text-muted sm:w-auto">kliknij wniosek, żeby zobaczyć jego drogę</span>
    </div>
  )
}

export function GraphScreen({
  id,
  selected,
  onSelect,
}: {
  id: string
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const { data: flow } = useSuspenseQuery(projectGraphQuery(id))
  const { isPublic, isExpert } = useSession()
  if (!hasFlow(flow)) {
    return (
      <EmptyState>
        Ten projekt nie ma jeszcze powiązanych faktów.
        {isExpert ? ' Uruchom wzbogacanie.' : ''}
      </EmptyState>
    )
  }
  const detail = selected ? flow.details[selected] : null
  const node = selected ? flow.nodes.find((n) => n.id === selected) : null
  const panel = detail ?? flow.overview
  const proposed = node?.review_status === 'proposed'
  return (
    <TwoCol
      main={
        <>
          <div className="overflow-x-auto rounded-panel border border-divider p-4">
            <EvidenceFlow flow={flow} selected={selected} onSelect={onSelect} />
          </div>
          <Legend />
        </>
      }
      aside={
        <DetailPanel
          kind={panel.kind}
          title={panel.title}
          rows={panel.rows.map((r) => ({ k: r.k, v: r.v }))}
          footer={
            detail?.review_item_id && proposed ? (
              isPublic ? (
                <span className="inline-flex items-center gap-1.5 text-[13px] text-muted">
                  <span aria-hidden className="size-3 rounded-pill border-2 border-dashed border-border" />
                  niezweryfikowane
                </span>
              ) : (
                <Button variant="attention" size="lg" asChild>
                  <Link to={'/przeglad' as never} search={{ sprawa: detail.review_item_id } as never}>
                    Sprawdź w Przeglądzie
                  </Link>
                </Button>
              )
            ) : null
          }
        >
          {detail?.evidence && detail.evidence.length > 0 ? (
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
              {detail.evidence.map((e, i) => (
                <li key={`${e.label}-${i}`} className="t-mono text-muted">
                  {e.url ? (
                    <a
                      href={e.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-text-secondary hover:underline"
                    >
                      {e.label}
                      <ExternalLink aria-hidden className="size-3" />
                      <span className="sr-only">(otwiera się w nowej karcie)</span>
                    </a>
                  ) : (
                    e.label
                  )}
                  {e.field ? `, pole ${e.field}` : ''}
                </li>
              ))}
            </ul>
          ) : null}
        </DetailPanel>
      }
    />
  )
}
