import { describe, expect, it } from 'vitest'
import type { SimulationOut } from '@/api/contracts/simulation'
import demo from './__fixtures__/simulation.demo.json'
import {
  buildLines,
  chartAria,
  combinedKey,
  effectLine,
  endLabels,
  interp,
  inverse,
  inverseDesc,
  kpis,
  type Pt,
  parseChecked,
  subsetKey,
  summarySentence,
} from './scenario'

// captured from the engine (SAN, 7 mln zł, ZiW, 14 mies., FEnIKS): a real response, not a mock
const sim = demo as unknown as SimulationOut

describe('subset keys', () => {
  it('follows options order, not click order', () => {
    expect(sim.options.map((o) => o.key)).toEqual(['geo', 'plan18', 'k07', 'r08'])
    expect(subsetKey(sim.options, ['k07', 'geo'])).toBe('geo+k07')
    expect(subsetKey(sim.options, [])).toBe('')
    expect(Object.keys(sim.metrics.time.curves)).toHaveLength(16)
  })
  it('parses the URL param and drops unknown keys', () => {
    expect(parseChecked('k07,geo,zzz,geo', sim.options)).toEqual(['k07', 'geo'])
    expect(parseChecked(undefined, sim.options)).toEqual([])
  })
})

describe('interpolation helpers', () => {
  const up: Pt[] = [
    [0, 0],
    [10, 0.5],
    [20, 1],
  ]
  const down: Pt[] = [
    [1, 1],
    [2, 0.8],
    [3, 0.4],
  ]
  it('interp / inverse / inverseDesc', () => {
    expect(interp(up, 5)).toBeCloseTo(0.25)
    expect(interp(up, -1)).toBe(0)
    expect(interp(up, 99)).toBe(1)
    expect(inverse(up, 0.75)).toBeCloseTo(15)
    expect(inverseDesc(down, 0.6)).toBeCloseTo(2.5)
  })
})

describe('buildLines', () => {
  it('baseline only when nothing is checked', () => {
    const { lines } = buildLines(sim, 'time', [])
    expect(lines.map((l) => l.label)).toEqual(['Teraz'])
  })
  it('one line per checked option that affects the metric, plus "Razem" for two or more', () => {
    const t = buildLines(sim, 'time', ['geo', 'k07'])
    // k07 does not affect time: no own line and no "Razem"
    expect(t.lines.map((l) => l.key)).toEqual(['', 'geo'])
    const c = buildLines(sim, 'cost', ['geo', 'k07'])
    expect(c.lines.map((l) => l.key)).toEqual(['', 'geo', 'k07', 'geo+k07'])
    expect(c.lines.at(-1)?.label).toBe('Razem')
  })
  it('plan18 reads its KPI at the class median plan', () => {
    const { lines } = buildLines(sim, 'time', ['plan18'])
    const p = lines.find((l) => l.key === 'plan18')
    expect(p?.evalX).toBeGreaterThan(sim.metrics.time.eval_x)
  })
  it('reports a missing subset curve instead of drawing it', () => {
    const broken = {
      ...sim,
      metrics: { ...sim.metrics, cost: { ...sim.metrics.cost, curves: { '': sim.metrics.cost.curves[''] } } },
    }
    const r = buildLines(broken as SimulationOut, 'cost', ['geo', 'k07'])
    expect(r.missing).toEqual(['geo', 'k07', 'geo+k07'])
    expect(r.lines).toHaveLength(1)
  })
})

describe('KPIs (API values only)', () => {
  it('time baseline matches the engine golden ranges', () => {
    const k = kpis(sim, 'time', [])
    expect(k.map((x) => x.label)).toEqual([
      'W terminie z planu',
      'Połowa umów',
      '8 na 10 umów',
      'Po terminie programu',
    ])
    const pOn = interp(sim.metrics.time.curves[''] as Pt[], sim.metrics.time.eval_x)
    expect(pOn).toBeGreaterThan(0.3)
    expect(pOn).toBeLessThan(0.42)
    expect(k.every((x) => x.delta === '')).toBe(true)
  })
  it('deltas appear only when a checked option affects the metric', () => {
    expect(combinedKey(sim, 'time', ['k07'])).toBe('')
    expect(kpis(sim, 'time', ['k07']).every((x) => x.delta === '')).toBe(true)
    const cost = kpis(sim, 'cost', ['geo', 'k07', 'r08'])
    expect(cost[0].label).toBe('W budżecie + 10%')
    expect(cost.some((x) => x.delta !== '')).toBe(true)
  })
  it('late2 what-if moves the programme KPI', () => {
    const k = kpis(sim, 'time', [], { late2: true })
    expect(k[3].label).toContain('przetarg +2 mies.')
  })
  it('competition: P(>=2), median, single offer, cancellation', () => {
    const k = kpis(sim, 'comp', ['k07'])
    expect(k.map((x) => x.label)).toEqual([
      'Co najmniej 2 oferty',
      'Mediana ofert',
      'Tylko jedna oferta',
      'Unieważnienie',
    ])
    expect(k[0].tone).toBe('good')
    expect(k[3].delta).toMatch(/pp$/)
  })
})

describe('labels and copy', () => {
  it('end labels keep 16 px apart', () => {
    const { lines } = buildLines(sim, 'cost', ['geo', 'k07', 'r08'])
    const labels = endLabels(
      lines,
      'cost',
      (x) => x * 10,
      (y) => 250 - y * 230,
    )
    for (let i = 1; i < labels.length; i++) expect(labels[i].y - labels[i - 1].y).toBeGreaterThanOrEqual(16)
  })
  it('summary, aria and effect lines are Polish templates with no em dash', () => {
    const s = summarySentence(sim, 'time', ['geo'])
    expect(s).toMatch(
      /^Teraz skończysz w terminie z planu w \d+% przypadków\. Z zaznaczonymi zmianami: \d+%\.$/,
    )
    expect(summarySentence(sim, 'time', [])).toContain('Zaznacz zmianę')
    expect(chartAria(sim, 'cost', ['k07'])).toContain('ze zmianami')
    expect(effectLine(sim.options[2], 'time')).toBe('N-PRICE, bez wpływu na termin')
    for (const t of [s, chartAria(sim, 'time', ['geo'])])
      expect(t).not.toMatch(new RegExp(`[${String.fromCharCode(0x2014, 0xb7)}]`))
  })
})
