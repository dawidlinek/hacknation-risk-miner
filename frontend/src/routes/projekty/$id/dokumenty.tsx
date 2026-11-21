import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { sessionQuery } from '@/auth/session'
import { requireFeature } from '@/config/features'
import { projectDocumentsQuery } from '@/features/documents/api'
import { DocumentsScreen } from '@/features/documents/DocumentsScreen'

export const Route = createFileRoute('/projekty/$id/dokumenty')({
  validateSearch: z.object({ dok: z.string().optional().catch(undefined) }),
  beforeLoad: ({ context }) => requireFeature(context, 'project_docs'),
  loader: async ({ context, params }) => {
    const s = await context.queryClient.ensureQueryData(sessionQuery)
    return context.queryClient.ensureQueryData(projectDocumentsQuery(params.id, s.role === 'public'))
  },
  component: DocumentsRoute,
})

function DocumentsRoute() {
  const { id } = Route.useParams()
  const { dok } = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <DocumentsScreen
      id={id}
      selected={dok ?? null}
      onSelect={(k) => navigate({ search: { dok: k ?? undefined }, replace: true })}
    />
  )
}
