import type { Dashboard, Quarter, Row, Trade } from '../types'
import { bp, int, num, pct, share, usd } from '../format'
import { EquityChart } from './EquityChart'
import { Badge, DataTable, Section, Tile, type Col } from './ui'

const windowCols: Col<Row>[] = [
  { key: 'day', label: 'day', align: 'left' },
  { key: 'status', label: 'status', align: 'left', render: (r) => <Badge status={String(r.status)}>{String(r.status)}</Badge> },
  { key: 'allowed', label: 'allowed', align: 'left' },
  { key: 'price_2055', label: 'price 20:55', render: (r) => int(r.price_2055) },
  { key: 'sma200', label: 'SMA200', render: (r) => int(r.sma200) },
  { key: 'fill_rate', label: 'fill', render: (r) => (typeof r.fill_rate === 'number' ? share(r.fill_rate) : '') },
  { key: 'entry_avg', label: 'entry', render: (r) => num(r.entry_avg, 2) },
  { key: 'exit_avg', label: 'exit', render: (r) => num(r.exit_avg, 2) },
  { key: 'exit_type', label: 'exit type', align: 'left', render: (r) => (r.exit_type ? <Badge status={String(r.exit_type)}>{String(r.exit_type)}</Badge> : '') },
  { key: 'entry_slip_real_bp', label: 'entry slip real', render: (r) => num(r.entry_slip_real_bp, 2) },
  { key: 'exit_slip_real_bp', label: 'exit slip real', render: (r) => num(r.exit_slip_real_bp, 2) },
  { key: 'entry_slip_demo_bp', label: 'entry slip demo', render: (r) => num(r.entry_slip_demo_bp, 2) },
  { key: 'exit_slip_demo_bp', label: 'exit slip demo', render: (r) => num(r.exit_slip_demo_bp, 2) },
  { key: 'fees_usdt', label: 'fees', render: (r) => num(r.fees_usdt, 4) },
  { key: 'funding_usdt', label: 'funding', render: (r) => num(r.funding_usdt, 4) },
  { key: 'pnl_usdt', label: 'P&L USDT', render: (r) => num(r.pnl_usdt, 2) },
  { key: 'pnl_bp', label: 'P&L bp', render: (r) => num(r.pnl_bp, 1) },
  { key: 'note', label: 'note', align: 'left', wrap: true, render: (r) => <span className="muted small">{String(r.note ?? '')}</span> },
]

const tradeCols: Col<Trade>[] = [
  { key: 'day', label: 'day', align: 'left' },
  { key: 'paper', label: 'paper bp', render: (t) => num(t.paper, 1) },
  { key: 'sim', label: 'expected bp', render: (t) => num(t.sim, 1) },
  { key: 'diff', label: 'difference', render: (t) => num(t.diff, 1) },
  { key: 'fill', label: 'fill', render: (t) => share(t.fill) },
  { key: 'exit_type', label: 'exit', align: 'left', render: (t) => (t.exit_type ? <Badge status={t.exit_type}>{t.exit_type}</Badge> : '') },
]

type QRow = Quarter & { source: string }
const quarterCols: Col<QRow>[] = [
  { key: 'q', label: 'quarter', align: 'left', render: (q) => `${q.q}${q.done ? '' : ' (in progress)'}` },
  { key: 'source', label: 'source', align: 'left', wrap: true },
  { key: 'n', label: 'trades' },
  { key: 'bp', label: 'avg bp/trade', render: (q) => num(q.bp, 1) },
  { key: 'total', label: 'total', render: (q) => (q.total !== undefined ? pct(q.total, 1) : num(q.usdt, 2)) },
]

