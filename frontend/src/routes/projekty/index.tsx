import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { pageTitle } from '@/config/brand'
import { projectsTableQuery } from '@/features/projects/api'
import { NATIONAL_SORTS, SORT_KEYS } from '@/features/projects/logic'
import { ProjectsScreen } from '@/features/projects/ProjectsScreen'

const search = z.object({
  q: z.union([z.string(), z.number()]).transform(String).optional().catch(undefined),
  filtr: z.string().optional().catch(undefined),
  podsektor: z.string().optional().catch(undefined),
  sort: z
    .enum(SORT_KEYS as [string, ...string[]])
    .optional()
    .catch(undefined),
  kier: z.enum(['asc', 'desc']).optional().catch(undefined),
  tab: z.literal('polska').optional().catch(undefined),
  // the router JSON-parses search values, so "14" arrives as a number and "02" as a string
  woj: z
    .union([z.string(), z.number()])
    .transform((v) => String(v).padStart(2, '0'))
    .pipe(z.string().regex(/^\d{2}$/))
    .optional()
    .catch(undefined),
  status: z.string().optional().catch(undefined),
  od: z.number().int().min(1990).max(2100).optional().catch(undefined),
  do: z.number().int().min(1990).max(2100).optional().catch(undefined),
  skladniki: z.boolean().optional().catch(undefined),
  nsort: z
    .enum(NATIONAL_SORTS as [string, ...string[]])
    .optional()
    .catch(undefined),
  nkier: z.enum(['asc', 'desc']).optional().catch(undefined),
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
