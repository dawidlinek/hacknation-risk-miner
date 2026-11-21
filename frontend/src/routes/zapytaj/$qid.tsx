import { createFileRoute } from '@tanstack/react-router'
import { pageTitle } from '@/config/brand'
import { requireFeature } from '@/config/features'
import { SavedQuestionScreen } from '@/features/ask/AskScreens'
import { savedQuestionQuery } from '@/features/ask/api'

export const Route = createFileRoute('/zapytaj/$qid')({
  beforeLoad: ({ context }) => requireFeature(context, 'ask_memory'),
  loader: ({ context, params }) => context.queryClient.ensureQueryData(savedQuestionQuery(params.qid)),
  head: ({ params }) => ({ meta: [{ title: pageTitle(`Pytanie ${params.qid}`) }] }),
  component: () => <SavedQuestionScreen code={Route.useParams().qid} />,
})
