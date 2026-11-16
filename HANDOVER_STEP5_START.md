# START HERE: Handover for the next chat (written 16 Nov 2026, ~22:15 UK time)

**Owner:** Damian Craddock. **Project:** BTC trend (B) + evening-window (A) trading system, paper-traded on Binance
Demo Trading from a laptop (WSL), built as a CV project.

**Read order for a new chat:**
1. **This file**: where things stand after the evening session of 16 Nov (harness built, tested live on the demo
   accounts, scheduler written but NOT yet installed).
2. `STRATEGY_RULES.md`: the rulebook (v1.1). If code disagrees with it, the code is wrong.
3. `HANDOVER_STEP4_START.md`: the night session (Binance demo set-up, keys, connection check, step 4 plan). Sections
   8.4-8.8 there are the original build plan; this file says what of it is done.
4. `PROJECT_CONTEXT.md`: master history (martingale -> research -> decision). Only if needed: `HANDOVER_STEP3.md`,
   `HANDOVER_STEP2.md`, `docs/STRATEGY_WRITEUP.md` (research numbers, still pre-correction).

**Where we stopped (updated 16 Nov 2026, ~22:50 UTC):** the dashboard is built, tested and run on the real logs
(section 11), and the five scheduled tasks are INSTALLED (16 Nov 22:42 UTC, with Damian's go-ahead; the dashboard task
was fired by hand through Task Scheduler and ran clean). The paper run is live: first automatic run = b-check at
00:01 UTC on 17 Nov. A Vite + React front end for the dashboard was then built in `frontend/` (section 12) and
`README.md` added at the root. **Next action: section 8, step 3 (watch the first week on the dashboard); optionally the
power settings script in step 1.**

---

## 1. The system in five lines (so this file stands alone)

- **B (main position):** at 00:00 UTC, if yesterday's daily close > its 50-day SMA, hold BTC worth 1.0 x account
  (spot); else hold cash. ~20 switches/yr. No stops/targets/shorting.
- **A (overlay):** at 20:55 UTC, if the live price > SMA200 of daily closes up to *yesterday*, buy BTCUSDT perpetual
  worth 1.0 x account at 21:00 with **post-only limit** orders (cancel at 21:05 if unfilled, never chase), sell with a
  post-only limit at 22:55, close at market at 23:00 if still open. ~216 trades/yr; none in deep bears.
- Daily close of day D = close of D's 23:00 hourly candle (Binance BTCUSDT spot, 1h).
- Size always from current account value; **never double after a loss** (martingale permanently dropped).
- **No parameter tuning on data after 2026-07-31.** That data is the only untouched test set.

Headline numbers (look-ahead-corrected, A at 1x, after fees): B+A **+75.9%/yr** whole period Apr 2020-Jul 2026
(Sharpe 1.25, DD -58%), +64.8%/yr out of sample 2023-Jul 2026; buy & hold +41.4%/yr. Fresh holdout 1 Aug-15 Nov 2026:
B +24.5%, A **-7.0%** (worst stretch on record; on probation, kill switch needs two negative quarters, review end Q1
2027), B+A +15.8%, buy & hold +3.9%. Full tables: STRATEGY_RULES.md sections 2.5, 3.6, 4.2.

**Signal state 16 Nov 2026 22:00 UTC:** close (15 Nov) 65,351 | SMA50 79,844 | SMA200 72,978 | price ~65,450
-> **B = CASH, A = OFF** ("bear" row). The bot will correctly do nothing but log until the price is back above
~72,978 (A) / the close is above ~79,844 (B). Not a bug.

---

## 2. What exists now (code inventory, 16 Nov 2026 22:00)

