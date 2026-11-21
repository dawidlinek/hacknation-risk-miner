// Polish formatters (frontend.md §1.9). Every number goes through here: Intl pl-PL does not group
// 4-digit numbers, the design does, so grouping is forced and group spaces become NBSP.
export const NBSP = ' '
export const MINUS = '−'
export const EMPTY = 'brak'

type Num = string | number | null | undefined

export function toNum(x: Num): number | null {
  if (x === null || x === undefined || x === '') return null
  const n = typeof x === 'number' ? x : Number(x)
  return Number.isFinite(n) ? n : null
}

const nbsp = (s: string) => s.replace(/[  ]/g, NBSP)
const fixMinus = (s: string) => s.replace(/^-/, MINUS).replace(/-/g, MINUS)

function nf(digits: number, minDigits = digits) {
  return new Intl.NumberFormat('pl-PL', {
    useGrouping: 'always' as unknown as boolean,
    minimumFractionDigits: minDigits,
    maximumFractionDigits: digits,
  })
}

function core(x: number, digits: number, minDigits = digits) {
  return fixMinus(nbsp(nf(digits, minDigits).format(x)))
}

export function fmtInt(n: Num): string {
  const v = toNum(n)
  return v === null ? EMPTY : core(Math.round(v), 0)
}

export function fmtDec(x: Num, digits = 1): string {
  const v = toNum(x)
  return v === null ? EMPTY : core(v, digits)
}

/** Up to `digits` decimals, trailing zeros dropped (`16.3` → `16,3`, `14` → `14`). */
export function fmtNum(x: Num, digits = 1): string {
  const v = toNum(x)
  return v === null ? EMPTY : core(v, digits, 0)
}

export interface MoneyLike {
  amount: string | number | null
  currency?: string | null
  vat_basis?: 'net' | 'gross' | 'unknown' | null
}

export function fmtMoney(m: MoneyLike | null | undefined, opts: { vat?: boolean; digits?: number } = {}): string {
  const v = toNum(m?.amount)
  if (!m || v === null) return EMPTY
  const digits = opts.digits ?? 2
  const cur = !m.currency || m.currency === 'PLN' ? 'zł' : m.currency
  let s = `${core(v, digits)}${NBSP}${cur}`
  if (opts.vat && m.vat_basis === 'gross') s += ' brutto'
  if (opts.vat && m.vat_basis === 'net') s += ' netto'
  return s
}

const SHORT_UNITS = { tys: 'tys.', mln: 'mln', mld: 'mld' } as const
export function fmtMoneyShort(x: Num, unit: keyof typeof SHORT_UNITS = 'mln', digits = 2): string {
  const v = toNum(x)
  if (v === null) return EMPTY
  return `${fmtNum(v, digits)}${NBSP}${SHORT_UNITS[unit]}${NBSP}zł`
}

/** Pick the unit automatically from a PLN amount. */
export function fmtPlnAuto(x: Num): string {
  const v = toNum(x)
  if (v === null) return EMPTY
  const a = Math.abs(v)
  if (a >= 1e9) return fmtMoneyShort(v / 1e9, 'mld', 1)
  if (a >= 1e6) return fmtMoneyShort(v / 1e6, 'mln', 2)
  if (a >= 1e3) return fmtMoneyShort(v / 1e3, 'tys', 0)
  return `${fmtInt(v)}${NBSP}zł`
}

export function fmtPct(x: Num, opts: { signed?: boolean; digits?: number; fromShare?: boolean } = {}): string {
  let v = toNum(x)
  if (v === null) return EMPTY
  if (opts.fromShare) v *= 100
  const digits = opts.digits ?? (opts.fromShare ? 0 : 1)
  const body = core(Math.abs(v), digits, 0)
  const sign = v < 0 ? MINUS : opts.signed && v > 0 ? '+' : ''
  return `${sign}${body}%`
}

export function fmtPp(d: Num): string {
  const v = toNum(d)
  if (v === null || Math.round(v) === 0) return ''
  const r = Math.round(v)
  return `${r > 0 ? '+' : MINUS}${Math.abs(r)}${NBSP}pp`
}

export function fmtDays(n: Num, opts: { short?: boolean; signed?: boolean } = {}): string {
  const v = toNum(n)
  if (v === null) return EMPTY
  const r = Math.round(v)
  const signed = opts.signed ?? true
  const sign = r < 0 ? MINUS : signed && r > 0 ? '+' : ''
  const abs = core(Math.abs(r), 0)
  const unit = opts.short ? 'd' : Math.abs(r) === 1 ? 'dzień' : 'dni'
  return `${sign}${abs}${NBSP}${unit}`
}

export function fmtMonths(x: Num, digits = 1): string {
  const v = toNum(x)
  return v === null ? EMPTY : `${fmtNum(v, digits)}${NBSP}mies.`
}

export function fmtN(n: Num | [Num, Num]): string {
  if (Array.isArray(n)) return `n${NBSP}=${NBSP}${fmtInt(n[0])} i ${fmtInt(n[1])}`
  return `n${NBSP}=${NBSP}${fmtInt(n)}`
}

export const MIN_N = 10
export function isInsufficient(n: Num, min = MIN_N): boolean {
  const v = toNum(n)
  return v === null || v < min
}

export function fmtScore(x: Num): string {
  return fmtDec(x, 2)
}

export function fmtBzp(s: string | null | undefined): string {
  return s ? s : EMPTY
}

export function fmtNip(s: string | null | undefined): string {
  if (!s) return EMPTY
  const d = s.replace(/\D/g, '')
  if (d.length !== 10) return s
  return `${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6, 8)} ${d.slice(8)}`.replace(/ /g, NBSP)
}
