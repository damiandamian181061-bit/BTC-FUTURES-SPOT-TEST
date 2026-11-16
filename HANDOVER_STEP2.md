# Handover: Step 2 (data feed) session, 16 Nov 2026

**Read order for a new chat:** `PROJECT_CONTEXT.md` (master file, whole project) -> this file (what happened in the
step 2 session, in detail) -> `STRATEGY_RULES.md` (exact rules for A and B, corrected numbers; the reference for
`signals.py`) -> `docs/STRATEGY_WRITEUP.md` only if research numbers are needed.

**Where we left off:** step 2 is finished and has been run live. Step 3 (`signals.py`) is next and has a detailed spec
in section 9 below. One correction must be built into step 3: the backtest's Strategy A filter has a small look-ahead
bias (section 7).

---

## 1. Summary in five lines

1. Built `code/datafeed.py` (downloads new Binance BTCUSDT 1h candles, checks them, appends), `code/test_datafeed.py`
   (7 offline tests) and `code/fresh_oos.py` (runs the unchanged backtest maths on data after 31 Jul 2026).
2. First live run on Damian's laptop: 2,570 new hours (1 Aug - 16 Nov 2026 01:00 UTC), no gaps, all checks passed.
3. Fresh holdout (1 Aug - 15 Nov 2026, 107 days): B +24.5% vs buy & hold +3.9%; A -6.8% (its worst stretch on record);
   B+A +16.1%.
4. Found a look-ahead bias in A's 200-day filter in `backtest.py`. Correcting it lowers A from +15.2% to +13.0%/yr
   overall (OOS +14.0% -> +11.2%) and B+A from +79.2% to +75.9%/yr. Conclusion unchanged; numbers slightly lower.
5. Python on Damian's Windows laptop runs through **WSL (Linux)**, because Windows Smart App Control blocks numpy.

---

## 2. How the session went (chronological)

1. Read `PROJECT_CONTEXT.md` and all code. Data: `data/btc_1h.csv`, 59,869 rows, 2019-10-01 00:00 to 2026-07-31 23:00 UTC.
2. **Tried to download data from Claude's side.** Both Claude environments (the cloud workspace and the shell on
   Damian's machine that Claude can drive) block every exchange/data host by policy: data.binance.vision,
   api.binance.com, data-api.binance.vision, Deribit, Coinbase, Kraken, CoinGecko, CryptoCompare, Yahoo, Hugging Face,
   Kaggle. Only GitHub and PyPI are reachable. Searched GitHub for a mirror of Aug-Nov 2026 Binance candles: none
   (one repo had only `.CHECKSUM` files, another had futures data only, not spot).
   -> **Decision:** build the feed to run on Damian's laptop (normal internet), and test it offline against a fake
   Binance API built from the existing data.
3. Wrote `datafeed.py`. Tested against a local mock server: truncated data to 31 May, let the feed rebuild Jun-Jul ->
   output **byte-identical** to the original file (incl. 2-page pagination, and a stop-mid-day-then-resume run).
   Fault tests: shifted prices -> overlap check fails, nothing written; 48 h hole -> fails, nothing written;
   unreachable host -> exit code 2.
4. Wrote `fresh_oos.py`. Engine check: reproduces backtest.py exactly (+79.2%/yr, maxDD -58%, Sharpe 1.29), and its
   Apr-Jul 2026 run matches backtest.py's "since Apr 2026" phase row (-15%/-29%, -3%/-13%, 0%, -3%/-13%).
5. Turned the mock tests into `code/test_datafeed.py`. The tests caught a real bug (`load_hourly()` had bound the file
   path at import time) -> fixed. Confirmed the real data file was never modified (MD5 identical to the copy in
   `btc_strategy_project.zip`).
