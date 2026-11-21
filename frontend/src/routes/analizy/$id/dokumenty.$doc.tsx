import { createFileRoute } from '@tanstack/react-router'
import { useCallback, useEffect, useState } from 'react'
import { z } from 'zod'
import { pageTitle } from '@/config/brand'
import { requireFeature } from '@/config/features'
import { redpenQuery } from '@/features/redpen/api'
import { noteFromHash } from '@/features/redpen/logic'
import { RedPenScreen } from '@/features/redpen/RedPenScreen'
import { RedPenSkeleton, SectionError } from '@/features/report/Skeletons'

export const Route = createFileRoute('/analizy/$id/dokumenty/$doc')({
  validateSearch: z.object({
    s: z.coerce.number().int().positive().optional().catch(undefined),
    wszystkie: z.coerce.boolean().optional().catch(undefined),
  }),
  beforeLoad: ({ context }) => requireFeature(context, 'red_pen'),
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(redpenQuery(params.id, Number(params.doc))),
  head: ({ params }) => ({ meta: [{ title: pageTitle(`Czerwony długopis ${params.id}`) }] }),
  errorComponent: SectionError,
  pendingComponent: RedPenSkeleton,
  component: RedPenRoute,
})

function RedPenRoute() {
  const { id, doc } = Route.useParams()
  const { s, wszystkie } = Route.useSearch()
  const navigate = Route.useNavigate()
  const [active, setActive] = useState<string | null>(() =>
    typeof window === 'undefined' ? null : noteFromHash(window.location.hash),
  )
  useEffect(() => {
    if (active && typeof window !== 'undefined') window.history.replaceState(null, '', `#u${active}`)
  }, [active])
  const onPage = useCallback(
    (p: number) => navigate({ search: (prev) => ({ ...prev, s: p }), replace: true }),
    [navigate],
  )
  return (
    <RedPenScreen
      id={id}
      doc={Number(doc)}
      page={s}
      onlyNoted={!wszystkie}
      active={active}
      onPage={onPage}
      onOnlyNoted={(v) =>
        navigate({ search: (prev) => ({ ...prev, wszystkie: v ? undefined : true }), replace: true })
      }
      onActive={setActive}
    />
  )
}