| File | Role | Status |
|---|---|---|
| `code/datafeed.py` (+ `test_datafeed.py`, 7 tests) | downloads closed 1h candles, validates, rebuilds daily file, `latest_price()` | step 2, live since 16 Nov; test fixture fixed this evening (was growing with the live file) |
| `code/signals.py` (+ `test_signals.py`, 19 tests) | B target at 00:00, A filter at 20:55, `current_state()` with "do not trade" checks; used by bot AND backtests | step 3, done |
| `code/backtest.py`, `fresh_oos.py`, `analysis.py`, `build_dataset.py` | research / holdout (corrected filter; `--original-filter` reproduces v1.0 numbers) | done |
| `code/exchange.py` (+ `test_exchange.py`, 5 tests) | stdlib Binance REST client: HMAC signing, clock offset, secrets loader | step 4 start, done |
| `code/connection_check.py` | read-only check of both demo accounts | done |
| **`code/orders.py`** | filters/rounding, demo + REAL book, balances, `futures_setup`, place/cancel/fills, fee conversion (USDT/BTC/BNB), `work_order` post-only loop, `market_rest` | **built this evening** |
| **`code/ledger.py`** | append-only CSV logs under `data/paper/` (`runs`, `alerts`, `signals`, `orders`, `fills`, `equity`, `a_windows`, `b_days`); dry runs -> `data/paper/dryrun/` | built this evening |
| **`code/fakebinance.py`** | fake spot + futures exchange on 127.0.0.1 (Binance shapes and error codes) for tests and dry runs; state persists in `fake_*.json` | built this evening |
| **`code/harness.py`** | the bot: `status`, `setup`, `b-check`, `a-precheck`, `a-enter`, `a-exit`, `a-test`, `flatten`, `relog`; flags `--dry-run`, `--force` (dry-run only), `--deadline-min`, `--poll`, `--leverage`, `--order-id`, `--strategy` | built this evening, **run live on the demo accounts** |
| **`code/test_harness.py`** | 19 offline tests (rounding, fills, re-pricing, partial fills, deadlines, would-cross on both venues, exit + market fallback, spot BTC fee, BNB fee, setup idempotent, errors propagate, ledger) | all pass |
| **`code/dashboard.py`** (+ `test_dashboard.py`, 11 tests) | read-only report from `data/paper/*.csv`: `data/paper/dashboard.html` + `dashboard.json` + terminal summary. B / A / combined sections, kill-switch table (rules 6.2), missed-run grid, alerts, feed status, paper vs "expected" (backtest maths on the same days) | **built 16 Nov ~22:30 UTC**, run on the real logs (section 11); JSON export added ~23:05 (section 12) |
| **`frontend/`** (Vite + React + TypeScript) | the dashboard as a web app: renders `dashboard.json`, re-reads it every minute, light/dark, Recharts equity charts, tables, kill switches, run grid. `npm run dev` / `npm run build` (see `frontend/README.md`) | **built 16 Nov ~23:20 UTC**, production build checked in the browser (section 12) |
| **`code/run.sh`** | wrapper the scheduler calls: runs one harness command (`dashboard` -> `dashboard.py`), appends output to `data/paper/logs/<command>.log` | built; `run.sh dashboard` run end to end in WSL |
| **`scheduler/install_tasks.ps1`** | registers the 5 Windows Task Scheduler tasks (4 harness commands + dashboard 23:10 UTC; UTC triggers, WakeToRun) via `schtasks.exe /XML` | **installed 16 Nov 22:42 UTC**; task names use dots ("BTC bot - b-check 00.01 UTC") because ':' is not allowed in a task name |
| `scheduler/uninstall_tasks.ps1`, `scheduler/laptop_power_settings.ps1` | remove tasks / stop sleep + lid action while plugged in (admin) | written, not run |
| `data/btc_1h.csv` | 62,458 hourly rows to 2026-11-16 20:00 UTC (datafeed ran at 21:58 UTC) | current |
| `data/paper/*.csv`, `dashboard.html`, `logs/dashboard.log` | the REAL paper-trading logs (7 orders rows, 1 fill, 1 b_days row, 8 runs incl. two manual dashboard runs, 2 alerts) + the generated page | live |

**Test totals: 61 offline tests, all pass** (datafeed 7, signals 19, exchange 5, harness 19, dashboard 11; confirmed in WSL 16 Nov 23:09 UTC). Run them all:
```bash
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && for t in test_datafeed test_signals test_exchange test_harness test_dashboard; do python3 code/$t.py 2>&1 | tail -1; done
```

---

## 3. Decisions made this evening

