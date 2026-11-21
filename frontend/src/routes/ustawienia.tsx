import { createFileRoute } from '@tanstack/react-router'
import { requireRole } from '@/auth/session'
import { pageTitle } from '@/config/brand'
import { requireFeature } from '@/config/features'
import { SettingsScreen, settingsQuery } from '@/features/settings/SettingsScreen'

export const Route = createFileRoute('/ustawienia')({
  beforeLoad: async ({ context, location }) => {
    await requireRole(context, 'expert', location.href)
    await requireFeature(context, 'settings_view')
  },
  loader: ({ context }) => context.queryClient.ensureQueryData(settingsQuery),
  head: () => ({ meta: [{ title: pageTitle('Ustawienia') }] }),
  component: SettingsScreen,
})
