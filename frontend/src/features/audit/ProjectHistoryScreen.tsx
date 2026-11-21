import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import type { AuditEntry } from '@/api/contracts/audit'
import { DataState, EmptyState } from '@/components/common/DataState'
import { FilterPills } from '@/components/common/FilterPills'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { projectDiffQuery, projectHistoryQuery, restoreErrorMessage, useRestore } from './api'
import { filterByWho, historyStats, restoreConfirm, WHO_OPTIONS } from './logic'
import { AuditList, BeforeAfter } from './parts'
import type { WhoFilter } from './types'

function RestoreDialog({
  entry,
  busy,
  onCancel,
  onConfirm,
}: {
  entry: AuditEntry | null
  busy: boolean
  onCancel: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState('')
  return (
    <Dialog open={!!entry} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Przywrócić wartość?</DialogTitle>
          <DialogDescription>{entry ? restoreConfirm(entry) : ''}</DialogDescription>
        </DialogHeader>
        {entry ? <BeforeAfter before={entry.after} after={entry.before} /> : null}
        <div className="flex flex-col gap-1.5 text-[14px]">
          <label htmlFor="restore-reason">Powód przywrócenia</label>
          <Textarea
            id="restore-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Krótko, dlaczego wracamy do poprzedniej wartości"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Anuluj
          </Button>
          <Button disabled={busy || !reason.trim()} onClick={() => onConfirm(reason.trim())}>
            {busy ? 'Przywracamy…' : 'Przywróć'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ProjectHistoryScreen({
  id,
  who,
  onWho,
}: {
  id: string
  who: WhoFilter
  onWho: (w: WhoFilter) => void
}) {
  const { data } = useSuspenseQuery(projectHistoryQuery(id))
  const [from, setFrom] = useState<string | null>(null)
  const [target, setTarget] = useState<AuditEntry | null>(null)
  const restore = useRestore(id)
  const diff = useQuery(projectDiffQuery(id, from, data.current))
  const shown = filterByWho(data.entries, who)
  const stats = historyStats(data.entries, data.current)
  const older = data.versions.filter((v) => v.version !== data.current)

  const confirm = (reason: string) => {
    if (!target) return
    restore.mutate(
      { entryId: target.id, reason },
      {
        onSuccess: () => {
          toast.success('Przywrócono. Powstał nowy wpis w dzienniku.')
          setTarget(null)
        },
        onError: (e) => {
          toast.error(restoreErrorMessage(e))
          setTarget(null)
        },
      },
    )
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <FilterPills options={WHO_OPTIONS} value={who} onChange={onWho} label="Kto zmienił" />
        {older.length > 0 ? (
          <label className="ml-auto inline-flex items-center gap-2 text-[13px] text-text-secondary">
            Porównaj wersję
            <select
              value={from ?? ''}
              onChange={(e) => setFrom(e.target.value || null)}
              className="min-h-9 rounded-pill border border-border bg-surface px-2.5 text-[13px] font-medium"
            >
              <option value="">wybierz</option>
              {older.map((v) => (
                <option key={v.version} value={v.version}>
                  {v.label}
                </option>
              ))}
            </select>
            z bieżącą {data.current}
          </label>
        ) : null}
      </div>
      <p className="t-mono m-0 text-[12px] text-muted" data-testid="history-stats">
        Wersja rekordu {stats.version}, decyzje ekspertów {stats.expert}, propozycje modelu {stats.model},
        zmiany z systemu {stats.system}
      </p>

      {from ? (
        <section
          aria-label="Różnice między wersjami"
          className="flex flex-col gap-2 rounded-item bg-soft p-4"
        >
          <h2 className="t-h3 m-0">
            Zmiany od {from} do {data.current}
          </h2>
          <DataState query={diff} empty="Brak różnic w polach rekordu." isEmpty={(d) => d.length === 0}>
            {(rows) => (
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {rows.map((r, i) => (
                  <li key={`${r.field}-${i}`} className="flex flex-wrap items-center gap-2 text-[14px]">
                    <span className="t-mono text-muted">{r.field}</span>
                    <BeforeAfter before={r.before} after={r.after} />
                  </li>
                ))}
              </ul>
            )}
          </DataState>
        </section>
      ) : null}

      {shown.length === 0 ? (
        <EmptyState>Brak wpisów tego rodzaju.</EmptyState>
      ) : (
        <AuditList entries={shown} variant="project" label="Historia zmian projektu" onRestore={setTarget} />
      )}
      <span className="text-[12px] text-muted">
        Dziennik tylko do dopisywania. Przywrócenie też jest nowym wpisem.
      </span>
      <RestoreDialog
        entry={target}
        busy={restore.isPending}
        onCancel={() => setTarget(null)}
        onConfirm={confirm}
      />
    </>
  )
}