| # | Decision | Why |
|---|---|---|
| 1 | **Paper sizing = each strategy from its own demo account**: B = 1.0 x spot account value, A = 1.0 x futures `totalMarginBalance` | Each reconciles to the backtest's "B alone"/"A alone" at 1x; combined = sum of daily returns; A's go/no-go doesn't depend on size. Logged in STRATEGY_RULES change log as a paper choice, not a rule change. Live sizing (rules 4.3) still open |
| 2 | Damian **reset the demo balances** (they came back as 5,000 USDT + 0.05 BTC spot, 5,000 USDT futures: the demo default) | Instead of selling the BTC by hand |
| 3 | **B trades away anything on the wrong side** worth > 1% of equity (and > 2 x min notional): CASH means 0 BTC, LONG means all USDT in BTC | First status showed the 0.05 BTC (39%) classed as "CASH" and left alone. Fixed; the fix sold it (section 5) |
| 4 | A isolated leverage **3x** | 1x notional on ~1/3 of the account as margin (rules 4.3, 6.1.2); liquidation ~30% away |
| 5 | Fees paid in **BNB are accepted** and converted at the BNBUSDT ticker; nothing is changed in the backtest | The demo account pays spot fees in BNB by default (0.075% instead of 0.10%). First live run crashed on this (after the fill); converter fixed, `relog` command added to recover the missing rows |
| 6 | Scheduled tasks start `a-enter` at 20:59:30 and `a-exit` at 22:54:30; harness waits for the exact second | WSL takes a few seconds to start |
| 7 | Real public book logged next to every demo order; slippage measured vs the real mid | Demo futures spread varied between 0.02 bp and 4.6 bp within an hour tonight; real was 0.02 bp |

---

## 4. How the harness behaves (short version; matches STRATEGY_RULES 2.2 / 3.2)

- **`b-check` (00:01 UTC):** `datafeed.update()` -> exit != 0 => alert, no trade. `current_state()` not ok => alert, no
  trade. Target vs holding; if anything > 1% of equity is on the wrong side: post-only limit at the touch for 15 min
  (re-posted as the touch moves), then market for the rest. Logs `b_days`, `orders`, `fills` (fee in USDT, slippage vs
  real mid and vs yesterday's close), `equity`. A late run (laptop was asleep) still runs; `delay_min` is logged.
- **`a-precheck` (20:55):** live spot price vs SMA200[D-1] -> `a_windows` row ALLOWED / SKIPPED_FILTER. Refuses if A
  already holds a position. No orders.
- **`a-enter` (21:00):** needs today's ALLOWED row (pre-check missing and before 21:05 -> does it late with a WARN;
  after 21:05 -> MISSED_MACHINE_OFF, no trade). qty = equity / bid rounded to 0.001. Post-only buy loop until 21:05
  (GTX; re-posted when the bid rises; partial fills kept). Nothing filled -> UNFILLED, **no market order**. A second
  run the same day refuses.
- **`a-exit` (22:55):** post-only reduce-only sell until 23:00, then market for the rest. Started after 23:00 ->
  market at once + alert. No position but the day was ALLOWED and no entry ran -> MISSED_MACHINE_OFF. Final
  `a_windows` row: fill rate, entry/exit avg, slippage (real + demo), fees, funding, P&L in USDT and bp, exit type.
- **`flatten`:** cancel all A orders, market-close A (B untouched). **`a-test`:** post-only orders 5% below the market on
  both venues, verified resting, cancelled. **`relog --strategy B --order-id N`:** re-fetch an order and write its
  fills / day row (recovery after a crash). **`status`:** signals, balances, position, open orders, demo vs real book,
  last runs and alerts (read-only).
- Dry run (`--dry-run`): fake exchange seeded from the real public book, auto-fills, logs to `data/paper/dryrun/`,
  state in `data/paper/dryrun/fake_*.json` (delete to start afresh). `--force` (dry-run only) pretends the signal says
  trade, to exercise the order paths on a day like today.

---

## 5. What was run live on the demo accounts tonight (all from Damian's laptop, WSL)

