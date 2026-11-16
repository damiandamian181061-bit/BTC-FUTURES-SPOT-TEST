import type { Dashboard, Row } from '../types'
import { dateShort } from '../format'
import { Badge, DataTable, Section, Tile, type Col } from './ui'

const alertCols: Col<Row>[] = [
  { key: 'ts_utc', label: 'time', align: 'left' },
  { key: 'level', label: 'level', align: 'left', render: (r) => <Badge status={String(r.level)}>{String(r.level)}</Badge> },
  { key: 'command', label: 'command', align: 'left' },
  { key: 'message', label: 'message', align: 'left', wrap: true },
]

export function Operations({ d }: { d: Dashboard }) {
  const o = d.ops
  const alerts7 = Object.entries(o.alerts_7d).map(([k, v]) => `${v} ${k}`).join(' ') || 'none'
  const feed = o.feed
  return (
    <Section id="ops" title="Operations" intro="Did every scheduled run happen, and did anything need a human.">
      <div className="tiles">
        <Tile label="missed scheduled runs" value={String(o.missed)} sub={o.first_day ? `in the grid below (since ${dateShort(o.first_day)})` : 'no scheduled runs yet'} />
        <Tile label="alerts, last 7 days" value={alerts7} sub={`${o.errors_7d} run(s) ended in ERROR`} />
        <Tile
          label="data feed, last run"
          value={feed ? <><Badge status={feed.status} icon>{feed.status}</Badge> {feed.run_utc}</> : 'n/a'}
          sub={feed ? `+${feed.rows_added} rows to ${(feed.last_new ?? '').slice(0, 16)}${feed.errors ? ` | ${feed.errors}` : ''}` : 'no update_log.csv'}
        />
        <Tile label="runs logged" value={String(o.runs_total)} sub="all commands, including manual ones" />
      </div>
      <h3>Scheduled runs by day, UTC</h3>
      {o.grid.length ? (
        <div className="scroll">
          <table className="grid">
            <thead><tr><th className="left">day</th>{o.cmds.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {o.grid.map((g) => (
                <tr key={g.day}>
                  <td className="left">{g.day}</td>
                  {g.cells.map((c, i) => <td key={i}><Badge status={c.status} title={c.note}>{c.status}</Badge></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted small">no scheduled runs yet (install scheduler/install_tasks.ps1)</p>
      )}
      <p className="muted small">
        MISSING = no run logged by its time + 20 min (laptop asleep, WSL failed to start, task not installed). NO_TRADE = the run refused to
        trade (failed data update or signal not ok): see alerts. Hover a cell for its note.
      </p>
      {o.notes.length > 0 && (
        <>
          <h3>Timing notes from the logs</h3>
          <ul className="small">{o.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </>
      )}
      <h3>Alerts, latest 15</h3>
      <DataTable cols={alertCols} rows={o.alerts} rowKey={(r, i) => `${String(r.ts_utc)}-${i}`} empty="no alerts" />
    </Section>
  )
}
