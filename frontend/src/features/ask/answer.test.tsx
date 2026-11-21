import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { adaptAnswer, type RealAnswer } from './api'
import { ChatAnswer, methodLabel } from './ChatAnswer'

const raw: RealAnswer = {
  id: 'a1',
  code: null,
  role: 'calc',
  role_label: 'obliczenie',
  text: 'W tej grupie 63% umów skończyło się po terminie.',
  bars: [],
  method: { kind: 'template', sql: null, template: 'template:report_chat_v1' },
  sources: [{ kind: 'query', id: 'rc', label: 'klasa: 82 umowy' }],
  n: 82,
  missing: [],
  actions: [{ kind: 'save', label: 'Zapisz jako rekord', href: null }],
}

describe('ChatAnswer (pattern 13)', () => {
  it('method labels', () => {
    expect(methodLabel('sql')).toMatch(/SQL/)
    expect(methodLabel('template:summary_v1')).toMatch(/bez AI/)
    expect(methodLabel('llm')).toMatch(/model AI/)
  })
  it('template answers show the n chip and the save action, without a method block', () => {
    const a = adaptAnswer(raw, 'Dlaczego taka szansa na termin?')
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ChatAnswer answer={a} />
      </QueryClientProvider>,
    )
    expect(screen.queryByText('Jak to policzyłem')).not.toBeInTheDocument()
    expect(screen.queryByText(/szablon na liczbach z bazy/)).not.toBeInTheDocument()
    expect(screen.getByText('n = 82')).toBeInTheDocument()
    expect(screen.getByText('obliczenie')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zapisz jako rekord' })).toBeInTheDocument()
  })
})
