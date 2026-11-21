import { createFileRoute, redirect } from '@tanstack/react-router'
import { sessionQuery } from '@/auth/session'
import { pageTitle } from '@/config/brand'
import { featuresQuery } from '@/config/features'
import { dashboardQuery, PulpitScreen } from '@/features/dashboard/PulpitScreen'

// Public: Monitoring (or Nowa inwestycja when `radar` is off). Expert: Pulpit (or Projekty while `dashboard` is off).
export const Route = createFileRoute('/')({
  beforeLoad: async ({ context }) => {
    const [s, f] = await Promise.all([
      context.queryClient.ensureQueryData(sessionQuery),
      context.queryClient.ensureQueryData(featuresQuery),
    ])
    if (s.role === 'public')
      throw redirect({ to: (f.radar ? '/monitoring' : '/analizy/nowa') as never, replace: true })
    if (!f.dashboard) throw redirect({ to: '/projekty' as never, replace: true })
  },
  loader: ({ context }) => context.queryClient.ensureQueryData(dashboardQuery),
  head: () => ({ meta: [{ title: pageTitle('Pulpit') }] }),
  component: PulpitScreen,
})
