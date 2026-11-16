import type { Dashboard, KillSwitch } from '../types'
import { Badge, DataTable, Section, type Col } from './ui'

const LABEL = { ok: 'OK', warn: 'WATCH', bad: 'TRIGGERED', na: 'no data yet' } as const

const cols: Col<KillSwitch>[] = [
  { key: 'trigger', label: 'trigger', align: 'left', wrap: true },
  { key: 'action', label: 'action if hit', align: 'left', wrap: true },
  { key: 'reading', label: 'current reading', align: 'left', wrap: true },
  { key: 'status', label: 'status', align: 'left', render: (k) => <Badge status={k.status} icon>{LABEL[k.status]}</Badge> },
]

export function KillSwitches({ d }: { d: Dashboard }) {
  const triggered = d.kill.filter((k) => k.status === 'bad').length
  const watch = d.kill.filter((k) => k.status === 'warn').length
  return (
    <Section
      id="kill"
      title="Kill switches"
      intro={triggered ? `${triggered} trigger(s) hit: stop and review before the next run.` : watch ? `${watch} reading(s) below the line with too few trades to call.` : 'Nothing triggered.'}
    >
      <DataTable cols={cols} rows={d.kill} rowKey={(k) => k.trigger} className="kill" />
      <p className="muted small">
        STRATEGY_RULES.md section 6.2. Go/no-go for A is read after 90 days of paper trading. WATCH = below the line but too few trades to call.
        The simulated quarters under Strategy A are context from the holdout, not paper results.
      </p>
    </Section>
  )
}
