import { useDashboard } from './api'
import { useTheme, type Theme } from './theme'
import { dateLong, utc } from './format'
import { Badge } from './components/ui'
import { SignalBar } from './components/SignalBar'
import { StrategyB } from './components/StrategyB'
import { StrategyA } from './components/StrategyA'
import { Combined } from './components/Combined'
import { KillSwitches } from './components/KillSwitches'
import { Operations } from './components/Operations'

const NAV = [
  ['signal', 'Now'], ['b', 'B'], ['a', 'A'], ['combined', 'Combined'], ['kill', 'Kill switches'], ['ops', 'Operations'],
] as const
const THEMES: { id: Theme; label: string }[] = [{ id: 'system', label: 'Auto' }, { id: 'light', label: 'Light' }, { id: 'dark', label: 'Dark' }]

export default function App() {
  const { data, error, loading, fetchedAt, refresh } = useDashboard(60_000)
  const [theme, setTheme] = useTheme()
  const triggered = data?.kill.filter((k) => k.status === 'bad').length ?? 0
  return (
    <>
      <header className="top">
        <div className="brand">
          <h1>BTC paper trading</h1>
          <span className="sub">B 50-day trend + A evening window</span>
          {data?.dry_run && <Badge status="warn">Dry run</Badge>}
          {triggered > 0 && <Badge status="bad" icon>{triggered} kill switch{triggered > 1 ? 'es' : ''} triggered</Badge>}
        </div>
        <nav aria-label="sections">{NAV.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}</nav>
        <div className="tools">
          {fetchedAt && <span className="muted small" title="when this page last read dashboard.json">read {fetchedAt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</span>}
          <button type="button" className="ghost" onClick={() => void refresh()} disabled={loading}>{loading ? 'Refreshing' : 'Refresh'}</button>
          <div className="segmented" role="radiogroup" aria-label="theme">
            {THEMES.map((t) => (
              <button key={t.id} type="button" role="radio" aria-checked={theme === t.id} className={theme === t.id ? 'on' : ''} onClick={() => setTheme(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className={loading && data ? 'stale' : ''}>
        {error && data && <div className="banner warn" role="alert">Last refresh failed: {error}. Showing the data generated {utc(data.generated_utc)}.</div>}
        {error && !data && (
          <div className="card" role="alert">
            <h2>No dashboard data yet</h2>
            <p>Could not load <code>data/dashboard.json</code>: {error}.</p>
            <p className="muted small">
              The Python side writes it. In WSL, from the project folder: <code>python3 code/dashboard.py</code>. The scheduled task does the same every
              day at 23:10 UTC. Then press Refresh.
            </p>
          </div>
        )}
        {!data && !error && <p className="muted">Loading…</p>}
        {data && (
          <>
            <p className="meta">
              Generated {utc(data.generated_utc)}
              {data.paper_start ? ` · paper trading since ${dateLong(data.paper_start)} (${data.paper_days} day${data.paper_days === 1 ? '' : 's'})` : ' · no paper rows yet'}
              {' · read-only: this page places no orders'}
            </p>
            <SignalBar d={data} />
            <StrategyB d={data} />
            <StrategyA d={data} />
            <Combined d={data} />
            <KillSwitches d={data} />
            <Operations d={data} />
            <footer>
              Numbers from code/dashboard.py (data/paper/*.csv and data/btc_1h.csv), rules STRATEGY_RULES.md v1.1. Expected curves: the backtest maths on the same days.
              No parameter is tuned on data after 31 Jul 2026. This page re-reads the file every minute. Logs: {data.paper_dir}.
            </footer>
          </>
        )}
      </main>
    </>
  )
}
