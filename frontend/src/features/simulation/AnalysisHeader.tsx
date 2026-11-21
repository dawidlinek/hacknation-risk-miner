import { PageHeader } from '@/app/Page'

/** Section heading inside the analysis layout (routes/analizy/$id/route.tsx owns the record line and the tabs). */
export function AnalysisHeader({ title, lead }: { id?: string; title: string; lead?: string }) {
  return <PageHeader title={title} lead={lead} />
}