| UTC | Command | Result |
|---|---|---|
| 21:40 | `harness.py status --dry-run` | fake exchange seeded from the REAL book: spot 65,318.49/.50 (0.00 bp), futures 65,280.00/.10 (0.02 bp) |
| 21:41 | `harness.py setup` | A futures demo: **margin ISOLATED, leverage 3x**, position 0 |
| 21:44 | `harness.py a-test` | post-only BUY 0.001 @ 62,030.80 (futures) and 0.0001 @ 62,047.35 (spot) placed, listed, cancelled, 0 filled: **ALL OK** |
| 21:47 | `harness.py status` | spot 5,000 USDT + 0.05 BTC (8,263 USDT), futures 5,000 USDT; demo futures spread 4.56 bp vs real 0.02 bp |
| 21:58 | `harness.py b-check` | datafeed +19 hours to 20:00 UTC; B target CASH; **sold 0.05 BTC post-only at the ask 65,294.35, filled in 5 s as maker** (real book 65,294.34/.35 at the time); then crashed logging the fill (fee in BNB) |
| 22:01 | `harness.py relog --strategy B --order-id 83894415923` | wrote the missing rows: fee 0.00412502 BNB = **2.4517 USDT (0.075%)**, slippage vs real mid -0.0008 bp |
| 22:02 | `harness.py status` | **B: 8,264.72 USDT, 0 BTC (CASH). A: 5,000 USDT, flat, ISOLATED 3x.** No open orders |

So the first real B trade is in `data/paper/b_days.csv` (status SWITCHED, held_before "?" because it was relogged).
**All offline tests: 50/50 pass** (Damian did not paste the `test_harness.py` output, but `a-test` and `b-check` worked live).

---

## 6. Commands reference (Damian's laptop: PowerShell -> `wsl` -> Enter; paste one line at a time, Ctrl+Shift+V)

```bash
# daily things the scheduler will do (can be run by hand; b-check trades if the target changed)
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py status          # read-only
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py b-check
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py a-precheck
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py a-enter
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py a-exit
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py flatten        # emergency only
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/dashboard.py             # read-only report -> data/paper/dashboard.html (open it in a browser)

# tests and checks
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/test_harness.py
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/connection_check.py
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py status --dry-run

# logs
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && tail -20 data/paper/runs.csv
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && cat data/paper/alerts.csv
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && tail -30 data/paper/logs/b-check.log   # exists once the scheduler has run
```

Claude's side: can read/edit/run code in the project folder via the device connection, but **cannot reach Binance**
(network policy) - anything touching Binance is run by Damian, who sends screenshots. Claude can't delete files in
the folder (stray files go to `_to_delete/`, which Damian can empty: it holds dry-run test folders and pycache).
Claude cannot and should not read `~/.config/btc-bot/secrets.env` (API keys, outside the connected folder by design).
**Never paste keys into chat.**

---

## 7. Known gaps / things to watch

- **Scheduler installed 16 Nov 22:42 UTC.** Everything now runs automatically while the laptop is awake; do not run
  b-check / a-precheck / a-enter / a-exit by hand around the scheduled times (a second run the same day refuses, but
  it still writes rows). Check the dashboard's operations grid daily for the first week.
- `held_before` in the relogged `b_days` row is "?" (it was 0.05 BTC / CASH-by-label).
- Demo futures microstructure is not the real book (spread 0.02-4.6 bp seen tonight). The go/no-go (fill rate >= 80%,
  slippage <= 2 bp) must be read from the **real-book** columns (`slip_real_bp`, `real_mid_*`) side by side with the
  demo ones. The dashboard (section 11) shows both side by side and applies the thresholds to the real-mid columns.
- BNB fee payment: the demo BNB balance will run out at some point; Binance then charges in the asset. The converter
  handles both. The backtest keeps 0.10% for B (conservative; do not retune).
- `wait_until` and the 20:59:30 / 22:54:30 starts are untested against real Task Scheduler timing: check
  `data/paper/logs/a-enter.log` on the first A day for "early by Ns: waiting until 21:00:00".
- `datafeed.update()` at 00:01 needs the 23:00 candle to be closed and published; if Binance is a few seconds late the
  run logs "signal not ok -> no trade" and alerts. If that happens more than once, move b-check to 00:03.
- `STRATEGY_WRITEUP.md` (both copies) still shows the original look-ahead figures; update before using it for the CV.
- Open from before: live sizing (rules 4.3), spot vs perpetual for B live, laptop vs VPS, tax/regulatory residency.

---

## 8. NEXT STEPS (in order)

