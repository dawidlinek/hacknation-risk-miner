import { describe, expect, it } from 'vitest'
import { resolveHotkey } from './hotkeys'

const ctx = { optionCount: 3, canSave: true, hasGold: true, index: 0, length: 5 }
const key = (k: string, target: EventTarget | null = document.body) => ({ key: k, target })

describe('review hotkeys', () => {
  it('picks options 1..n only within the option count', () => {
    expect(resolveHotkey(key('2'), ctx)).toEqual({ type: 'pick', index: 1 })
    expect(resolveHotkey(key('4'), ctx)).toBeNull()
  })
  it('ignores keys typed into inputs', () => {
    const input = document.createElement('input')
    expect(resolveHotkey(key('1', input), ctx)).toBeNull()
    expect(resolveHotkey(key('Enter', input), ctx)).toBeNull()
  })
  it('Enter saves only when valid', () => {
    expect(resolveHotkey(key('Enter'), ctx)).toEqual({ type: 'save' })
    expect(resolveHotkey(key('Enter'), { ...ctx, canSave: false })).toBeNull()
  })
  it('J and K wrap around', () => {
    expect(resolveHotkey(key('j'), { ...ctx, index: 4 })).toEqual({ type: 'move', to: 0 })
    expect(resolveHotkey(key('K'), ctx)).toEqual({ type: 'move', to: 4 })
  })
  it('G toggles gold only when the item has a gold row', () => {
    expect(resolveHotkey(key('g'), ctx)).toEqual({ type: 'gold' })
    expect(resolveHotkey(key('g'), { ...ctx, hasGold: false })).toBeNull()
  })
  it('ignores modified keys', () => {
    expect(resolveHotkey({ key: '1', target: document.body, ctrlKey: true }, ctx)).toBeNull()
  })
})
