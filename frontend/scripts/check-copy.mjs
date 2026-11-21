// Fails when U+2014 (em dash) or U+00B7 (middle dot) appears in src/ or e2e/ (README §9 copy rule).
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const roots = ['src', 'e2e']
const banned = [new RegExp('\\u2014'), new RegExp('\\u00B7')]
const skip = new Set(['node_modules', 'routeTree.gen.ts', 'schema.gen.ts'])
let bad = 0
function walk(dir) {
  let entries
  try { entries = readdirSync(dir) } catch { return }
  for (const name of entries) {
    if (skip.has(name)) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) { walk(p); continue }
    if (!/\.(tsx?|mjs|json|css|html)$/.test(name)) continue
    readFileSync(p, 'utf8').split('\n').forEach((line, i) => {
      if (banned.some((re) => re.test(line))) { bad++; console.error(`${p}:${i + 1}: ${line.trim().slice(0, 120)}`) }
    })
  }
}
roots.forEach(walk)
if (bad) { console.error(`\n${bad} line(s) with U+2014 or U+00B7`); process.exit(1) }
console.log('copy check: ok')
