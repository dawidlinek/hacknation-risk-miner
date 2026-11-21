import { useMutation, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, Link, Outlet } from '@tanstack/react-router'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { ApiError, contractFetch } from '@/api/client'
import type { JobOut } from '@/api/contracts/import'
import { NotFound } from '@/app/NotFound'
import { Page, PageHeader } from '@/app/Page'
import { LoginRequired } from '@/auth/LoginRequired'
import { useSession } from '@/auth/session'
import { ExportMenu } from '@/components/common/ExportMenu'
import { type PillTab, PillTabs } from '@/components/common/PillTabs'
import { Button } from '@/components/ui/button'
import { pageTitle } from '@/config/brand'
import { projectCardQuery } from '@/features/projects/api'
import { fmtNip } from '@/lib/format'

export const Route = createFileRoute('/projekty/$id')({
  loader: async ({ context, params }) => context.queryClient.ensureQueryData(projectCardQuery(params.id)),
  head: ({ params }) => ({ meta: [{ title: pageTitle(`Projekt ${params.id}`) }] }),
  // the card loaded (a missing project is an ApiError 404 handled below), so a notFound here is a disabled section
  notFoundComponent: () => (
    <Page>
      <div className="flex flex-col items-start gap-3 rounded-panel bg-soft p-6">
        <h1 className="t-h2 m-0" data-page-title tabIndex={-1}>
          Ta sekcja nie jest jeszcze dostępna.
        </h1>
        <Link to="/projekty/$id" params={{ id: Route.useParams().id }} className="font-medium">
          Wróć do karty projektu
        </Link>
      </div>
    </Page>
  ),
  errorComponent: ({ error }) => (
    <Page>
      <NotFoundOrError error={error} />
    </Page>
  ),
  component: ProjectLayout,
})

function NotFoundOrError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 404) return <NotFound title="Nie ma takiego projektu." />
  throw error
}

function ProjectLayout() {
  const { id } = Route.useParams()
  const { data: card } = useSuspenseQuery(projectCardQuery(id))
  const { isExpert, readOnly } = useSession()
  const enrich = useMutation({
    mutationFn: () =>
      contractFetch<JobOut>('/api/jobs', { method: 'POST', json: { kind: 'load_all', payload: {} } }),
    onSuccess: (job) =>
      toast.success(`Wzbogacanie uruchomione (#${job.id}). Karta odświeży się po zakończeniu.`),
    onError: (e) =>
      toast.error(
        e instanceof ApiError && e.status === 403
          ? 'Wzbogacanie może uruchomić administrator.'
          : 'Nie udało się uruchomić wzbogacania.',
      ),
  })
  const base = `/projekty/${id}`
  const tabs: PillTab[] = [
    { label: 'Przebieg', href: base, exact: true },
    { label: 'Graf powiązań', href: `${base}/graf`, flag: 'case_graph' },
    {
      label: `Dokumenty (${card.doc_counts.have} z ${card.doc_counts.expected})`,
      href: `${base}/dokumenty`,
      flag: 'project_docs',
    },
    ...(isExpert && !card.auto_card
      ? [{ label: 'Historia zmian', href: `${base}/historia`, flag: 'project_history' as const }]
      : []),
  ]
  return (
    <Page>
      <PageHeader
        breadcrumb={
          <>
            <Link to="/projekty" className="text-muted no-underline hover:underline">
              Projekty
            </Link>
            {' / '}
            {card.id}
            {card.buyer.name ? (
              <>
                {', '}
                {card.buyer.nip ? (
                  <Link to="/organizacje/$nip" params={{ nip: card.buyer.nip }}>
                    {card.buyer.name}
                  </Link>
                ) : (
                  card.buyer.name
                )}
              </>
            ) : null}
            {card.buyer.nip ? `, NIP ${fmtNip(card.buyer.nip)}` : ''}
          </>
        }
        title={card.title}
        actions={
          <>
            {card.auto_card ? null : (
              <LoginRequired>
                <Button
                  variant="outline"
                  size="lg"
                  onClick={() => enrich.mutate()}
                  disabled={enrich.isPending || readOnly}
                >
                  <RefreshCw aria-hidden />
                  Wzbogać ponownie
                </Button>
              </LoginRequired>
            )}
            <ExportMenu
              formats={['csv', 'json']}
              urlFor={(f) =>
                `/api/export/projects.${f}?rm_ids=${encodeURIComponent(card.id)}${f === 'csv' ? '&sep=semicolon' : ''}`
              }
              filename={(f) => `${card.id}.${f}`}
            />
          </>
        }
      />
      {card.auto_card ? (
        <div
          role="note"
          className="rounded-item border border-dashed border-attention bg-attention-soft px-4 py-3 text-[14px] text-attention-text"
        >
          Karta automatyczna z BZP, niezweryfikowana. Powstała z ogłoszeń i trafia do bazy przypadków dopiero
          po przeglądzie eksperta.
        </div>
      ) : null}
      <PillTabs tabs={tabs} label="Sekcje projektu" />
      <Outlet />
    </Page>
  )
}
