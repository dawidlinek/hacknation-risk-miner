import { createFileRoute } from '@tanstack/react-router'
import { requireRole } from '@/auth/session'
import { pageTitle } from '@/config/brand'
import { ImportScreen } from '@/features/import/ImportScreen'

export const Route = createFileRoute('/zrodla')({
  beforeLoad: async ({ context, location }) => {
    await requireRole(context, 'expert', location.href)
  },
  head: () => ({ meta: [{ title: pageTitle('Import i źródła') }] }),
  component: ImportScreen,
})
