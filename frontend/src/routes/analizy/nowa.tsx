import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { pageTitle } from '@/config/brand'
import { NewAnalysisScreen } from '@/features/analysis/NewAnalysisScreen'

export const Route = createFileRoute('/analizy/nowa')({
  validateSearch: z.object({ z: z.string().optional().catch(undefined) }),
  head: () => ({ meta: [{ title: pageTitle('Nowa inwestycja') }] }),
  component: NewAnalysisRoute,
})

function NewAnalysisRoute() {
  const { z: fromId } = Route.useSearch()
  return <NewAnalysisScreen fromId={fromId} />
}
