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
    typ: z.string().optional().catch(undefined),
    projekt: z.string().optional().catch(undefined),
    kolejnosc: z.enum(['strength', 'queue']).optional().catch(undefined),
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
      filter={{ type: s.typ, project: s.projekt, sort: s.kolejnosc }}
      onKind={(k) =>
        navigate({ search: { rodzaj: k ? KIND_SLUG[k] : undefined, kolejnosc: s.kolejnosc }, replace: true })
      }
      onFilter={(f) =>
        navigate({
          search: {
            rodzaj: s.rodzaj,
            ryzyko: f.code === '' ? undefined : s.ryzyko,
            typ: f.type,
            projekt: f.project,
            kolejnosc: f.sort,
          },
          replace: true,
        })
      }
    />
  )
}
