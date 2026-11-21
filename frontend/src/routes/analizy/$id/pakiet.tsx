import { createFileRoute } from '@tanstack/react-router'
import { pageTitle } from '@/config/brand'
import { requireFeature } from '@/config/features'
import { AllocationScreen } from '@/features/allocation/AllocationScreen'
import { allocationQuery } from '@/features/allocation/api'

export const Route = createFileRoute('/analizy/$id/pakiet')({
  beforeLoad: ({ context }) => requireFeature(context, 'allocation'),
  loader: ({ context, params }) => context.queryClient.ensureQueryData(allocationQuery(params.id)),
  head: ({ params }) => ({ meta: [{ title: pageTitle(`Podział ryzyk ${params.id}`) }] }),
  component: AllocationRoute,
})

function AllocationRoute() {
  const { id } = Route.useParams()
  return <AllocationScreen id={id} />
}
