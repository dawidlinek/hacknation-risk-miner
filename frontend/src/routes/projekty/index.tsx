import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { pageTitle } from '@/config/brand'
import { projectsTableQuery } from '@/features/projects/api'
import { SORT_KEYS } from '@/features/projects/logic'
import { ProjectsScreen } from '@/features/projects/ProjectsScreen'

const search = z.object({
  q: z.string().optional().catch(undefined),
  filtr: z.string().optional().catch(undefined),
  podsektor: z.string().optional().catch(undefined),
  sort: z
    .enum(SORT_KEYS as [string, ...string[]])
    .optional()
    .catch(undefined),
  kier: z.enum(['asc', 'desc']).optional().catch(undefined),
  str: z.number().int().min(1).optional().catch(undefined),
})

export const Route = createFileRoute('/projekty/')({
  validateSearch: search,
  head: () => ({ meta: [{ title: pageTitle('Projekty') }] }),
  loader: ({ context }) => context.queryClient.ensureQueryData(projectsTableQuery),
  component: ProjectsRoute,
})

function ProjectsRoute() {
  const s = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <ProjectsScreen
      search={s as never}
      onSearch={(patch) => navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })}
    />
  )
}
