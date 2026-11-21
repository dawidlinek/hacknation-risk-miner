import { Download } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { downloadFile } from '@/lib/download'

export type ExportFormat = 'docx' | 'pdf' | 'csv' | 'json' | 'md'
const LABEL: Record<ExportFormat, string> = { docx: 'DOCX', pdf: 'PDF', csv: 'CSV', json: 'JSON', md: 'Markdown' }

/** DropdownMenu of formats; `urlFor(fmt)` builds the endpoint, the file downloads via fetch → blob. */
export function ExportMenu({
  formats,
  urlFor,
  filename,
  label = 'Eksportuj',
  disabled,
}: {
  formats: ExportFormat[]
  urlFor: (f: ExportFormat) => string
  filename: (f: ExportFormat) => string
  label?: string
  disabled?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const run = async (f: ExportFormat) => {
    setBusy(true)
    try {
      await downloadFile(urlFor(f), filename(f))
    } catch {
      toast.error('Nie udało się przygotować pliku. Spróbuj ponownie.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled || busy}>
        <Button variant="outline" size="lg" aria-busy={busy}>
          <Download aria-hidden />
          {busy ? 'Przygotowujemy plik…' : label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {formats.map((f) => (
          <DropdownMenuItem key={f} onSelect={() => run(f)}>
            {LABEL[f]}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
