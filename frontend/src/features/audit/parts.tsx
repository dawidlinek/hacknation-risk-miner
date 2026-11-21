import { Link } from '@tanstack/react-router'
import type { AuditEntry } from '@/api/contracts/audit'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { avatarOf, splitTime } from './logic'

export function BeforeAfter({
  before,
  after,
  note,
}: {
  before: string
  after: string
  note?: string | null
}) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <span className="t-mono rounded-[8px] bg-soft px-2 py-0.5 text-[12px] text-text-secondary line-through">
        {before}
      </span>
      <span aria-hidden className="text-prov-source">
        →
      </span>
      <span className="t-mono rounded-[8px] bg-soft px-2 py-0.5 text-[12px]">{after}</span>
      {note ? <span className="text-[13px] text-text-secondary">{note}</span> : null}
    </span>
  )
}

function Avatar({ actor }: { actor: AuditEntry['actor'] }) {
  const a = avatarOf(actor)
  return (
    <span
      aria-hidden
      data-actor={actor}
      className={cn('inline-flex size-9.5 items-center justify-center text-[14px] font-semibold', a.cls)}
    >
      {a.letter}
    </span>
  )
}

const ACTOR_NAME: Record<AuditEntry['actor'], string> = {
  expert: 'ekspert',
  model: 'model',
  system: 'system',
}

/**
 * One audit entry. `project`: time + date, version and "Przywróć". `global`: time only, object link, note and the entry id.
 */
export function AuditRow({
  entry,
  variant,
  onRestore,
  restoreDisabled,
}: {
  entry: AuditEntry
  variant: 'project' | 'global'
  onRestore?: (e: AuditEntry) => void
  restoreDisabled?: string
}) {
  const t = splitTime(entry.at)
  const global = variant === 'global'
  return (
    <li
      className={cn(
        'grid items-start gap-3.5 rounded-item border border-divider px-4 py-3.5',
        global ? 'grid-cols-[64px_38px_minmax(0,1fr)_auto]' : 'grid-cols-[110px_38px_minmax(0,1fr)_auto]',
      )}
    >
      <span className="flex flex-col gap-0.5 pt-0.5">
        <time dateTime={entry.at} className="t-mono text-[13px] font-semibold">
          {t.time}
        </time>
        {global ? null : <span className="t-mono text-[11.5px] text-muted">{t.date}</span>}
      </span>
      <Avatar actor={entry.actor} />
      <span className="flex min-w-0 flex-col gap-1.5">
        <span className="text-[15px]">
          <strong className="font-semibold">{entry.actor_label}</strong> {entry.action}
          {global && entry.object ? (
            <>
              {' '}
              {entry.object.href ? (
                <Link to={entry.object.href as never} className="font-medium">
                  {entry.object.label}
                </Link>
              ) : (
                <span className="font-medium">{entry.object.label}</span>
              )}
            </>
          ) : null}
        </span>
        <BeforeAfter before={entry.before} after={entry.after} note={global ? entry.note : null} />
        {global ? null : entry.why ? (
          <span className="text-[13px] text-text-body-muted">{entry.why}</span>
        ) : null}
      </span>
      <span className="flex flex-col items-end gap-1.5">
        <span className="t-mono text-[12px] text-muted whitespace-nowrap">
          {global ? entry.ref : entry.version}
        </span>
        {!global && entry.restorable && onRestore ? (
          <Button
            variant="outline"
            size="sm"
            disabled={!!restoreDisabled}
            title={restoreDisabled}
            onClick={() => onRestore(entry)}
            aria-label={`Przywróć wartość sprzed zmiany ${entry.version}, ${ACTOR_NAME[entry.actor]}`}
          >
            Przywróć
          </Button>
        ) : null}
      </span>
    </li>
  )
}

export function AuditList({
  entries,
  variant,
  onRestore,
  restoreDisabled,
  label,
}: {
  entries: AuditEntry[]
  variant: 'project' | 'global'
  onRestore?: (e: AuditEntry) => void
  restoreDisabled?: string
  label: string
}) {
  return (
    <ul aria-label={label} className="m-0 flex list-none flex-col gap-2 p-0">
      {entries.map((e) => (
        <AuditRow
          key={e.id}
          entry={e}
          variant={variant}
          onRestore={onRestore}
          restoreDisabled={restoreDisabled}
        />
      ))}
    </ul>
  )
}
