import { describe, expect, it } from 'vitest'
import { adaptGraph, type RealGraph } from '@/api/adapters/graph'
import type { FlowLink, FlowNode } from '@/api/contracts/graph'
import { bandColor, feedsOf, flowOpacity, linkStage, nodeMap, spreadLabels } from './logic'

const n = (
  id: string,
  column: 0 | 1 | 2,
  role: FlowNode['role'],
  extra: Partial<FlowNode> = {},
): FlowNode => ({
  id,
  column,
  label: id,
  sub: '',
  role,
  selectable: column === 2,
  ...extra,
})
const nodes = [
  n('zs', 0, 'organiser'),
  n('ai', 0, 'ai'),
  n('pr', 1, 'group'),
  n('um', 1, 'group'),
  n('r4', 2, 'conclusion', { origin: 'AI' }),
  n('cost', 2, 'conclusion', { origin: 'CALC' }),
]
const map = nodeMap({ nodes, links: [], details: {}, overview: { kind: '', title: '', rows: [] } })
const links: FlowLink[] = [
  { source: 'zs', target: 'um', value: 1 },
  { source: 'ai', target: 'pr', value: 2 },
  { source: 'pr', target: 'r4', value: 2 },
  { source: 'um', target: 'cost', value: 1 },
]

describe('flowOpacity', () => {
  it('nothing selected: stage 1 at 0.28, stage 2 at 0.22', () => {
    const feeds = feedsOf(links, null)
    expect(flowOpacity(links[0], linkStage(links[0], map), null, feeds)).toBe(0.28)
    expect(flowOpacity(links[2], linkStage(links[2], map), null, feeds)).toBe(0.22)
  })
  it('selected conclusion lights its path and dims the rest', () => {
    const feeds = feedsOf(links, 'r4')
    expect([...feeds]).toEqual(['pr'])
    expect(flowOpacity(links[2], 2, 'r4', feeds)).toBe(0.55)
    expect(flowOpacity(links[3], 2, 'r4', feeds)).toBe(0.06)
    expect(flowOpacity(links[1], 1, 'r4', feeds)).toBe(0.5)
    expect(flowOpacity(links[0], 1, 'r4', feeds)).toBe(0.08)
  })
})

describe('bandColor', () => {
  it('stage 1 by source role, stage 2 violet for AI conclusions', () => {
    expect(bandColor(links[0], 1, map)).toBe('ink')
    expect(bandColor(links[1], 1, map)).toBe('ai')
    expect(bandColor(links[2], 2, map)).toBe('ai')
    expect(bandColor(links[3], 2, map)).toBe('source')
  })
})

describe('spreadLabels', () => {
  it('keeps order, enforces the gap and stays inside the bounds', () => {
    const out = spreadLabels([100, 105, 110, 400], 40, 0, 500)
    expect(out[1] - out[0]).toBeGreaterThanOrEqual(40)
    expect(out[2] - out[1]).toBeGreaterThanOrEqual(40)
    expect(out[3]).toBe(400)
    expect(spreadLabels([490, 495, 499], 40, 0, 500).at(-1)).toBeLessThanOrEqual(500)
  })
  it('preserves the input order of the result', () => {
    const out = spreadLabels([300, 100], 50)
    expect(out[0]).toBe(300)
    expect(out[1]).toBe(100)
  })
})

describe('adaptGraph', () => {
  const raw: RealGraph = {
    nodes: [
      { id: 'src:xlsx', column: 0, label: 'Zestaw', sub: 'XLSX', role: 'source' },
      { id: 'fact:um', column: 1, label: 'Umowa', sub: '2 fakty' },
      {
        id: 'concl:R01',
        column: 2,
        label: 'R01',
        sub: 'wniosek AI',
        role: 'ai',
        review_status: 'proposed',
        review_item_id: 2801,
      },
    ],
    links: [{ source: 'src:xlsx', target: 'fact:um', value: 2 }],
    details: {
      'concl:R01': {
        kind: 'wniosek',
        title: 'R01',
        rows: [{ k: 'skąd', v: 'x' }],
        cta: { label: 'Sprawdź', href: '/przeglad?item=2801' },
      },
    },
    summary: { facts: 1, conclusions: 3, by_role: { source: 1 } },
  }
  it('maps roles, selectable conclusions and the review item', () => {
    const f = adaptGraph(raw)
    expect(f.nodes.map((x) => x.role)).toEqual(['organiser', 'group', 'conclusion'])
    expect(f.nodes[2].selectable).toBe(true)
    expect(f.details['concl:R01'].review_item_id).toBe(2801)
    expect(f.overview.title).toBe('1 fakt, 3 wnioski')
  })
})
