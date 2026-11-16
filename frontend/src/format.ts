const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const sign = (v: number) => (v > 0 ? '+' : '')
const loc = (v: number, d: number) => v.toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d })

/** Signed percentage from a fraction: 0.0123 -> "+1.23%" */
export const pct = (v: unknown, d = 2) => (isNum(v) ? `${sign(v)}${loc(v * 100, d)}%` : 'n/a')
/** Drawdown (never signed): -0.058 -> "-5.8%" */
export const dd = (v: unknown) => (isNum(v) ? `${loc(v * 100, 1)}%` : 'n/a')
/** Unsigned share: 0.75 -> "75%" */
export const share = (v: unknown) => (isNum(v) ? `${Math.round(v * 100)}%` : 'n/a')
export const bp = (v: unknown, d = 1) => (isNum(v) ? `${sign(v)}${loc(v, d)} bp` : 'n/a')
export const usd = (v: unknown, d = 2) => (isNum(v) ? loc(v, d) : 'n/a')
export const num = (v: unknown, d = 2) => (isNum(v) ? loc(v, d) : typeof v === 'string' ? v : '')
export const int = (v: unknown) => (isNum(v) ? loc(v, 0) : typeof v === 'string' ? v : '')

/** Default table-cell formatting: numbers to 2 dp (integers as-is), strings as-is, blanks empty. */
export function cell(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (isNum(v)) return Number.isInteger(v) ? loc(v, 0) : loc(v, 2)
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return String(v)
}

export const dateShort = (iso: string | number) => new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' })
export const dateLong = (iso: string | number) => new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' })
export const utc = (iso: string | null | undefined) => {
  if (!iso) return 'n/a'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.toISOString().slice(0, 16).replace('T', ' ')} UTC`
}
export const hours = (v: unknown) => (isNum(v) ? `${loc(v, 1)} h` : 'n/a')
