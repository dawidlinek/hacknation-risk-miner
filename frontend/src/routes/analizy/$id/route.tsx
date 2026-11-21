import { createFileRoute, Outlet } from '@tanstack/react-router'
import { AnalysisLayout } from '@/features/report/AnalysisLayout'

export const Route = createFileRoute('/analizy/$id')({
  component: AnalysisLayoutRoute,
})

function AnalysisLayoutRoute() {
  const { id } = Route.useParams()
  return (
    <AnalysisLayout id={id}>
      <Outlet />
    </AnalysisLayout>
  )
}
