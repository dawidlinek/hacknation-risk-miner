import { describe, expect, it } from 'vitest'
import { type CardProposal, proposalEvidence, questionOnly } from './context'

describe('questionOnly', () => {
  it('drops the subject the backend appended to the question', () => {
    expect(questionOnly('Które ryzyko opisuje to zdarzenie? Inspekcja sieci', 'Inspekcja sieci')).toBe(
      'Które ryzyko opisuje to zdarzenie?',
    )
  })
  it('keeps a question that is the subject itself', () => {
    expect(questionOnly('Inspekcja sieci', 'Inspekcja sieci')).toBe('Inspekcja sieci')
    expect(questionOnly('Czy to postępowanie?', null)).toBe('Czy to postępowanie?')
  })
})

const base: CardProposal = {
  code: 'R16',
  name: 'Warunki atmosferyczne',
  description: null,
  sector: 'wod-kan',
  sector_label: 'wodociągi i kanalizacja',
  copied_from_wodkan: false,
  parent_code: null,
  rationale: null,
  proposed_by: null,
  events: [],
  cases: { texts: 1604, changes: 1823, codes: ['R16'] },
  empirical: {
    n: 345,
    source: 'BZP_2022_2026',
    category: 'warunki atmosferyczne',
    p_late: null,
    delay_p50: 64,
    delay_p75: 131,
    cost_p75: 0.027,
    cost_p90: 0.11,
  },
  signals: [],
  clauses: [],
  mitigations: [],
  examples: [],
  closest: [],
}

// em dash, middle dot and raw underscores must not reach the copy
const BANNED = /[\u2014\u00b7_]/

describe('proposalEvidence', () => {
  it('says how many cases stand behind the proposal, in plain Polish', () => {
    const [cases, bzp] = proposalEvidence(base)
    expect(cases).toContain('temu ryzyku')
    expect(cases).toMatch(/1\s604 opisów przyczyn zmian umów \(1\s823 zmian w BZP\)/)
    expect(bzp).toContain('(2022–2026)')
    expect(bzp).toContain('mediana wydłużenia terminu 64 dni')
    expect(bzp).not.toMatch(BANNED)
  })
  it('names the example codes when the cases come from other codes', () => {
    const [cases] = proposalEvidence({
      ...base,
      empirical: null,
      cases: { texts: 111, changes: 124, codes: ['N-LAW'] },
    })
    expect(cases).toContain('kodom N-LAW')
  })
})
