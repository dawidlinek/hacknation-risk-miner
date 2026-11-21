import { createFileRoute } from '@tanstack/react-router'
import { pageTitle } from '@/config/brand'
import { organizationMemoryQuery } from '@/features/memory/api'
import { OrganizationScreen } from '@/features/memory/OrganizationScreen'

export const Route = createFileRoute('/organizacje/$nip')({
  loader: ({ context, params }) => context.queryClient.ensureQueryData(organizationMemoryQuery(params.nip)),
  head: ({ params }) => ({ meta: [{ title: pageTitle(`Organizacja ${params.nip}`) }] }),
  component: () => <OrganizationScreen nip={Route.useParams().nip} />,
})
