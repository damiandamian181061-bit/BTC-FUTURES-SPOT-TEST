import type { Dashboard } from '../types'
import { hours, int, utc } from '../format'
import { Badge, Section } from './ui'

/** Portfolio-state rows as the rulebook names them, for the big headline. */
function headline(state: string | null) {
  if (!state) return 'No signal'
  const name = state.split(' (')[0]
  return name.charAt(0).toUpperCase() + name.slice(1)
}

export function SignalBar({ d }: { d: Dashboard }) {
  const s = d.signal
  const age = s.data_age_h
  const ageStatus = age === null ? 'na' : age <= 3 ? 'ok' : age <= 12 ? 'warn' : 'bad'
  const detail = s.state?.includes('(') ? s.state.slice(s.state.indexOf('(') + 1, -1) : null
  return (
    <Section id="signal" title="Right now">
      <div className="hero">
        <div>
          <div className="eyebrow">Portfolio row, from the stored candles</div>
          <div className="state">{headline(s.state)}</div>
          {detail && <div className="muted">{detail}</div>}
        </div>
        <div className="facts">
          <div className="fact">
            <span className="k">B, 50-day trend</span>
            <span className="v"><Badge status={s.b ?? 'na'}>{s.b ?? 'n/a'}</Badge><span className="n">{int(s.b_close)} vs {int(s.sma50)}</span></span>
          </div>
          <div className="fact">
            <span className="k">A, 21:00 window</span>
            <span className="v"><Badge status={s.a ?? 'na'}>{s.a ?? 'n/a'}</Badge><span className="n">{int(s.a_price)} vs {int(s.sma200)}</span></span>
          </div>
          <div className="fact">
            <span className="k">Data</span>
            <span className="v"><Badge status={ageStatus} icon>{hours(age)} old</Badge><span className="n">{utc(s.last_candle)}</span></span>
          </div>
          <div className="fact">
            <span className="k">Signal checks</span>
            <span className="v"><Badge status={s.ok ? 'ok' : 'bad'} icon>{s.ok ? 'ok' : 'not ok'}</Badge></span>
          </div>
        </div>
      </div>
      {s.warnings.length > 0 && <p className="muted small">{s.warnings.join(' | ')}</p>}
      {s.errors.length > 0 && <p className="small"><Badge status="bad" icon>errors</Badge> {s.errors.join(' | ')}</p>}
      <p className="muted small">
        The real 20:55 decision uses the live price; this view uses the last stored close. B decides at 00:01 UTC on yesterday's close.
        Nothing trades while the row is bear. That is the rule working, not a fault.
      </p>
    </Section>
  )
}
