import type { Dashboard, Row } from '../types'
import { bp, dd, int, num, pct, usd } from '../format'
import { EquityChart } from './EquityChart'
import { Badge, DataTable, Section, Tile, type Col } from './ui'

const cols: Col<Row>[] = [
  { key: 'day', label: 'day', align: 'left' },
  { key: 'status', label: 'status', align: 'left', render: (r) => <Badge status={String(r.status)}>{String(r.status)}</Badge> },
  { key: 'action', label: 'action', align: 'left' },
  { key: 'qty', label: 'qty BTC', render: (r) => num(r.qty, 5) },
  { key: 'avg_price', label: 'avg price', render: (r) => num(r.avg_price, 2) },
  { key: 'fee_usdt', label: 'fee USDT', render: (r) => num(r.fee_usdt, 2) },
  { key: 'slip_real_bp', label: 'slip real bp', render: (r) => num(r.slip_real_bp, 2) },
  { key: 'slip_demo_bp', label: 'slip demo bp', render: (r) => num(r.slip_demo_bp, 2) },
  { key: 'close_prev', label: 'close D-1', render: (r) => int(r.close_prev) },
  { key: 'sma50', label: 'SMA50', render: (r) => int(r.sma50) },
  { key: 'delay_min', label: 'delay min', render: (r) => num(r.delay_min, 0) },
  { key: 'note', label: 'note', align: 'left', wrap: true, render: (r) => <span className="muted small">{String(r.note ?? '')}</span> },
]

export function StrategyB({ d }: { d: Dashboard }) {
  const b = d.B
  const th = d.thresholds
  const annual = b.switches_yr !== null && b.days >= 30
  return (
    <Section id="b" title="Strategy B · 50-day trend" intro="Spot demo account. Long while yesterday's close is above its 50-day average, cash otherwise.">
      <div className="tiles">
        <Tile label="holding" value={<Badge status={b.holding}>{b.holding ?? 'n/a'}</Badge>} sub={b.equity !== null ? `${num(b.btc, 5)} BTC + ${usd(b.usdt)} USDT` : undefined} />
        <Tile label="equity" value={`${usd(b.equity)} USDT`} sub={b.equity_ts ? `at ${b.equity_ts}` : undefined} />
        <Tile label="paper return" value={pct(b.paper_return)} sub={`expected ${pct(b.expected_return)} | buy & hold ${pct(b.bh_return)} | ${b.days} day(s)`} />
        <Tile label="max drawdown" value={dd(b.max_dd)} sub={`limit ${dd(th.b_dd_max)} (worst backtest)`} />
        <Tile label="switches" value={String(b.switches)} sub={annual ? `${Math.round(b.switches_yr ?? 0)}/yr annualised, backtest ~${th.backtest_b_switches_yr}, review >${th.b_switch_max_yr}` : `${b.days_logged} day row(s); backtest ~${th.backtest_b_switches_yr}/yr`} />
        <Tile label="fees paid" value={`${usd(b.fees)} USDT`} sub="0.10% assumed per switch in the backtest" />
        <Tile label="avg slippage" value={`real ${bp(b.slip_real, 2)}`} sub={`demo ${bp(b.slip_demo, 2)} | negative = better than mid`} />
        <Tile label="days logged" value={String(b.days_logged)} sub={`${b.no_trade} no-trade, ${b.late_runs} late (>30 min), ${b.incomplete} incomplete`} />
      </div>
      <EquityChart
        title="B: paper equity vs the backtest maths on the same days (growth since paper start)"
        series={[{ key: 'paper', name: 'B paper', pts: b.curve.paper }, { key: 'expected', name: 'B expected (same days)', pts: b.curve.expected }]}
      />
      <h3>Switches, last 10</h3>
      <DataTable cols={cols} rows={b.switch_rows} rowKey={(r, i) => `${String(r.day)}-${i}`} />
      <p className="small">
        <Badge status={b.mismatches.length ? 'bad' : b.checks ? 'ok' : 'na'} icon>signal check</Badge>{' '}
        {b.checks ? `${b.checks - b.mismatches.length}/${b.checks} logged B decisions agree with signals.py` : 'no B decisions logged yet'}
        {b.mismatches.map((m) => <span key={m.day}> | <strong>{m.day}</strong> logged {m.logged} but signals.py says {m.computed}</span>)}
      </p>
    </Section>
  )
}
