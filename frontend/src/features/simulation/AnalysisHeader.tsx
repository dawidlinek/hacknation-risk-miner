/** Section heading inside the analysis layout (routes/analizy/$id/route.tsx owns the H1, the record line and the tabs). */
export function AnalysisHeader({ title, lead }: { id?: string; title: string; lead?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <h2 className="t-h2 m-0">{title}</h2>
      {lead ? <p className="m-0 max-w-[720px] text-text-body-muted">{lead}</p> : null}
    </div>
  )
}
