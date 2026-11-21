import { createFileRoute } from '@tanstack/react-router'
import { pageTitle } from '@/config/brand'
import { useFeature } from '@/config/features'
import { askAnalysis } from '@/features/ask/api'
import { ChatPanel } from '@/features/ask/ChatPanel'
import { reportQuery } from '@/features/report/api'
import { ReportScreen } from '@/features/report/ReportScreen'

export const Route = createFileRoute('/analizy/$id/')({
  loader: ({ context, params }) => context.queryClient.ensureQueryData(reportQuery(params.id)),
  head: ({ params }) => ({ meta: [{ title: pageTitle(`Raport ${params.id}`) }] }),
  component: ReportRoute,
})

function ReportRoute() {
  const { id } = Route.useParams()
  const chatOn = useFeature('ask_memory')
  // report chat (F2's ChatPanel) in the slot between the flags and the comparison group
  const chat = chatOn ? (
    <ChatPanel title="Zapytaj o ten raport" context="analysis" ask={(q) => askAnalysis(id, q, 'report')} />
  ) : null
  return <ReportScreen id={id} chat={chat} />
}
