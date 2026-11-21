import { createFileRoute } from '@tanstack/react-router'
import { requireFeature } from '@/config/features'
import { RegionPanel } from '@/features/monitoring/DrillPanels'

export const Route = createFileRoute('/monitoring/$woj/')({
  beforeLoad: ({ context }) => requireFeature(context, 'radar_drill'),
  component: () => <RegionPanel woj={Route.useParams().woj} />,
})
