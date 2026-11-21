import { createFileRoute, redirect } from '@tanstack/react-router'
import { EmptyState } from '@/components/common/DataState'
import { requireFeature } from '@/config/features'
import { reportQuery } from '@/features/report/api'

/** "Czerwony długopis" tab without a document: open the first attached document, or say there is none. */
export const Route = createFileRoute('/analizy/$id/dokumenty/')({
  beforeLoad: async ({ context, params }) => {
    await requireFeature(context, 'red_pen')
    const r = await context.queryClient.ensureQueryData(reportQuery(params.id))
    const first = r.documents?.[0]?.document_id
    if (first)
      throw redirect({ to: '/analizy/$id/dokumenty/$doc', params: { id: params.id, doc: String(first) } })
  },
  component: NoDocuments,
})

function NoDocuments() {
  return (
    <EmptyState>
      Do tej analizy nie dołączono dokumentów. Dodaj PFU lub PPU w założeniach, a uwagi pojawią się tutaj.
    </EmptyState>
  )
}
