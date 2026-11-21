import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import type { AgentStep, AskAnswer } from "@/api/contracts/common";
import { OriginMarker } from "@/components/common/ProvenanceTag";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/download";
import { rowsCsvUrl, useSaveQuestion } from "./api";

/** "template:summary_v1" → "szablon (bez AI)", "llm" → "model AI", "sql" → "zapytanie SQL". */
export function methodLabel(m: string): string {
  if (m === "sql") return "zapytanie SQL do bazy umów";
  if (m === "llm") return "model AI na liczbach z tej analizy";
  if (m === "template" || m.startsWith("template:"))
    return "szablon na liczbach z bazy (bez AI)";
  return m;
}

const ROLE_ORIGIN = {
  obliczenie: "CALC",
  wniosek_ai: "AI",
  brak_danych: "SOURCE",
} as const;

/** Pattern 13: role label, text, bars, source chips, actions. */
export function ChatAnswer({
  answer,
  onSaved,
  compact,
  className,
}: {
  answer: AskAnswer;
  onSaved?: (code: string) => void;
  compact?: boolean;
  className?: string;
}) {
  const save = useSaveQuestion();
  const code = save.data?.code ?? answer.saved_id ?? null;
  const max =
    answer.scale_max ?? Math.max(...(answer.bars ?? []).map((b) => b.value), 1);
  const bars = answer.bars ?? [];
  return (
    <article
      className={cn("flex flex-col gap-3 rounded-card bg-soft p-4", className)}
    >
      <header className="flex flex-col gap-1">
        <span className="text-[14px] font-medium text-text-secondary">
          {answer.question}
        </span>
        <span className="t-mono inline-flex items-center gap-1.5 text-muted">
          <OriginMarker origin={ROLE_ORIGIN[answer.role]} />
          {answer.role_label}
        </span>
      </header>
      {answer.steps && answer.steps.length > 0 ? (
        <AgentSteps steps={answer.steps} />
      ) : null}
      <p className="m-0 text-[15px] leading-[1.55] whitespace-pre-line">
        {answer.text}
      </p>
      {bars.length > 0 ? (
        <ul
          className="m-0 flex list-none flex-col gap-1.5 p-0"
          aria-label="Zestawienie"
        >
          {bars.slice(0, compact ? 5 : 16).map((b) => (
            <li
              key={b.label}
              className="grid grid-cols-[minmax(110px,170px)_1fr_auto] items-center gap-3 text-[13px]"
            >
              <span className="truncate">{b.label}</span>
              <span
                aria-hidden
                className="h-2 overflow-hidden rounded-pill bg-soft-2"
              >
                <span
                  className={cn(
                    "block h-full",
                    b.attention ? "bg-attention" : "bg-text-secondary",
                  )}
                  style={{ width: `${Math.max(2, (b.value / max) * 100)}%` }}
                />
              </span>
              <span
                className={cn("t-mono", b.attention && "text-attention-text")}
              >
                {b.display}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {answer.sources.length > 0 ? (
        <div
          className="flex flex-wrap items-center gap-1.5 text-[12px]"
          aria-label="Źródła"
        >
          <span className="text-muted">Źródła:</span>
          {answer.sources.slice(0, 4).map((s) => (
            <span
              key={s}
              className="max-w-full truncate rounded-pill bg-surface px-2 py-0.5 text-text-secondary"
              title={s}
            >
              {s}
            </span>
          ))}
          {answer.sources.length > 4 ? (
            <span
              className="text-muted"
              title={answer.sources.slice(4).join("\n")}
            >
              +{answer.sources.length - 4}
            </span>
          ) : null}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {answer.actions.map((a) => {
          if (a.kind === "save") {
            return code ? (
              <span
                key="save"
                className="t-mono rounded-pill bg-surface px-3 py-1.5 text-text-secondary"
              >
                zapisano jako {code}
              </span>
            ) : (
              <Button
                key="save"
                variant="outline"
                size="sm"
                disabled={save.isPending}
                onClick={() =>
                  save.mutate(answer.id, {
                    onSuccess: (r) => {
                      toast.success(`Zapisano jako ${r.code}.`);
                      onSaved?.(r.code);
                    },
                    onError: () =>
                      toast.error("Nie udało się zapisać odpowiedzi."),
                  })
                }
              >
                {a.label}
              </Button>
            );
          }
          if (a.kind === "export_csv") {
            return code ? (
              <Button
                key="csv"
                variant="outline"
                size="sm"
                onClick={() =>
                  downloadFile(rowsCsvUrl(code), `${code}.csv`).catch(() =>
                    toast.error("Nie udało się pobrać pliku."),
                  )
                }
              >
                {a.label}
              </Button>
            ) : null;
          }
          return a.href ? (
            <Button key={a.label} variant="outline" size="sm" asChild>
              <Link to={a.href as never}>{a.label}</Link>
            </Button>
          ) : null;
        })}
      </div>
    </article>
  );
}

/** The agent's visible work: what it thinks it should do next and each tool it called, with a short result. */
export function AgentSteps({ steps }: { steps: AgentStep[] }) {
  return (
    <ol
      className="m-0 flex list-none flex-col gap-1.5 border-l-2 border-soft-2 p-0 pl-3 text-[13px]"
      aria-label="Kroki asystenta"
    >
      {steps.map((st, i) =>
        st.kind === "tool" ? (
          <li key={i} className="flex flex-col gap-0.5">
            <span className="flex flex-wrap items-center gap-1.5">
              <span className="t-mono rounded-pill bg-surface px-2 py-0.5 text-text-secondary">
                {st.label ?? st.tool}
              </span>
              {st.input ? (
                <span className="t-mono text-muted">{st.input}</span>
              ) : null}
            </span>
            {st.result ? (
              <span className="text-text-secondary">→ {st.result}</span>
            ) : null}
          </li>
        ) : (
          <li key={i} className="text-muted italic">
            {st.text}
          </li>
        ),
      )}
    </ol>
  );
}
