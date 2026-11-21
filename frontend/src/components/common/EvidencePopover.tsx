// STUB from S0 (F1). Owner: F2 (frontend.md §3). Props are final; F2 fills in the lazy GET /api/evidence body.
import type { ReactNode } from 'react'
import type { EvidenceKey } from '@/api/contracts/common'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

export function EvidencePopover({ evidence, children }: { evidence: EvidenceKey; children: ReactNode }) {
  return (
    <Popover>
      <PopoverTrigger className="cursor-pointer rounded-chip text-left hover:underline" aria-label="Pokaż źródło">
        {children}
      </PopoverTrigger>
      <PopoverContent className="t-caption">
        <span className="t-mono text-muted">
          {evidence.claim_table} #{evidence.claim_id}
        </span>
      </PopoverContent>
    </Popover>
  )
}
