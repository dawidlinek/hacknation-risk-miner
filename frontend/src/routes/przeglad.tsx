import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { KIND_SLUG, parseKindParam } from '@/api/adapters/review'
import { requireRole } from '@/auth/session'
import { pageTitle } from '@/config/brand'
import { requireFeature } from '@/config/features'
import { ReviewScreen } from '@/features/review/ReviewScreen'

export const Route = createFileRoute('/przeglad')({
  validateSearch: z.object({
    rodzaj: z.string().optional().catch(undefined),
    sprawa: z.coerce.number().int().optional().catch(undefined),
    ryzyko: z.string().optional().catch(undefined),
  }),
  beforeLoad: async ({ context, location }) => {
    await requireRole(context, 'expert', location.href)
    await requireFeature(context, 'review_queue')
  },
  head: () => ({ meta: [{ title: pageTitle('Przegląd') }] }),
  component: ReviewRoute,
})

function ReviewRoute() {
  const s = Route.useSearch()
  const navigate = Route.useNavigate()
  const kind = parseKindParam(s.rodzaj)
  return (
    <ReviewScreen
      kind={kind}
      first={s.sprawa}
      code={s.ryzyko}
      onKind={(k) => navigate({ search: { rodzaj: k ? KIND_SLUG[k] : undefined }, replace: true })}
    />
  )
}