export function StrategyA({ d }: { d: Dashboard }) {
  const a = d.A
  const th = d.thresholds
  const exits = Object.entries(a.exit_types).map(([k, v]) => `${k} ${v}`).join(', ') || 'none'
  const quarters: QRow[] = [
    ...a.quarters.map((q) => ({ ...q, source: 'paper' })),
    ...a.sim_quarters.map((q) => ({ ...q, source: `simulated on actual candles (holdout from ${th.holdout_start})` })),
  ]
  return (
    <Section id="a" title="Strategy A · 21:00–23:00 UTC window" intro="USD-M futures demo account. Post-only entry at 21:00, exit by 23:00, only when the 20:55 price is above the 200-day average.">
      <div className="tiles">
        <Tile label="equity" value={`${usd(a.equity)} USDT`} sub={`${a.position ? `position ${num(a.position, 3)} BTC | ` : ''}${a.equity_ts ? `at ${a.equity_ts}` : ''}`} />
        <Tile label="paper return" value={pct(a.paper_return)} sub={`expected ${pct(a.expected_return)} | ${a.days} day(s)`} />
        <Tile label="days" value={String(a.days_logged)} sub={`${a.allowed} allowed by the filter, ${a.counts.SKIPPED_FILTER ?? 0} skipped, ${a.attempted} entries attempted`} />
        <Tile label="fill rate" value={share(a.fill_rate)} sub={`go/no-go >= ${share(th.fill_min)} | ${a.filled_days}/${a.attempted} days got any fill, ${a.unfilled} unfilled`} />
        <Tile label="avg slippage per side" value={`real ${bp(a.slip_real, 2)}`} sub={`demo ${bp(a.slip_demo, 2)} | go/no-go <= ${th.slip_max_bp} bp vs REAL mid`} />
        <Tile label="avg per trade" value={bp(a.avg_bp)} sub={`backtest ${bp(th.backtest_a_bp)} | same days simulated ${bp(a.sim_same_days)} | drag ${bp(a.exec_drag)}`} />
        <Tile label="closed trades" value={String(a.closed)} sub={`win rate ${share(a.win_rate)} | P&L ${usd(a.pnl_usdt)} USDT`} />
        <Tile label="fees + funding" value={`${usd(a.fees)} + ${usd(a.funding)} USDT`} sub={`exits: ${exits}`} />
        <Tile label="rolling 90 days" value={bp(a.roll90_bp)} sub={`${a.roll90_n} trade(s) | kill switch: negative two quarters running`} />
        <Tile label="problems" value={String(a.missed + a.errors + a.still_open)} sub={`${a.missed} missed (machine off), ${a.errors} errors, ${a.still_open} still open after 23:00`} />
      </div>
      <p className="muted small">
        Equity is the USDT that A trades with (the futures account's USDT margin balance, last logged by the bot).
        Binance's Futures › Assets page shows a larger Margin Balance because it also counts the demo account's idle
        USDC and BTC, which A never uses: they are left out on purpose so returns are measured on the money at risk.
      </p>
      <EquityChart
        title="A: paper equity vs the backtest maths on the same days (growth since paper start)"
        series={[{ key: 'paper', name: 'A paper', pts: a.curve.paper }, { key: 'expected', name: 'A expected (same days)', pts: a.curve.expected }]}
      />
      <h3>Windows, last 15</h3>
      <DataTable cols={windowCols} rows={a.recent_rows} rowKey={(r, i) => `${String(r.day)}-${i}`} />
      {a.trades.length > 0 && (
        <>
          <h3>Paper vs expected, per closed trade</h3>
          <p className="muted small">Last 15. Basis points after fees; expected is the backtest maths on that day's candles.</p>
          <DataTable cols={tradeCols} rows={a.trades.slice(-15)} rowKey={(t) => t.day} />
        </>
      )}
      <h3>By quarter</h3>
      <DataTable cols={quarterCols} rows={quarters} rowKey={(q) => `${q.source}-${q.q}`} empty="no quarters yet" />
      <p className="small">
        <Badge status={a.mismatches.length ? 'bad' : a.checks ? 'ok' : 'na'} icon>signal check</Badge>{' '}
        {a.checks ? `${a.checks - a.mismatches.length}/${a.checks} logged 20:55 decisions agree with signals.py` : 'no 20:55 decisions logged yet'}
        {a.mismatches.map((m) => <span key={m.day}> | <strong>{m.day}</strong> logged {m.logged} but signals.py says {m.computed}</span>)}
        {a.filter_total > 0 && ` | filter agreed with the backtest proxy (20:00 close) on ${a.filter_agree}/${a.filter_total} days`}
      </p>
      <p className="muted small">
        Demo futures microstructure is not the real book (spread 0.02-4.6 bp seen vs 0.02 bp real): judge fills and slippage on the REAL-mid columns.
      </p>
    </Section>
  )
}
