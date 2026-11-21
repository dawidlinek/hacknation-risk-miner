import { createFileRoute } from '@tanstack/react-router'
import { requireFeature } from '@/config/features'
import { ContractPanel } from '@/features/monitoring/DrillPanels'

export const Route = createFileRoute('/monitoring/$woj/$pow/umowa/$umowa')({
  beforeLoad: ({ context }) => requireFeature(context, 'radar_drill'),
  component: () => {
    const { woj, pow, umowa } = Route.useParams()
    return <ContractPanel woj={woj} pow={pow} id={umowa} />
  },
})
