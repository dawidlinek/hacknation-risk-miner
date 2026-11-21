import { createFileRoute } from '@tanstack/react-router'
import { pageTitle } from '@/config/brand'
import { requireFeature } from '@/config/features'
import { AskScreen } from '@/features/ask/AskScreens'

export const Route = createFileRoute('/zapytaj/')({
  beforeLoad: ({ context }) => requireFeature(context, 'ask_memory'),
  head: () => ({ meta: [{ title: pageTitle('Zapytaj pamięć') }] }),
  component: AskScreen,
})
