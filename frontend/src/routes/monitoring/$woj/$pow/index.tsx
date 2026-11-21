import { createFileRoute } from '@tanstack/react-router'
import { requireFeature } from '@/config/features'
import { PowiatPanel } from '@/features/monitoring/DrillPanels'

export const Route = createFileRoute('/monitoring/$woj/$pow/')({
  beforeLoad: ({ context }) => requireFeature(context, 'radar_drill'),
  component: () => {
    const { woj, pow } = Route.useParams()
    return <PowiatPanel woj={woj} pow={pow} />
  },
})
