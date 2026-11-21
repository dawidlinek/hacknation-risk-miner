import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { requireRole } from '@/auth/session'
import { pageTitle } from '@/config/brand'
import { catalogueQuery } from '@/features/catalogue/api'
import { CatalogueScreen, type CatalogueTab, TABS } from '@/features/catalogue/CatalogueScreen'

export const Route = createFileRoute('/katalog')({
  validateSearch: z.object({ czesc: z.string().optional().catch(undefined) }),
  beforeLoad: async ({ context, location }) => {
    await requireRole(context, 'expert', location.href)
  },
  loader: ({ context }) => context.queryClient.ensureQueryData(catalogueQuery),
  head: () => ({ meta: [{ title: pageTitle('Katalog') }] }),
  component: CatalogueRoute,
})

function CatalogueRoute() {
  const { czesc } = Route.useSearch()
  const navigate = Route.useNavigate()
  const tab: CatalogueTab = (TABS as string[]).includes(czesc ?? '') ? (czesc as CatalogueTab) : 'ryzyka'
  return (
    <CatalogueScreen
      tab={tab}
      onTab={(t) => navigate({ search: { czesc: t === 'ryzyka' ? undefined : t }, replace: true })}
    />
  )
}