**1. [DONE 16 Nov 2026 22:42 UTC] Install the scheduled tasks** (Windows PowerShell, not WSL; safe to re-run):
```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\damia\Documents\BTC Strategy Project\scheduler\install_tasks.ps1"
```
Creates 5 tasks "BTC bot - ...": b-check 00.01, a-precheck 20.55, a-enter 21.00 (starts 20:59:30), a-exit 22.55
(starts 22:54:30), dashboard 23.10, all UTC ("synchronize across time zones"), WakeToRun, run as Damian's interactive
session, call `wsl.exe -e bash -c "'/mnt/c/Users/damia/Documents/BTC Strategy Project/code/run.sh' <cmd>"`.
Lesson: the first attempt failed with "The parameter is incorrect" because the names contained ':' (a task is stored
as a file under System32\Tasks, so file-name rules apply); the script now uses dots and registers via `schtasks.exe /XML`.
Proof of the chain: `Start-ScheduledTask 'BTC bot - dashboard 23.10 UTC'` ran Task Scheduler -> WSL -> run.sh ->
dashboard.py with LastTaskResult 0; log and `runs.csv` heartbeat written at 22:42:35 UTC.
Fire the harmless one again any time:
```powershell
Start-ScheduledTask -TaskName 'BTC bot - dashboard 23.10 UTC'; Start-Sleep 25; Get-Content "C:\Users\damia\Documents\BTC Strategy Project\data\paper\logs\dashboard.log" -Tail 15
```
Still optional, as Administrator (sleep never / lid does nothing while plugged in; NOT run yet):
```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\damia\Documents\BTC Strategy Project\scheduler\laptop_power_settings.ps1"
```
Check the next morning: `data/paper/logs/b-check.log` and `runs.csv` should show the 00:01 run of 17 Nov.

**2. [DONE 16 Nov 2026] `code/dashboard.py`**: see section 11. It is the 5th scheduled task (23:10 UTC). Open
`C:\Users\damia\Documents\BTC Strategy Project\data\paper\dashboard.html` in any browser after a run.

**3. Watch the first week:** open the dashboard each day: the operations grid shows missed runs, the timing notes show
"early by Ns" lines, alerts list failures. Expect "no change" / "OFF" every day until the price recovers above SMA200
(~72,978).

**4. Later in step 4:** Telegram/email alerts (8.7 in HANDOVER_STEP4_START), a monthly table in the dashboard (it
already compares paper vs expected per trade and over the whole paper period), decide laptop vs VPS if missed runs
pile up.

**5. After 90 days of paper:** go/no-go for A (fill rate >= 80%, slippage <= 2 bp vs real mid, avg/trade within 3 bp of
backtest); B switch count sanity; add funding + slippage to the backtest; CV write-up.

---

## 9. Rules that carry into every chat

- No tuning on data after 2026-07-31. No changes to 50 / 200 / 21:00 / 23:00 / fee assumptions without a written
  reason, a test on unused data and a change-log entry in STRATEGY_RULES.md.
- Size from current account value only. Never double after a loss.
- Any failed data update, missing candle or live-vs-backtest signal mismatch = **no trade + alert**.
- A never market-buys and never holds past 23:00. B never overrides the signal by hand.
- Every backtest number quoted must say which version (original vs corrected) and which period.
- Damian runs code via WSL one-liners; Claude edits files directly but can't fetch market data or reach Binance.
- Never put API keys in chat or in the project folder.

## 10. Folder inventory (16 Nov 2026, 22:15 UK)
```
HANDOVER_STEP5_START.md  <- this file (start here)
STRATEGY_RULES.md        <- rulebook v1.1 (change log updated tonight: paper sizing, harness built)
HANDOVER_STEP4_START.md  <- night session: demo set-up + original step 4 plan (sections 12-13 partly superseded by this file)
PROJECT_CONTEXT.md       <- master history (points here)
HANDOVER_STEP3.md, HANDOVER_STEP2.md, STRATEGY_WRITEUP.md, docs/STRATEGY_WRITEUP.md, btc_strategy_project.zip (older)
code/      datafeed.py, signals.py, exchange.py, connection_check.py, orders.py, ledger.py, fakebinance.py, harness.py,
           dashboard.py, run.sh, backtest.py, fresh_oos.py, analysis.py, build_dataset.py, test_*.py (5 files, 58 tests), __pycache__/
scheduler/ install_tasks.ps1, uninstall_tasks.ps1, laptop_power_settings.ps1
data/      btc_1h.csv (to 2026-11-16 20:00 UTC), btc_1h.csv.bak, btc_1d.csv, update_log.csv
data/paper/ runs, alerts, signals, orders, fills, equity, a_windows (empty until A trades), b_days (REAL logs), dashboard.html, dashboard.json
data/paper/logs/ dashboard.log (manual + scheduler test runs); the other logs appear once the scheduler runs
frontend/  Vite + React + TypeScript dashboard app (src/, vite.config.ts, dev.cmd, README.md; node_modules/ and dist/ are generated)
README.md  root overview: layout, daily automation table, how to run things
.claude/launch.json  preview configs for Claude's desktop browser pane (frontend dev server, frontend/dist, data/paper); harmless
charts/    equity_curves.png, drawdowns.png, hour_of_day.png, holdout_equity.png (corrected filter)
project/ (empty), _to_delete/ (dry-run test folders, pycache, stray pngs: Damian can delete)
Outside the folder: ~/.config/btc-bot/secrets.env in WSL (API keys, chmod 600); copies in Bitwarden.
```