6. **Running it on the laptop (troubleshooting, so the next chat doesn't repeat it):**
   - `python` -> "Python was not found" (only the Microsoft Store shortcut existed).
   - Installed Python 3.12 with `winget install -e --id Python.Python.3.12`.
   - `py -m pip install pandas numpy matplotlib` worked, but importing numpy failed:
     `ImportError: DLL load failed while importing _sfc64: An Application Control policy has blocked this file.`
     That is **Windows 11 Smart App Control** blocking unsigned DLLs.
   - Options: (a) turn Smart App Control off (can't be turned back on without resetting Windows), or (b) use WSL.
     **Chose WSL** (already installed; Linux user `damian`, machine `DCDC`). Installed `python3-pandas` and
     `python3-matplotlib` via apt. Small tweak to `fresh_oos.py` (`DataFrame.map` -> `apply(... .map)`) so it works
     with older pandas versions.
7. Live run succeeded (results in section 6). Updated `PROJECT_CONTEXT.md`.
8. While writing this handover, re-read the backtest for the step 3 spec and found the A-filter look-ahead (section 7).

---

## 3. How to run things (Damian's laptop)

Open PowerShell -> type `wsl` -> Enter. Then:

```bash
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project"
python3 code/datafeed.py          # update data (add --dry-run to check without writing, --price for current price)
python3 code/fresh_oos.py         # holdout report from 2026-08-01; --start/--end for other windows
python3 code/test_datafeed.py     # offline tests (should end with OK)
python3 code/backtest.py          # original research tables (note: now reads the extended data, see section 8)
```

One-liner for the routine update:
```bash
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/datafeed.py && python3 code/fresh_oos.py
```

Notes:
- Do **not** use Windows Python for this project (Smart App Control blocks numpy). Windows Python 3.12 is installed
  but only the standard library works there.
- Claude can read and edit the project folder and run code in it from its side, but **cannot download market data**
  (network policy). Anything needing Binance has to be run by Damian in WSL, who then pastes or screenshots the output.
- In the next chat, give Damian one-line commands to paste into WSL, since copy-paste of single lines is easiest.

---

## 4. What `code/datafeed.py` does (reference)

| Item | Detail |
|---|---|
| Source | Binance spot REST `GET /api/v3/klines`, symbol BTCUSDT, interval 1h; 1000 candles per request, paginated |
| Hosts (in order) | `data-api.binance.vision` (public market-data host), `api.binance.com`, `api1`, `api2`. Env var `BTC_FEED_BASE_URL` overrides (used by tests) |
| Closed candles only | drops any candle whose close_time >= now, so a still-forming hour is never stored |
| Overlap check | re-downloads the last 24 stored hours; any OHLC difference > 1e-6 or volume difference -> fail |
| New-candle checks (fail) | not time-ordered, duplicates, not on the hour, price <= 0, negative volume, high/low inconsistent with open/close, gap > 24 h, hourly move > 30% |
| Warnings (still writes) | gaps of 2-24 h (genuine Binance outages exist: 17 in the research data), hourly moves > 10%, daily close differing from Binance's own 1d candle |
| Writing | old file kept as `data/btc_1h.csv.bak` (one generation), new file written to `.tmp` then renamed (atomic) |
| Daily file | `data/btc_1d.csv`: OHLCV per UTC day + `hours` column (count of hourly candles that day), rebuilt every run |
| Log | `data/update_log.csv`: run time, status (OK / NO_NEW / FAILED / NO_NETWORK), rows added, first/last new, warnings, errors |
| Exit codes | 0 ok or nothing new; 1 a check failed, nothing written; 2 Binance unreachable |
| Timestamps | handles ms and microseconds (Binance spot zip files switched to microseconds in 2025) |
| Functions for later modules | `load_hourly(path=None)`, `daily_closes(hourly=None)`, `build_daily(h)`, `latest_price()`, `fetch_klines(interval, start_ms, end_ms)` |

**Daily close convention (important for step 3):** `daily_closes()` = `hourly.close.resample("1D").last()`. The value
labelled day D is the close of the 23:00 candle, i.e. the price at **00:00 UTC on D+1**. Same label convention as
Binance 1d candles. Identical to `daily_close` in `backtest.py` (tested).

Dependencies: pandas only (numpy via pandas); network via Python's built-in `urllib` (no `requests` needed).

## 5. Tests (`code/test_datafeed.py`)

Runs a fake Binance API in a background thread (data from `data/btc_1h.csv`, 2026 onwards), works in a temp folder,
never touches `data/`. 7 tests, all passing on 16 Nov 2026:
1. rebuild 31 May -> 31 Jul is byte-identical to the original and needs 2 pages; `daily_closes()` equals backtest
2. second run is a no-op
3. forming candle not stored (now = 10:30 -> last stored 09:00), then resume gives byte-identical file
4. prices shifted 0.1% -> overlap check fails, file unchanged
5. 48-hour hole -> fails, file unchanged
6. `--dry-run` writes nothing (not even the log)
7. `latest_price()` returns the ticker price

---

## 6. Live run and fresh holdout results (16 Nov 2026)

**Feed:** `OK, 2570 rows, 2026-08-01 00:00 -> 2026-11-16 01:00 UTC`, no warnings, no gaps. The overlap check passing
means the research dataset (originally rebuilt from a GitHub mirror of Binance files) matches live Binance data.
Dataset is now 62,439 rows. `btc_1h.csv.bak` = the original 59,869-row file.

BTC by month (first -> last close): Aug 62,938 -> 78,581 | Sep 78,652 -> 83,624 | Oct 83,509 -> 77,582 |
Nov (to 16th) 77,690 -> 64,571.

**Holdout 1 Aug - 15 Nov 2026 (107 complete days), parameters unchanged** (backtest maths as written, i.e. including
the look-ahead in A's filter; corrected numbers in section 7):

| | Total | Max DD | Notes |
|---|---|---|---|
| Buy & hold | +3.9% | -25.9% | |
| B alone | +24.5% | -6.9% | 78/107 days long, 4 switches (~14/yr vs ~19 backtest); cash all of November |
| A alone (1x) | -6.8% | -9.2% | 85 trades (85/107 days allowed), win 48.2%, avg -8.2 bp/trade (backtest +6.5), t -1.72, best +1.17%, worst -1.74% |
| B + A (1x) | +16.1% | -10.4% | |

Monthly (B&H / B / A / B+A): Aug +25.0 / +20.3 / +2.1 / +22.8 | Sep +6.4 / +6.4 / -6.2 / -0.2 |
Oct -7.2 / -2.7 / -0.2 / -3.0 | Nov -15.8 / 0.0 / -2.4 / -2.4 (%).

Versus every 107-day window in the 2023-26 OOS period: B+A at the 56th percentile (median +9.5%); A at the **0th
percentile** (worse than every past window; 10th pct -2.0%, median +4.1%); B&H 47th.

**Interpretation agreed in chat:**
- B behaved exactly as designed: rode August, sat in cash for the November fall.
- A's -8.2 bp/trade is ~3 standard errors below the +6.5 bp backtest expectation (per-trade sd ~44 bp, n = 85). That
  is more than bad luck, but it is one quarter, and past windows overlap so the "0th percentile" overstates it.
  Possible edge decay (the 21-23 UTC effect is public, flagged as a risk from the start).
- **Kill switch not triggered**: the rule needs the rolling 90-day average negative for **two consecutive quarters**.
  This is quarter one.
- **Do not retune** A's window or filter on Aug-Nov data: that would spend the only fresh out-of-sample data.
- A stays in the plan **on paper only** (costs nothing; step 4 still needs to measure fill rates). Review at end of
  Q1 2027. B is the stronger half.

**Signal state at 16 Nov 2026 00:00 UTC:** close 65,351 | SMA50 79,844 | SMA200 72,978 -> **B = CASH, A = OFF**
(the "bear" row of the portfolio-state table).

---

## 7. Look-ahead bias found in Strategy A's filter (must be fixed in step 3)

**The bug.** In `backtest.py` (and `fresh_oos.py`, which copies it):
```python
A = (wd - MAKER).where(daily_close > ma200).fillna(0)
```
`daily_close` for day D is the price at 00:00 UTC on D+1, and `ma200` for day D includes that close. So the decision to
trade the 21:00-23:00 window on day D uses a price from **after** the window. On days near the 200-day line, a
window that rose helps push the close above the average (trade counted) and one that fell helps push it below (trade
skipped). Strategy B is fine: `pos = (...).shift(1)` uses only the previous day's close.

**The live rule (what the bot can actually do):** at 20:55 UTC on day D, compare the current price with the average
of the 200 completed daily closes up to D-1 (`ma200.shift(1)`). In historical data, the closest proxy for the 20:55
price is the close of the 20:00 hourly candle (= price at 21:00, the entry price).

**Impact (measured 16 Nov 2026):** the two filters disagree on 11 of 2,404 days.

| | Backtest (look-ahead) | Live-feasible filter |
|---|---|---|
| A in-sample 2020-22 | +16.8%/yr, Sharpe 1.15, +8.3 bp/trade | +15.6%/yr, Sharpe 1.07, +7.8 bp |
| A out-of-sample 2023-Jul 26 | +14.0%/yr, Sharpe 1.28, +5.5 bp | **+11.2%/yr, Sharpe 1.02, +4.4 bp** |
| A overall | +15.2%/yr, +6.5 bp, 1,359 trades | **+13.0%/yr, +5.7 bp**, 1,359 trades |
| B+A overall | +79.2%/yr, DD -57.9%, Sharpe 1.29 | **+75.9%/yr**, DD -58.0%, Sharpe 1.25 |
| B+A OOS | +68.9%/yr, DD -23.9% | +64.8%/yr, DD -23.9% |
| A holdout Aug-Nov 26 | -6.8% (85 trades, -8.2 bp) | -7.0% (84 trades, -8.6 bp) |
| B+A holdout | +16.1% | +15.8% |

Conclusion unchanged (A still clears the +10%/yr bar out of sample, just barely now), but every A figure in
`PROJECT_CONTEXT.md` / `STRATEGY_WRITEUP.md` is slightly flattered. **To do in step 3:** add the corrected filter to
the backtest (suggest a flag, keeping the original for the record), re-state the headline numbers, and have
`signals.py` implement the live-feasible version. `signals.py` should be tested against the *corrected* backtest
signals, not the original ones.

Also worth knowing for step 3: with A's out-of-sample edge now ~4.4 bp/trade after maker fees, the paper-trading
go/no-go thresholds (fill rate >= 80%, slippage <= 2 bp) matter even more. 2 bp of slippage would eat about half of it.

---

## 8. Housekeeping / state of the folder

- `data/btc_1h.csv` now runs to 2026-11-16 01:00 UTC. **Re-running `backtest.py` now includes Aug-Nov 2026 in its
  "OOS" and "ALL" rows** (its OOS segment has no end date), so its printed numbers will no longer match the write-up.
  The research numbers were for data to 2026-07-31. Suggest giving backtest.py an end date of 2026-07-31 in step 3.
- `data/btc_1h.csv.bak`: the original research file (59,869 rows). Keep it.
- `btc_strategy_project.zip`: snapshot from before this session (doesn't include the new code).
- `project/`: empty folder (left over from unzipping), safe to delete.
- `_to_delete/`: a stray test chart and a Python cache folder. Claude can't delete files on Damian's machine;
  Damian can delete this folder.
- Root `STRATEGY_WRITEUP.md` and `docs/STRATEGY_WRITEUP.md` are copies of each other; neither has been updated with
  the holdout or the look-ahead correction yet.

---

## 9. Step 3 spec: `code/signals.py`

**Purpose:** one place that turns data into the two trading decisions, used by both the bot and the backtest so they
can't drift apart.

**Functions (suggested):**
```python
b_target(daily_close: pd.Series, day) -> int
    # 1 if daily_close[day-1] > mean(daily_close[day-50 .. day-1]) else 0.  Decided at 00:00 UTC on `day`.
a_allowed(daily_close: pd.Series, price_now: float, day) -> bool
    # price_now > mean(daily_close[day-200 .. day-1]).  Decided at 20:55 UTC on `day`. price_now from latest_price().
b_targets(daily_close) -> pd.Series      # vectorised, whole history (for backtest + tests)
a_allowed_series(hourly) -> pd.Series    # vectorised, proxy price = close of the 20:00 candle, ma200.shift(1)
current_state() -> dict                  # loads data via datafeed, returns b_target, a_allowed, close, sma50, sma200, timestamps
```

**Rules and edge cases to decide or handle:**
- SMA uses exactly 50 / 200 completed daily closes; fewer available -> no signal (B = 0, A = False).
- Days with fewer than 24 hourly candles (Binance outages): `resample().last()` takes the last available hour. Decide
  whether to accept (matches backtest) or flag. Suggest: accept but warn if the 23:00 candle is missing.
- At 00:00 UTC the 23:00 candle has only just closed: the bot must run `datafeed.py` first (a minute or so after
  00:00), then compute B. If the update failed (exit != 0), do not trade; alert.
- A at 20:55 needs a live price, not a candle: `latest_price()`. Log price, SMA200, and decision.
- A also needs the full 21:00 and 22:00 hours; the backtest skips days with a missing window hour. Live equivalent:
  if the exchange is down at 21:00, skip.

**Tests (must pass before step 4):**
1. `b_targets()` equals `backtest.py`'s `pos` for every day 2019-2026 (exact match).
2. `a_allowed_series()` equals the corrected live-feasible filter (section 7) for every day; also report the 11 days
   where it differs from the original backtest filter.
3. Hand-checked examples: a known crossing day for each signal.
4. `current_state()` on today's data gives B CASH / A OFF (as of 16 Nov 2026).
5. No look-ahead test: computing the signal for day D using data truncated at D-1 23:59 (B) or D 20:59 (A) gives the
   same answer as using the full dataset.

**Then:** update `backtest.py` (end date 2026-07-31 for the research numbers; corrected A filter via `signals.py`),
re-run, and update the headline numbers in `PROJECT_CONTEXT.md`.

---

## 10. Steps after that (unchanged from PROJECT_CONTEXT.md, with status)

| # | Step | Status |
|---|---|---|
| 1 | New project chat with folder as context | done |
| 2 | Data feed + fresh OOS check | **done 16 Nov 2026** |
| 3 | `signals.py` + tests (+ look-ahead fix) | **next** |
| 4 | Paper-trading harness (Deribit testnet or Binance Futures testnet): post-only limit at 21:00, cancel 21:05, limit exit 22:55, market fallback 23:00; log everything | |
| 5 | Run A on paper 90 days: fill rate >= 80%, slippage <= 2 bp, realised avg/trade within 3 bp of backtest | |
| 6 | Run B on paper in parallel | |
| 7 | Add funding + slippage to backtest from paper data; proceed only if A still clears +10%/yr OOS | |
| 8 | Live, small, legal (B spot anywhere; A needs a legal futures venue) | |
| 9 | CV write-up | |

**Open questions still open:** testnet choice (Deribit vs Binance Futures testnet); where the bot runs (VPS vs laptop.
It must be awake at 00:00, 20:55, 21:00, 22:55 and 23:00 UTC daily, and since Python runs in WSL on the laptop, a
scheduled job would need to call `wsl` from Windows Task Scheduler, or use cron inside WSL); spot vs perpetual for B;
tax/regulatory residency (UK term-time vs Thailand summers; FCA retail ban on crypto derivatives).
**Also open:** B/A sizing conflict when B is spot and A's collateral is separate (STRATEGY_RULES.md 4.3).
**New question from this session:** given A's weak holdout and the look-ahead correction, is A still worth building
into the paper harness straight away, or should step 4 start with B only and add A once the harness works?
(Recommendation in chat: keep A on paper, it costs nothing, but B first if time is short.)

---

## 11. Rules to carry into the next chat

- No parameter tuning on data after 2026-07-31. It is the only untouched test data.
- Position sizing is always from current account value; never double after a loss (martingale permanently dropped).
- Every backtest number quoted should say which version (original vs look-ahead-corrected) and which period.
- Damian runs code via WSL one-liners; Claude can edit files in the folder directly but cannot fetch market data.
