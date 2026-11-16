import type { Dashboard } from '../types'
import { dd, pct, usd } from '../format'
import { EquityChart } from './EquityChart'
import { Section, Tile } from './ui'

export function Combined({ d }: { d: Dashboard }) {
  const c = d.C
  return (
    <Section id="combined" title="Combined" intro="B's daily return plus A's daily return, the way the backtest adds them. Independent of the two account sizes.">
      <div className="tiles">
        <Tile label="sum of both accounts" value={`${usd(c.sum)} USDT`} sub={`B ${usd(d.B.equity)} + A ${usd(d.A.equity)}`} />
        <Tile label="combined return" value={pct(c.paper_return)} sub={`B return + A return per day, as the backtest adds them | ${c.days} day(s)`} />
        <Tile label="expected (same days)" value={pct(c.expected_return)} sub={`buy & hold ${pct(c.bh_return)}`} />
        <Tile label="max drawdown" value={dd(c.max_dd)} sub="combined curve" />
      </div>
      <EquityChart
        title="B + A: combined paper vs expected vs buy & hold (growth since paper start)"
        series={[
          { key: 'paper', name: 'B+A paper', pts: c.curve.paper },
          { key: 'expected', name: 'B+A expected', pts: c.curve.expected },
          { key: 'bh', name: 'buy & hold', pts: c.curve.bh ?? [] },
        ]}
      />
    </Section>
  )
}