---

## 11. Session of 16 Nov 2026 late evening (Claude desktop app, 22:15-23:00 UTC): dashboard built

**What changed**
- `code/dashboard.py` (read-only: no keys, no orders, no network) and `code/test_dashboard.py` (8 tests, pass).
  Run: `python3 code/dashboard.py` (flags `--dry-run`, `--no-html`, `--days N`, `--now "YYYY-MM-DD HH:MM"` to replay).
  Writes `data/paper/dashboard.html` (self-contained, light/dark, inline SVG charts) and prints a terminal summary;
  writes a `dashboard` heartbeat row to `runs.csv`, so a missed 23:10 run shows up like any other.
- Sections: (1) signal state from stored candles, (2) B, (3) A, (4) combined, (5) kill switches, (6) operations.
  "Expected" curves = `fresh_oos.build` (same maths as backtest.py, signals from signals.py) on the actual candles of
  the same days, so paper minus expected isolates execution (fills, slippage, fees). A gets a per-trade table (paper bp
  vs expected bp, fill, exit type) and a by-quarter table; real-mid and demo-mid slippage are shown side by side.
  Combined return = B's daily return + A's daily return (how the backtest adds them), so it does not depend on the two
  demo accounts having different sizes. A 00:01 equity snapshot counts as the previous day's close.
- Kill-switch table implements every row of STRATEGY_RULES 6.2 with OK / WATCH / TRIGGERED / "no data yet"
  (WATCH = below the line but fewer than ~20-30 trades). It also recomputes every logged B target and 20:55 decision
  with signals.py from the stored data: any disagreement = TRIGGERED (the "bug until proven otherwise" rule).
- Operations: per-day grid of the five scheduled commands (OK / NO_TRADE / ERROR / MISSING / pending), missed-run
  count, alerts, last datafeed run, data age, and "early by Ns" / "late run" lines pulled from `data/paper/logs/`.
- `code/run.sh` dispatches `dashboard` to dashboard.py; `scheduler/install_tasks.ps1` gained a 5th task
  "BTC bot - dashboard 23:10 UTC" (both scripts parse clean; still not installed).
