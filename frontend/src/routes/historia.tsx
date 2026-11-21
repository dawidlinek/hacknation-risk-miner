import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { requireRole } from '@/auth/session'
import { pageTitle } from '@/config/brand'
import { GlobalHistoryScreen } from '@/features/audit/GlobalHistoryScreen'
import { parseKind } from '@/features/audit/logic'

export const Route = createFileRoute('/historia')({
  validateSearch: z.object({
    rodzaj: z.string().optional().catch(undefined),
    dzien: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/)
      .optional()
      .catch(undefined),
  }),
  beforeLoad: ({ context, location }) => requireRole(context, 'expert', location.href),
  head: () => ({ meta: [{ title: pageTitle('Historia zmian') }] }),
  component: HistoryRoute,
})

function HistoryRoute() {
  const s = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <GlobalHistoryScreen
      kind={parseKind(s.rodzaj)}
      day={s.dzien ?? null}
      onKind={(k) =>
        navigate({ search: (p) => ({ ...p, rodzaj: k === 'wszystko' ? undefined : k }), replace: true })
      }
      onDay={(d) => navigate({ search: (p) => ({ ...p, dzien: d ?? undefined }), replace: true })}
    />
  )
}
