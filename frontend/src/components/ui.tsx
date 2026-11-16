import type { ReactNode } from 'react'
import { cell } from '../format'

/** Colour class for any status word the Python side emits (kill switches, run grid, ledger statuses). */
export function statusClass(s: string | null | undefined): 'ok' | 'warn' | 'bad' | 'na' {
  switch (s) {
    case 'ok': case 'OK': case 'now': case 'CLOSED': case 'ENTERED': case 'ALLOWED': case 'SWITCHED': case 'MAKER': case 'LONG': case 'ON': case 'INFO': case 'NO_NEW':
      return 'ok'
    case 'warn': case 'NO_TRADE': case 'UNFILLED': case 'MIXED': case 'MARKET': case 'WARN':
      return 'warn'
    case 'bad': case 'MISSED': case 'ERROR': case 'MISSING': case 'STILL_OPEN': case 'MISSED_MACHINE_OFF': case 'SWITCH_INCOMPLETE': case 'FAILED': case 'NO_NETWORK':
      return 'bad'
    default:
      return 'na'
  }
}

const ICON = { ok: '✓', warn: '⚠', bad: '✕', na: '–' } as const

export function Badge({ status, children, icon = false, title }: { status?: string | null; children: ReactNode; icon?: boolean; title?: string }) {
  const cls = statusClass(status ?? (typeof children === 'string' ? children : null))
  return (
    <span className={`badge ${cls}`} title={title}>
      {icon && <span aria-hidden="true" className="badge-icon">{ICON[cls]}</span>}
      {children}
    </span>
  )
}

export function Tile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  )
}

export function Section({ id, title, children, intro }: { id: string; title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section className="card" id={id} aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>{title}</h2>
      {intro && <p className="intro small">{intro}</p>}
      {children}
    </section>
  )
}

export interface Col<T> {
  key: string
  label: string
  render?: (row: T) => ReactNode
  align?: 'left' | 'right' | 'center'
  wrap?: boolean
}

export function DataTable<T extends object>({ cols, rows, rowKey, empty = 'nothing logged yet', className = '' }: {
  cols: Col<T>[]
  rows: T[]
  rowKey: (row: T, i: number) => string
  empty?: string
  className?: string
}) {
  if (!rows.length) return <p className="muted small">{empty}</p>
  return (
    <div className="scroll">
      <table className={className}>
        <thead>
          <tr>{cols.map((c) => <th key={c.key} className={c.align ?? ''}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey(r, i)}>
              {cols.map((c) => (
                <td key={c.key} className={`${c.align ?? ''}${c.wrap ? ' wrap' : ''}`}>
                  {c.render ? c.render(r) : cell((r as Record<string, unknown>)[c.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
