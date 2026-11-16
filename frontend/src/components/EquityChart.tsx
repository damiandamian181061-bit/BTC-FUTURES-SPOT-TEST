import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from 'recharts'
import type { Point } from '../types'
import { dateLong, dateShort } from '../format'

export type SeriesKey = 'paper' | 'expected' | 'bh'
export interface Series { key: SeriesKey; name: string; pts: Point[] }
interface RowT { t: number; paper?: number; expected?: number; bh?: number }

const DAY = 86_400_000
const fmt = (v: number, dec: number) => `${v > 0 ? '+' : ''}${v.toFixed(dec)}%`

/** 1 / 2 / 2.5 / 5 x 10^n: the smallest clean step giving about n ticks over `span`. */
function niceStep(span: number, n = 5) {
  const raw = Math.max(span, 1e-9) / n
  const mag = 10 ** Math.floor(Math.log10(raw))
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * mag) return m * mag
  return 10 * mag
}

/** Symmetric-enough y range around the data and the 0% baseline, on clean ticks (Recharts' auto domain misfires on one point). */
function yScale(vals: number[]) {
  const minV = Math.min(0, ...vals)
  const maxV = Math.max(0, ...vals)
  const pad = Math.max((maxV - minV) * 0.1, 0.2)
  const step = niceStep(maxV - minV + 2 * pad)
  const lo = Math.floor((minV - pad) / step) * step
  const hi = Math.ceil((maxV + pad) / step) * step
  const ticks: number[] = []
  for (let v = lo; v <= hi + 1e-9; v += step) ticks.push(Number(v.toFixed(6)))
  const dec = step >= 1 ? 0 : step >= 0.1 ? 1 : 2
  return { lo, hi, ticks, dec }
}

/**
 * Growth-since-start lines: paper (solid, series-1), expected (dashed, grey), buy & hold (dashed, series-2).
 * Colours come from CSS variables via the series-* classes, so light and dark modes both validate.
 */
export function EquityChart({ title, series }: { title: string; series: Series[] }) {
  const live = series.filter((s) => s.pts.length > 0)
  if (!live.length) {
    return (
      <figure className="chart chart-empty">
        <figcaption><strong>{title}</strong></figcaption>
        <p className="muted small">No equity history yet: the curve starts with the first daily snapshot.</p>
      </figure>
    )
  }
  const byT = new Map<number, RowT>()
  for (const s of live) {
    for (const [iso, v] of s.pts) {
      const t = Date.parse(iso)
      const row = byT.get(t) ?? { t }
      row[s.key] = (v - 1) * 100
      byT.set(t, row)
    }
  }
  const rows = [...byT.values()].sort((a, b) => a.t - b.t)
  const single = rows.length === 1
  const vals = rows.flatMap((r) => [r.paper, r.expected, r.bh]).filter((v): v is number => v !== undefined)
  const { lo, hi, ticks, dec } = yScale(vals)
  return (
    <figure className="chart">
      <figcaption>
        <strong>{title}</strong>
        {live.length > 1 && (
          <ul className="legend" aria-label="series">
            {live.map((s) => (
              <li key={s.key}><span className={`key series-${s.key}`} />{s.name}</li>
            ))}
          </ul>
        )}
      </figcaption>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis
            dataKey="t" type="number" scale="time" tickLine={false} minTickGap={48}
            domain={single ? [rows[0].t - DAY, rows[0].t + DAY] : ['dataMin', 'dataMax']}
            tickFormatter={(t: number) => dateShort(t)}
          />
          <YAxis width={58} axisLine={false} tickLine={false} domain={[lo, hi]} ticks={ticks} tickFormatter={(v: number) => fmt(v, dec)} />
          <ReferenceLine y={0} className="baseline" />
          <Tooltip content={<ChartTip series={live} dec={dec} />} isAnimationActive={false} />
          {live.map((s) => (
            <Line
              key={s.key} dataKey={s.key} name={s.name} className={`series-${s.key}`} type="linear" strokeWidth={2}
              strokeDasharray={s.key === 'paper' ? undefined : '6 4'} connectNulls isAnimationActive={false}
              dot={single ? { r: 4, strokeWidth: 2 } : false} activeDot={{ r: 4, strokeWidth: 2 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </figure>
  )
}

function ChartTip({ active, payload, label, series, dec }: TooltipProps<number, string> & { series: Series[]; dec: number }) {
  if (!active || !payload?.length) return null
  const t = typeof label === 'number' ? label : Number(label)
  return (
    <div className="tip" role="status">
      <div className="tip-date">{Number.isFinite(t) ? dateLong(t) : ''}</div>
      {series.map((s) => {
        const p = payload.find((x) => x.dataKey === s.key)
        if (!p || typeof p.value !== 'number') return null
        return (
          <div key={s.key} className="tip-row">
            <span className={`key series-${s.key}`} />
            <strong>{fmt(p.value, dec)}</strong>
            <span className="muted">{s.name}</span>
          </div>
        )
      })}
    </div>
  )
}
