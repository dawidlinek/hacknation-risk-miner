import { createFileRoute, Outlet } from '@tanstack/react-router'
import { z } from 'zod'
import { pageTitle } from '@/config/brand'
import { requireFeature } from '@/config/features'
import { MonitoringLayout } from '@/features/monitoring/MonitoringLayout'

export const Route = createFileRoute('/monitoring')({
  validateSearch: z.object({
    tryb: z.enum(['done', 'open']).optional().catch(undefined),
    miara: z.string().optional().catch(undefined),
    sygnaly: z.coerce.number().optional().catch(undefined),
    q: z.string().optional().catch(undefined),
    podsektor: z.string().optional().catch(undefined),
    wartosc: z.string().optional().catch(undefined),
    rok: z.coerce.number().int().optional().catch(undefined),
  }),
  beforeLoad: ({ context }) => requireFeature(context, 'radar'),
  head: () => ({ meta: [{ title: pageTitle('Monitoring') }] }),
  component: () => (
    <MonitoringLayout>
      <Outlet />
    </MonitoringLayout>
  ),
})
