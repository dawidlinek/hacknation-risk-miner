import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import type { Metric } from '@/api/contracts/simulation'
import { pageTitle } from '@/config/brand'
import { requireFeature } from '@/config/features'
import { SectionError, SimulationSkeleton } from '@/features/report/Skeletons'
import { simulationQuery } from '@/features/simulation/api'
import { SimulationScreen } from '@/features/simulation/SimulationScreen'
import { METRIC_FROM_PARAM, PARAM_FROM_METRIC } from '@/features/simulation/scenario'

export const Route = createFileRoute('/analizy/$id/symulacja')({
  validateSearch: z.object({
    miara: z.enum(['czas', 'koszt', 'konkurencja']).optional().catch(undefined),
    zmiany: z.string().optional().catch(undefined),
  }),
  beforeLoad: ({ context }) => requireFeature(context, 'monte_carlo'),
  loader: ({ context, params }) => context.queryClient.ensureQueryData(simulationQuery(params.id)),
  head: ({ params }) => ({ meta: [{ title: pageTitle(`Symulacja ${params.id}`) }] }),
  errorComponent: SectionError,
  pendingComponent: SimulationSkeleton,
  component: SimulationRoute,
})

function SimulationRoute() {
  const { id } = Route.useParams()
  const { miara, zmiany } = Route.useSearch()
  const navigate = Route.useNavigate()
  const metric: Metric = METRIC_FROM_PARAM[miara ?? 'czas'] ?? 'time'
  const checked = (zmiany ?? '').split(',').filter(Boolean)
  return (
    <SimulationScreen
      id={id}
      metric={metric}
      checked={checked}
      onMetric={(m) =>
        navigate({ search: (s) => ({ ...s, miara: PARAM_FROM_METRIC[m] as 'czas' }), replace: true })
      }
      onChecked={(keys) =>
        navigate({
          search: (s) => ({ ...s, zmiany: keys.length ? keys.join(',') : undefined }),
          replace: true,
        })
      }
    />
  )
}
