import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { requireFeature } from '@/config/features'
import { projectGraphQuery } from '@/features/graph/api'
import { GraphScreen } from '@/features/graph/GraphScreen'

export const Route = createFileRoute('/projekty/$id/graf')({
  validateSearch: z.object({ wezel: z.string().optional().catch(undefined) }),
  beforeLoad: ({ context }) => requireFeature(context, 'case_graph'),
  loader: ({ context, params }) => context.queryClient.ensureQueryData(projectGraphQuery(params.id)),
  component: GraphRoute,
})

function GraphRoute() {
  const { id } = Route.useParams()
  const { wezel } = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <GraphScreen
      id={id}
      selected={wezel ?? null}
      onSelect={(w) => navigate({ search: { wezel: w ?? undefined }, replace: true })}
    />
  )
}
