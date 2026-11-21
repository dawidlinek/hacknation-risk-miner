import { describe, expect, it } from 'vitest'
import { tidyIssue } from './PulpitScreen'

describe('Pulpit discrepancy text', () => {
  it('a raw word list from the API reads as plain words', () => {
    expect(tidyIssue("odpowiada części [1] (wyróżniające słowa: [['100', '237', '435']])")).toBe(
      'odpowiada części [1] (wyróżniające słowa: 100, 237, 435)',
    )
  })
})
