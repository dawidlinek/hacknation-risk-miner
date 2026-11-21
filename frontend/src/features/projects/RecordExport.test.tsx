import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { downloadFile } from '@/lib/download'
import { ProjectRecordExport, projectRecordExportUrl } from './RecordExport'

vi.mock('@/lib/download', () => ({ downloadFile: vi.fn(async (_u: string, name: string) => name) }))

describe('Eksportuj rekord', () => {
  beforeEach(() => vi.mocked(downloadFile).mockClear())

  it('builds the per-project export URL', () => {
    expect(projectRecordExportUrl('RM-2026-023', 'pdf')).toBe('/api/projects/RM-2026-023/export.pdf')
    expect(projectRecordExportUrl('ocds-148610-a/b', 'md')).toBe('/api/projects/ocds-148610-a%2Fb/export.md')
  })

  it('offers PDF, DOCX, Markdown and JSON and downloads the chosen one', async () => {
    const user = userEvent.setup()
    render(<ProjectRecordExport id="RM-2026-023" />)
    await user.click(screen.getByRole('button', { name: /Eksportuj rekord/ }))
    for (const label of ['PDF', 'DOCX', 'Markdown', 'JSON']) {
      expect(await screen.findByRole('menuitem', { name: label })).toBeInTheDocument()
    }
    await user.click(screen.getByRole('menuitem', { name: 'Markdown' }))
    await waitFor(() =>
      expect(downloadFile).toHaveBeenCalledWith(
        '/api/projects/RM-2026-023/export.md',
        'rekord_RM-2026-023.md',
      ),
    )
  })
})