- All 58 offline tests pass in WSL (datafeed 7, signals 19, exchange 5, harness 19, dashboard 8).
- **Scheduler installed** (22:42 UTC, Damian's go-ahead in chat): five tasks live, the dashboard task fired by hand
  and ran clean through Task Scheduler. First automatic run: b-check 17 Nov 00:01 UTC. The laptop power-settings
  script (admin) has not been run.

**Finding to carry forward (no rule changed):** the dashboard's by-quarter table shows the simulated A overlay on the
actual candles since the holdout began: **Aug-Sep 2026 (2026Q3, partial): 42 trades, -11.1 bp/trade, -4.5%; 2026Q4
to 16 Nov: 42 trades, -6.2 bp/trade, -2.6%.** Both negative in simulation. The kill switch (6.2) counts paper trades,
and there are none yet, so it is not triggered; but if Q4 ends negative, the end-of-Q1-2027 review should treat this
as two negative quarters of evidence, not one. Do not retune A on this data (rules section 7).

**Working notes for the next chat**
- This session ran inside the Claude desktop app on Damian's laptop: Claude can run WSL (`wsl.exe -e bash <script>`)
  from PowerShell itself, so tests, fresh_oos.py and the dashboard no longer need Damian to paste commands. Trading
  commands (b-check, a-enter, a-exit, setup, flatten, a-test) and installing the scheduler stay Damian's call.
- Develop against a scratch copy of `data/paper/*.csv` by setting `BTC_BOT_PAPER_DIR` (ledger.py honours it) so the
  real append-only logs stay clean. `.claude/launch.json` lets Claude's browser pane preview the HTML.
- Two manual `dashboard` rows sit in `runs.csv` for 16 Nov (22:32 and 22:36 UTC): test runs, not scheduler runs.

---

## 12. Session of 16 Nov 2026 night (23:00-23:30 UTC): JSON export + Vite front end

Damian asked for "an actual front end" in Vite. The Python engine was left exactly where it is (the scheduler, the
WSL commands and tonight's first paper run depend on `code/` paths); the app lives in a new `frontend/` folder.

**Data contract.** `code/dashboard.py` now also writes `data/paper/dashboard.json` (`payload()`, schema 1: every
number the HTML shows, JSON-safe, no NaN). `write_json()` is atomic. Three tests added (`T4_json`): payload complete
and NaN-free, empty-logs payload, `clean()` conversions. 61 tests total, all pass in WSL. The scheduled 23:10 task
therefore refreshes both the static HTML and the JSON every day; the HTML stays as the no-Node fallback.

**App.** `frontend/` = Vite 6 + React 18 + TypeScript 5.6 + Recharts 2 (Node 24 is on Windows; Smart App Control
let esbuild/rollup run). `src/types.ts` mirrors the JSON; `src/api.ts` fetches `data/dashboard.json` every minute
(refetch keeps the previous frame at reduced opacity); `src/theme.ts` = system/light/dark toggle in localStorage.
Sections match the HTML page: signals, B, A, combined, kill switches (icon + word, never colour alone), operations
grid with hover notes, alerts. Charts: paper (blue, solid) vs expected (grey, dashed) vs buy & hold (orange, dashed);
the blue/orange pair passed the data-viz palette validator in light and dark; chart chrome is themed through CSS
variables so Recharts renders both modes from one markup; y-axis ticks are computed (Recharts' auto domain misfires
with one point). Vendor code is split into `vendor-charts` / `vendor` chunks.
- Dev: `cd frontend && npm install && npm run dev` (or double-click `frontend/dev.cmd`) -> http://127.0.0.1:5173.
  `vite.config.ts` serves `../data/paper` at `/data` so the app reads the live file.
- Build: `npm run build` -> `frontend/dist/` (static, relative paths) + `dist/data/dashboard.json` copied in by
  `scripts/copy-data.mjs`. Checked in the browser pane via the built site on localhost:8765 (the pane's site policy
  blocked the dev-server origin; `.claude/launch.json` has configs for both).
- No console errors; all sections render from the real `dashboard.json` (1 B switch, A empty, bear row).

**Not done / ideas:** a date-range filter row (the dataviz guidance wants presets above the charts: trivial once
there are more than a few days of data); a "monthly live vs backtest" table (same gap as the HTML); hosting `dist/`
somewhere reachable from the phone (any static host; the JSON would need copying there daily).

**Later the same night (23:30-23:40 UTC): README, design pass, git, GitHub.**
- `README.md` rewritten as a short purpose + get-started page with a Guides table linking every other document.
- Front end given a quieter visual system (translucent header with pill nav and an Auto/Light/Dark segmented control,
  a "Right now" hero card, inset tiles and tables, hairlines instead of borders); checked in both themes.
- Git repository initialised on `main` (git and `gh` live in WSL, not Windows; `core.filemode false`,
  `.gitattributes` normalises line endings). Excluded by `.gitignore`: node_modules, dist, caches, the daily
  dashboard html/json and logs, dry-run state, `btc_1h.csv.bak`, the zip snapshot, `_to_delete/`, the WSL
  transcript, `.claude/`. Commits are authored with the GitHub no-reply address.
- **Public GitHub repository: https://github.com/damiandamian181061-bit/btc-strategy-project** (created and pushed
  16 Nov 2026 ~23:36 UTC, Damian chose public). Routine: in WSL, `git add -A && git commit -m "..." && git push`.
  The paper logs under `data/paper/*.csv` are tracked, so a commit after a run records the day's rows.
