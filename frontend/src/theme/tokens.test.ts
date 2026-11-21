import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import local from './tokens.json'

describe('tokens', () => {
  it('src/theme/tokens.json equals design/tokens.json', () => {
    const design = JSON.parse(readFileSync(resolve(__dirname, '../../../design/tokens.json'), 'utf8'))
    expect(local).toEqual(design)
  })
  it('every light colour role has a CSS variable', () => {
    const css = readFileSync(resolve(__dirname, '../index.css'), 'utf8')
    for (const k of Object.keys(local.color.light)) {
      if (typeof (local.color.light as Record<string, unknown>)[k] !== 'string' || k === 'focus') continue
      expect(css, k).toContain(`--${k}:`)
    }
  })
})
