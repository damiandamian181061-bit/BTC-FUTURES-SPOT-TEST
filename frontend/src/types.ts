// Mirrors the JSON written by code/dashboard.py (payload(), schema 1). Keep the two in step.

export type Status = 'ok' | 'warn' | 'bad' | 'na'
/** [ISO timestamp, growth of 1 since the paper start] */
export type Point = [string, number]
export interface Curve { paper: Point[]; expected: Point[]; bh?: Point[] }

export interface Span {
  paper_return: number | null
  expected_return: number | null
  max_dd: number | null
  days: number
  start: string | null
  end: string | null
}

export interface SignalState {
  b: 'LONG' | 'CASH' | null
  a: 'ON' | 'OFF' | null
  state: string | null
  b_close: number | null
  sma50: number | null
  a_price: number | null
  a_price_source: string | null
  sma200: number | null
  ok: boolean
  warnings: string[]
  errors: string[]
  last_candle: string | null
  data_age_h: number | null
}

export interface Mismatch { day: string; logged: string; computed: string }
/** A ledger row as logged: strings stay strings, numeric columns are numbers, blanks are null. */
export type Row = Record<string, string | number | boolean | null>

export interface StrategyB extends Span {
  holding: string | null
  equity: number | null
  btc: number | null
  usdt: number | null
  equity_ts: string | null
  bh_return: number | null
  days_logged: number
  switches: number
  switches_yr: number | null
  fees: number
  slip_real: number | null
  slip_demo: number | null
  late_runs: number
  no_trade: number
  incomplete: number
  checks: number
  mismatches: Mismatch[]
  curve: Curve
  switch_rows: Row[]
}

export interface Quarter { q: string; n: number; bp: number; usdt?: number; total?: number; done: boolean }

export interface Trade {
  day: string
  paper: number | null
  sim: number | null
  diff: number | null
  fill: number | null
  entry: number | null
  exit: number | null
  exit_type: string | null
  es_real: number | null
  xs_real: number | null
  es_demo: number | null
  xs_demo: number | null
  fees: number | null
  funding: number | null
  pnl: number | null
  status: string
}

export interface StrategyA extends Span {
  equity: number | null
  equity_ts: string | null
  position: number | null
  counts: Record<string, number>
  allowed: number
  attempted: number
  closed: number
  fill_rate: number | null
  filled_days: number
  slip_real: number | null
  slip_demo: number | null
  entry_slip_real: number | null
  exit_slip_real: number | null
  entry_slip_demo: number | null
  exit_slip_demo: number | null
  avg_bp: number | null
  win_rate: number | null
  pnl_usdt: number
  fees: number
  funding: number
  exit_types: Record<string, number>
  market_exits: number
  missed: number
  errors: number
  unfilled: number
  still_open: number
  sim_same_days: number | null
  exec_drag: number | null
  filter_agree: number
  filter_total: number
  roll90_n: number
  roll90_bp: number | null
  quarters: Quarter[]
  sim_quarters: Quarter[]
  trades: Trade[]
  days_logged: number
  checks: number
  mismatches: Mismatch[]
  curve: Curve
  recent_rows: Row[]
}

export interface Combined extends Span { sum: number | null; bh_return: number | null; curve: Curve }

export interface KillSwitch { trigger: string; action: string; reading: string; status: Status }

export interface GridCell { status: string; note: string }
export interface Ops {
  missed: number
  first_day: string | null
  cmds: string[]
  grid: { day: string; cells: GridCell[] }[]
  alerts: Row[]
  alerts_7d: Record<string, number>
  errors_7d: number
  runs_total: number
  feed: Record<string, string> | null
  notes: string[]
}

export interface Thresholds {
  fill_min: number
  slip_max_bp: number
  bp_tolerance: number
  backtest_a_bp: number
  b_switch_max_yr: number
  b_dd_max: number
  backtest_b_switches_yr: number
  holdout_start: string
}

export interface Dashboard {
  schema: number
  generated_utc: string
  dry_run: boolean
  paper_dir: string
  paper_start: string | null
  paper_days: number
  thresholds: Thresholds
  signal: SignalState
  B: StrategyB
  A: StrategyA
  C: Combined
  kill: KillSwitch[]
  ops: Ops
}
