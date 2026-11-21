import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

/** Fails on serious/critical WCAG 2.1 A/AA violations; the map canvas is excluded (the list is the accessible path). */
export async function expectNoA11yViolations(page: Page, label = '') {
  const r = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .exclude('.maplibregl-canvas')
    .analyze()
  const bad = r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  const summary = bad.map((v) => `${v.id} (${v.impact}): ${v.nodes.length}x ${v.nodes[0]?.target.join(' ')}`)
  expect(summary, `axe ${label}`).toEqual([])
}
