import { createFileRoute } from '@tanstack/react-router'
import { pageTitle } from '@/config/brand'
import { lessonsQuery } from '@/features/lessons/api'
import { LessonsScreen } from '@/features/lessons/LessonsScreen'

export const Route = createFileRoute('/wnioski')({
  loader: ({ context }) => context.queryClient.ensureQueryData(lessonsQuery()),
  head: () => ({ meta: [{ title: pageTitle('Wnioski sektorowe') }] }),
  component: () => <LessonsScreen />,
})
