import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { requireRole } from '@/auth/session'
import { requireFeature } from '@/config/features'
import { projectHistoryQuery } from '@/features/audit/api'
import { parseWho } from '@/features/audit/logic'
import { ProjectHistoryScreen } from '@/features/audit/ProjectHistoryScreen'

export const Route = createFileRoute('/projekty/$id/historia')({
  validateSearch: z.object({ kto: z.string().optional().catch(undefined) }),
  beforeLoad: async ({ context, location }) => {
    await requireRole(context, 'expert', location.href)
    await requireFeature(context, 'project_history')
  },
  loader: ({ context, params }) => context.queryClient.ensureQueryData(projectHistoryQuery(params.id)),
  component: HistoryRoute,
})

function HistoryRoute() {
  const { id } = Route.useParams()
  const { kto } = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <ProjectHistoryScreen
      id={id}
      who={parseWho(kto)}
      onWho={(w) => navigate({ search: { kto: w === 'wszystko' ? undefined : w }, replace: true })}
    />
  )
}
