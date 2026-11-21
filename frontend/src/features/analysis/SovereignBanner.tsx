import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { makeDocumentPublic } from './api'

export const SOVEREIGN_TITLE =
  'Model suwerenny niedostępny: dokument poufny przetworzono tylko regułami, bez AI.'
export const SOVEREIGN_HINT =
  'Jeśli dokument jest publiczny (np. pobrany z BZP), oznacz go jako publiczny, a AI przetworzy go ponownie.'
export const MAKE_PUBLIC_LABEL = 'Oznacz jako publiczny i przetwórz ponownie'

/** Shown on 1.1 and 1.3 when a confidential document met a sovereign-model outage. Confidential text never goes to
 * the cloud; the owner may re-run it as a public document with one click. */
export function SovereignBanner({ id, documentIds }: { id: string; documentIds: number[] }) {
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: async () => {
      for (const d of documentIds) await makeDocumentPublic(id, d)
    },
    onSuccess: () => {
      toast.success('Dokument oznaczony jako publiczny. AI czyta go ponownie.')
      void qc.invalidateQueries({ queryKey: ['analysis', id] })
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError && e.status === 403
          ? 'Tylko autor analizy może zmienić oznaczenie dokumentu.'
          : 'Nie udało się zmienić oznaczenia dokumentu. Spróbuj ponownie.',
      ),
  })
  return (
    <div
      className="flex flex-col gap-2 rounded-item bg-attention-soft px-4 py-3 text-attention-text"
      role="status"
      data-testid="sovereign-banner"
    >
      <p className="t-small m-0 font-medium">{SOVEREIGN_TITLE}</p>
      <p className="t-small m-0">
        Uwagi i cechy z reguł są dostępne. {documentIds.length ? SOVEREIGN_HINT : ''}
      </p>
      {documentIds.length ? (
        <div>
          <Button type="button" size="sm" variant="outline" disabled={m.isPending} onClick={() => m.mutate()}>
            {m.isPending ? 'Zmieniamy oznaczenie…' : MAKE_PUBLIC_LABEL}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
