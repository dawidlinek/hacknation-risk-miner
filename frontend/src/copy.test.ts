import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function files(dir: string): string[] {
  let out: string[] = []
  let entries: string[] = []
  try {
    entries = readdirSync(dir)
  } catch {
    return out
  }
  for (const n of entries) {
    if (n === 'routeTree.gen.ts' || n === 'schema.gen.ts' || n === 'node_modules') continue
    const p = join(dir, n)
    if (statSync(p).isDirectory()) out = out.concat(files(p))
    else if (/\.(tsx?|json|css)$/.test(n)) out.push(p)
  }
  return out
}

describe('copy rules', () => {
  it('no em dash (U+2014) or middle dot (U+00B7) in src/ and e2e/', () => {
    const root = resolve(__dirname, '..')
    const bad: string[] = []
    for (const f of [...files(join(root, 'src')), ...files(join(root, 'e2e'))]) {
      readFileSync(f, 'utf8')
        .split('\n')
        .forEach((l: string, i: number) => {
          if (/[\u2014\u00B7]/.test(l)) bad.push(`${f.slice(root.length + 1)}:${i + 1}`)
        })
    }
    expect(bad).toEqual([])
  })
})
