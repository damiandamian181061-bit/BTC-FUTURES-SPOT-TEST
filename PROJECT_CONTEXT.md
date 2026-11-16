# BTC Trend + Evening-Window Trading System: Project Context & Handover

**Owner:** Damian Craddock
**Created:** 16 November 2026, from a research chat with Claude
**START HERE in a new chat:** `HANDOVER_STEP5_START.md` (16 Nov 2026 23:00: harness built and run live on the demo accounts; first real B trade logged; dashboard built (`code/dashboard.py`, its section 11); scheduler installed 16 Nov 22:42 UTC, paper run live from 17 Nov; next: watch the first week). Previous: `HANDOVER_STEP4_START.md` (16 Nov 2026: step 3 done; Binance Demo accounts + keys set up; evening session built the paper-trading harness `code/harness.py` + `orders.py` + `ledger.py` + `fakebinance.py`, 49 tests pass; sections 12-13 say what is next: Task Scheduler + dashboard).
**Earlier handover:** `HANDOVER_STEP3.md` (16 Nov 2026: `signals.py` built and tested, look-ahead fixed in the backtest, step 4 next). Read it after this file. Previous: `HANDOVER_STEP2.md` (data feed, fresh holdout, look-ahead found).
**Exact strategy rules (the rulebook):** `STRATEGY_RULES.md`. Where numbers differ from this file, STRATEGY_RULES.md is current (look-ahead-corrected).
**Purpose of this file:** everything a new chat (or a collaborator) needs to pick the project up: how we got here, what was decided and why, the exact strategy, what is built, and what happens next. Read this first; read `docs/STRATEGY_WRITEUP.md` for the full numbers.

---

## 1. One-paragraph summary

We started with a martingale idea (double the position after every losing futures trade, cap the losing streak, restart with a new account). Simulation and real Bitcoin data showed it has zero expected value before costs, negative after, and that no cap, split, risk-reward ratio or leverage changes that. We then tested Bitcoin's hourly data (Binance, Oct 2019 – Jul 2026) for a real edge, with a strict in-sample / out-of-sample split and fees included. Two things held up: a 50-day trend filter and a 21:00–23:00 UTC long window with a 200-day trend filter and limit orders. Combined, they returned about +76%/yr over 6.3 years (look-ahead-corrected; +79%/yr in the original backtest) versus +41%/yr for buy-and-hold, with roughly half the drawdown out of sample, and beat buy-and-hold in every halving-cycle phase. **Decision: build and paper-trade this two-part system. Martingale is dropped.**

---

## 2. Folder contents

```
project/
├── PROJECT_CONTEXT.md          <- this file
├── docs/STRATEGY_WRITEUP.md    <- full research write-up: data, every test, every table, limitations
├── data/btc_1h.csv             <- Binance BTCUSDT 1h candles, UTC, 2019-10-01 .. 2026-07-31 (59,869 rows)
├── code/build_dataset.py       <- rebuilds the CSV from raw Binance monthly zips
├── code/analysis.py            <- autocorrelation, hour-of-day, volume tests, strategy comparisons
├── code/backtest.py            <- the combined B+A portfolio backtest; prints all tables, draws charts
├── code/datafeed.py            <- live data feed: appends new closed Binance 1h candles, rebuilds data/btc_1d.csv
├── code/test_datafeed.py       <- offline tests for the feed (fake Binance API, temp folder)
├── code/fresh_oos.py           <- fresh out-of-sample check on data from 2026-08-01 (backtest maths, unchanged)
├── code/signals.py            <- signal engine: B target (00:00 UTC) and A filter (20:55 UTC); used by bot AND backtest
├── code/test_signals.py       <- 19 tests for signals.py (match backtest, no look-ahead, edge cases)
└── charts/equity_curves.png, drawdowns.png, hour_of_day.png (+ holdout_equity.png after fresh_oos.py)
```
Run `python3 code/backtest.py` from the project folder to reproduce everything (corrected A filter, data to 2026-07-31; `--original-filter` for the v1.0 numbers). Needs pandas, numpy, matplotlib. On Damian's laptop, run Python inside WSL.

---

## 3. How the chat went (chronological, with the key numbers)

1. **Martingale plan proposed:** double after each loss on daily futures, hold open-to-close, split into 50- or 100-trade accounts to dodge the 39%-per-1,000-trades blow-up risk.
   *Finding:* exact blow-up odds (survive 9 losses, die on 10th): 2.0% per 50 trades, 4.4% per 100, 38.5% per 1,000, 91.4% per 5,000. Splitting into 20 × 50-trade accounts gives 33% chance of at least one blow-up, nearly the same as 38.5%. EV is zero; one blow-up wipes ~40 good accounts. (Optional stopping theorem.)
2. **Cap at 5 losses:** lose 31 units once per ~62 trades, +1 otherwise. Still zero EV; ~47% chance of being down after a year, 59% with 3% costs.
3. **1:2 risk-reward:** with random entries the win rate becomes 1/3; EV still zero. Doubling on top triples the frequency of 5-loss streaks (13% vs 3%).
4. **Cap 5 on one account for 100 trades:** 52% chance of being up, median +11 units, mean 0. Needs ~127 units of capital to survive 99% of runs (218 at 1:2).
5. **£10 per unit on futures:** too small. On Micro E-mini S&P (MES, $5/point) a £10 stop is 2.5 points, i.e. noise. Costs of ~$2 per round trip are 10–15% of a $13 risk; at that cost level 74–81% of 100-trade runs lose.
6. **Crypto futures:** fractional sizing fixes the stop problem; Binance USDT-M fees are 0.02% maker / 0.05% taker; fees as a share of risk depend on stop width. Legal issue: FCA retail ban on crypto derivatives still in force (UK); Thailand SEC proposed retail access to overseas crypto derivatives 31 Aug 2026, not yet adopted. **Damian said to set the law aside for the analysis.**
7. **Leverage with £10:** fees and edge scale together, so leverage cannot fix a negative-after-fees trade; 50× liquidates on a <2% move and kills the wider stop. Verdict: £10 is for learning the platform, not for testing the strategy.
8. **"Is there a theory that helps?"** Yes: (a) doubling after a loss only makes sense if losses predict wins (mean reversion), which is testable; (b) Kelly criterion for sizing once an edge exists (f = p − q/b); (c) gambler's ruin for survival maths.
9. **Got hourly data** (user could only find daily). Found Binance monthly zips mirrored on GitHub; built a clean 59,869-hour dataset.
10. **Tests on real data:**
    - Mean reversion exists but is small and fading: P(up | prev down) 55.9% (2019–22) → 52.2% (2023–26).
    - Doubling made every direction rule worse except "always long" in a +280% bull market (and that rule had −85% drawdown in 2019–22).
    - Hour-of-day pattern is noise except 21:00–23:00 UTC, positive in both periods (matches Quantpedia). Nets money only at maker fees.
    - Volume does not predict return; busiest hours (12–16 UTC) are slightly negative.
11. **Four-year cycle:** fits 2020 cycle, breaks on 2024 cycle (the "bear" two years before the 2024 halving were +123%). Two cycles = untestable. Use a moving average to follow the cycle from price instead.
12. **Candidate strategies tested** (fees in, IS/OOS): 50-day trend filter and 21–23 UTC window with 200-day filter were the only two that held up. "Fade yesterday" was +72%/yr IS and −36%/yr OOS, the textbook faded edge.
13. **Cycle-phase split:** Strategy A positive in all 8 phases, never worse than −10%. Strategy B captured most of the bulls and sat out the bears roughly flat.
14. **Decision:** run B as main position, A on top. Combined backtest: +94%/yr IS (DD −58%), +69%/yr OOS (DD −24%), +79%/yr overall, Sharpe 1.3; beat buy-and-hold in every phase; calendar 2022 still −50%.
15. **Decision:** build it, paper-trade first, start A at 1× not 2×.

---

## 4. Key decisions and the reasoning

| Decision | Reason |
|---|---|
| Drop the martingale entirely | Zero EV before costs, negative after; on real BTC data it increased drawdown under every rule. Biggest position lands in crashes. |
| Sizing is fixed-fraction (position = k × current account), never doubling | Shrinks after losses, grows after wins; keeps drawdowns bounded. This is the Kelly direction. |
| Trend filter = 50-day SMA, long/cash (not long/short) | Best Sharpe in both periods (1.04 / 1.17). Shorting below the MA was worse in both periods. |
| Window = 21:00–23:00 UTC | Only hours positive and significant in both halves; independently published; rest of the hourly pattern had 0.03 correlation between periods. |
| Window filter = 200-day SMA | Near-identical results in both periods (Sharpe 1.61 / 1.58, DD −10% / −9%); better than 50-day or volatility filters. |
| Limit orders only for A | At taker fees (10 bp) A loses 8–10%/yr; at maker fees (4 bp) it earns 14–17%/yr. The fee is the entire edge. |
| A overlay at 1×, not 2× | 2× gives +106%/yr vs +79%/yr with the same drawdown, but it's leverage on one pattern with two cycles of evidence. Earn the right to 2× with live data. |
| Don't trade the 4-year cycle from the calendar | Breaks on the 2024 cycle; n = 2. |
| Paper trade before any money | Fill rate on limit orders is the one thing the backtest can't tell us, and A's edge is only 3–4 bp/day after fees. |
| £10 live account is for learning the platform only | Fees at that size eat the edge; 100 trades on £10 is luck either way. |

---

## 5. The exact strategy (what the bot has to do)

### Strategy B: trend position (main holding)
- **Instrument:** spot BTC (or 1× long perpetual; spot avoids funding and is legal everywhere).
- **Signal time:** 00:00 UTC daily, after the daily candle closes.
- **Signal:** daily close vs simple moving average of the last 50 daily closes (00:00 UTC closes).
- **Rule:** close > SMA50 → target 100% of account in BTC. close ≤ SMA50 → target 0% (cash/stablecoin).
- **Execution:** only trade when the target changes. Market or limit, not time-critical. Expect ~19 switches/year ≈ 2%/yr in taker fees.
- **No stop-loss, no take-profit, no doubling.** Exit is the SMA crossing.
- **Known behaviour:** whipsaws in choppy bears (82 long days in 2022, still −50% that year). Worst historical drawdown −58%. Captured ~70% of 2020–21 bull, ~90% of 2023 recovery.

### Strategy A: evening window (overlay)
- **Instrument:** BTC perpetual future (USDT-margined), isolated margin, separate sub-account.
- **Pre-check 20:55 UTC:** current mark price vs SMA200 of daily 00:00 UTC closes. Below → **no trade today**. (Expect ~150 trading days/year; zero in deep bears like 2022.)
- **Entry 21:00 UTC:** limit buy, size = 1.0 × current total account value (B holding + A sub-account), priced at the best bid (post-only / maker). If unfilled by 21:05, cancel and skip the day. **Never chase with a market order.**
- **Exit 22:55 UTC:** limit sell at best ask for the full position. If unfilled by 23:00, close at market (the exit matters more than the fee).
- **No stop-loss inside the window.** Exposure is 2 hours; worst historical window −4.3%.
- **Expected profile:** ~52% win rate, +6.5 bp average per trade after maker fees, Sharpe ~1.2–1.6, max DD ~10% at 1×.
- **Kill switch:** if the rolling 90-day average per trade is negative for two consecutive quarters, stop A and review. If limit-order fill rate in paper trading is < 80% or average slippage > 2 bp, A is not viable at these fees.

### Portfolio states
| Price vs averages | B | A | Net exposure 21–23 UTC | Net exposure other 22 h |
|---|---|---|---|---|
| Above 50d and 200d (bull) | long 1× | trades 1× | 2× long | 1× long |
| Above 200d, below 50d (pullback) | cash | trades 1× | 1× long | 0 |
| Below 200d, above 50d (early recovery) | long 1× | off | 1× long | 1× long |
| Below both (bear) | cash | off | 0 | 0 |

### Risk rules (non-negotiable)
1. A's position is always sized from *current* account value. Never increase size after a loss.
2. Isolated margin for A with only ~1/3 of account as collateral (3× would be the implied leverage of a 1× position on that collateral; liquidation needs a ~30% move in 2 hours, never seen).
3. B's holding lives in spot/a separate account that A's margin can't touch.
4. Max overlay 1× until 6 months of live/paper results confirm fill rate and slippage; 2× only after that and only if drawdown stays within backtest range.
5. Exchange outage during 21–23 UTC: have a second exchange account ready to hedge; if neither is reachable, accept the window risk (that's why there's no overnight hold).
6. Daily log of every signal, order, fill price, fee, slippage and funding. Monthly comparison of live vs backtest expectations.

---

## 6. What to watch out for (the ways this fails)

- **Fill rate.** The edge is 3–4 bp after maker fees. Taker execution destroys it. This is the first thing paper trading must measure.
- **Edge decay.** The 21–23 UTC effect is public. Watch A's rolling average; stop if it goes negative for 2 quarters.
- **Overfitting.** The window and the filters were chosen from in-sample data and prior research, then tested once out of sample. Don't tune parameters on the 2023–26 data; that would burn the only out-of-sample test. Future tuning needs new data (post-July 2026).
- **Weaker cycles.** 2024 bull year was +33% vs +550% in 2020. Expect less.
- **Whipsaw costs on B** in sideways markets; ~19 switches/yr is fine, 40+ would mean the regime has changed.
- **Fat tails in 2 hours.** Flash crashes, exchange halts, stablecoin de-pegs. Keep A's leverage modest and never hold past 23:00.
- **Regulation.** UK retail cannot legally trade crypto derivatives (FCA ban in force; crypto ETNs were opened to retail in Oct 2025 but derivatives were not). Thailand SEC consultation closed 30 Sept 2026, no adoption date. Strategy B on spot is legal anywhere. Strategy A on futures needs a legal venue; until then, paper trade only.
- **Tax.** Frequent trading (A does ~150–216 trades/yr) has tax consequences in both the UK (CGT, possibly trading income) and Thailand. Get this checked before going live.

---

## 7. What is built vs what is not

**Built (in this folder):**
- Clean hourly dataset, Oct 2019 – Jul 2026.
- Analysis scripts: autocorrelation, hour-of-day, volume, cycle phases, strategy comparisons.
- Combined backtest with fees, IS/OOS split, cycle-phase tables, charts.
- Full research write-up.

- **Data feed (step 2, built 16 Nov 2026):** `code/datafeed.py`. Pulls closed BTCUSDT 1h candles from the Binance REST API
  (data-api.binance.vision, falls back to api.binance.com), re-checks the last 24 stored hours against Binance before
  appending, rejects duplicates / bad OHLC / gaps > 24 h / hourly moves > 30%, writes atomically (keeps `btc_1h.csv.bak`),
  rebuilds `data/btc_1d.csv`, cross-checks daily closes against Binance 1d candles, logs every run to `data/update_log.csv`.
  Exit codes: 0 ok, 1 check failed (nothing written), 2 no network. `--dry-run`, `--price`.
  For later modules: `from datafeed import load_hourly, daily_closes, latest_price`. `daily_closes()` is identical to
  backtest.py's `daily_close` (tested). Tested offline (7 tests incl. byte-identical rebuild of Jun-Jul 2026).
  Not yet run against live Binance: the build sandbox blocks exchange hosts, so the first live run is on Damian's machine.
- **Fresh OOS check:** `code/fresh_oos.py` reproduces backtest.py exactly (engine check +79.2%/yr, -58%, Sharpe 1.29;
  Apr-Jul 2026 phase row matches) and reports the holdout from 2026-08-01, compared with every same-length window of the
  2023-26 OOS period. As of 31 Jul 2026: B = CASH (close 62,888 < SMA50 63,440), A filter OFF (close < SMA200 71,497).
- **First live run (16 Nov 2026, via WSL on Damian's laptop; Windows Smart App Control blocks numpy):** 2,570 new hours
  to 2026-11-16 01:00 UTC, no gaps, overlap check vs live Binance passed (so the research dataset matches Binance).
  **Fresh holdout 1 Aug - 15 Nov 2026 (107 days, parameters unchanged):** buy & hold +3.9% (DD -25.9%);
  B alone +24.5% (DD -6.9%, 4 switches, sat out the Nov fall); A alone -6.8% (85 trades, win 48.2%, -8.2 bp/trade vs
  +6.5 backtest, t -1.72, worse than every 107-day window of the 2023-26 OOS); B+A +16.1% (DD -10.4%).
  Read: B behaved as designed. A had its worst stretch on record: one bad quarter, not yet the kill-switch
  (two negative quarters). Do NOT retune A's window/filter on this data. Keep A in paper trading; review at end of Q1 2027.
  State at 16 Nov 00:00 UTC: close 65,351, SMA50 79,844, SMA200 72,978 -> B CASH, A OFF.
- **Look-ahead bias found (16 Nov 2026):** backtest.py's A filter (`daily_close > ma200` on day D) uses the 00:00 close
  of D+1, after the 21-23 UTC window. Live-feasible version (20:55 price vs `ma200.shift(1)`): A OOS +11.2%/yr
  (was +14.0%), A overall +13.0%/yr (was +15.2%), B+A overall +75.9%/yr (was +79.2%). Conclusion unchanged; fix in
  step 3. Details: HANDOVER_STEP2.md section 7. **Fixed 16 Nov 2026 (step 3)**: backtest.py and fresh_oos.py now use the
  corrected filter via signals.py and reproduce the corrected numbers exactly.
- **Signal engine (step 3, built 16 Nov 2026):** `code/signals.py` + `code/test_signals.py` (19 tests, all pass).
  B = `C[D-1] > SMA50[D-1]`, A = 20:55 price `> SMA200[D-1]`; `current_state()` refuses to signal (exit 1) on stale
  data or a missing 23:00 candle. Matches backtest B on every day; no-look-ahead proven by truncation and by
  scrambling future data. Details: HANDOVER_STEP3.md.

- **Paper-trading harness (step 4, built 16 Nov 2026 evening):** `code/harness.py` (b-check / a-precheck / a-enter / a-exit /
  status / setup / a-test / flatten, `--dry-run`), `code/orders.py` (post-only loops, real-vs-demo book, fees, slippage),
  `code/ledger.py` (append-only CSV logs under `data/paper/`), `code/fakebinance.py` (offline fake exchange),
  `code/test_harness.py` (18 tests). Venue: Binance Demo Trading (spot for B, USD-M futures for A, two API keys kept
  outside the project folder). Sizing in paper: each strategy 1.0x its own demo account. Details: HANDOVER_STEP4_START.md s.12.

- **Dashboard (step 4, built 16 Nov 2026 late evening):** `code/dashboard.py` + `code/test_dashboard.py` (8 tests).
  Read-only report from `data/paper/*.csv` -> `data/paper/dashboard.html` + terminal summary: separate B and A
  sections plus a combined total, paper vs "expected" (backtest maths on the same days), real-mid and demo-mid
  slippage side by side, every kill switch of STRATEGY_RULES 6.2, a missed-run grid, alerts, feed status. Scheduled
  as the 5th task at 23:10 UTC via `run.sh dashboard`. Details: HANDOVER_STEP5_START.md section 11.
- **Front end (16 Nov 2026 night):** `dashboard.py` also writes `data/paper/dashboard.json`; `frontend/` is a Vite +
  React + TypeScript app that renders it (charts, tables, kill switches, run grid, light/dark, auto-refresh).
  `cd frontend && npm run dev`. Root `README.md` describes the layout. Details: HANDOVER_STEP5_START.md section 12.

- **Scheduler (installed 16 Nov 2026 22:42 UTC):** five Windows Task Scheduler tasks (b-check 00:01, a-precheck 20:55,
  a-enter 21:00, a-exit 22:55, dashboard 23:10 UTC) call `code/run.sh` through WSL on Damian's laptop. The 90-day
  paper run is live from 17 Nov 2026.

**Not built yet:**
- Monthly live-vs-backtest table (the dashboard already compares per trade and over the whole paper period).
- Alerting (Telegram/email) for fills, misses, errors.
- Funding and slippage model in the backtest (to add once paper-trading data exists).

---

## 8. Next steps (in order)

1. **Set up a new project chat** with this folder as context. Start with the build plan below.
2. **[DONE 16 Nov 2026] Data feed:** script that downloads the latest Binance BTCUSDT 1h and 1d candles daily (data.binance.vision monthly/daily zips or the REST API) and appends to `data/btc_1h.csv`. Extend the backtest to Aug–Nov 2026 as a fresh out-of-sample check.
3. **[DONE 16 Nov 2026] Signal engine:** a Python module `signals.py` that, given the daily closes, returns `b_target` (0/1) at 00:00 UTC and `a_allowed` (True/False) at 20:55 UTC. Unit-test it against the backtest's signals for 2020–2026 (they must match exactly).
4. **Paper-trading harness:** connect to Deribit testnet (free, has BTC perpetuals, Damian already uses Deribit data for the options project) or Binance Futures testnet. Implement A's order logic: post-only limit at 21:00, cancel at 21:05, limit exit 22:55, market fallback 23:00. Log everything.
5. **Run A on paper for 90 days.** Measure: fill rate, slippage vs mid, realised fee, realised vs backtest P&L. Go/no-go thresholds: fill rate ≥ 80%, slippage ≤ 2 bp, realised average per trade within 3 bp of backtest.
6. **Run B on paper in parallel** (trivial: one signal a day). Confirm switch count and that live SMA50 matches backtest SMA50.
7. **Add funding + slippage to the backtest** using the paper-trading measurements. Re-run. If A still clears +10%/yr out of sample, proceed.
8. **Live, small, legal.** B on spot can go live anywhere once comfortable. A waits for a legal futures venue in whichever country Damian is resident; start at 1×, review quarterly, consider 2× after 6 months of results inside backtest range.
9. **Write it up for the CV** as "Out-of-sample backtest and paper-trading of a trend + intraday-seasonality Bitcoin strategy": the martingale rejection, the OOS method, the costs analysis and the kill-switch rules are what a finance interviewer will care about.

---

## 9. Useful constants

| Item | Value |
|---|---|
| Binance USDT-M fees (regular user) | maker 0.02%, taker 0.05% per side; 10% off paying in BNB |
| Micro E-mini S&P (MES) | $5/point, tick 0.25 = $1.25; day margin ~$50, overnight ~$1,700–2,900 |
| TFEX SET50 futures | THB 200/point, tick 0.1 = THB 20 |
| Quantpedia window | buy 21:00 UTC, sell 23:00 UTC; reported 40.6%/yr 2015–2022, costs not reported |
| Halving dates | 11 May 2020, 20 Apr 2024, next expected ~2028 |
| Kelly fraction | f = p − (1−p)/b, where b = reward/risk ratio |
| Backtest split | IS: 2019-10-01 to 2022-12-31; OOS: 2023-01-01 to 2026-07-31 |
| Data gaps | 17 gaps > 1 hour, largest 6 hours, no missing months |

---

## 10. Open questions for the next chat

- Which exchange/testnet for paper trading: Deribit (already used for the options project) or Binance Futures testnet (matches the fee schedule used in the backtest)?
- Where will the bot run: a VPS (needs to be up at 00:00, 20:55, 21:00, 22:55, 23:00 UTC every day) or a laptop with a scheduler?
- Spot vs perpetual for B? Spot is simpler and legal; perpetual allows one account for both but adds funding.
- How to handle the day the signal flips during A's window (B goes to cash at 00:00 while A is flat, so no conflict, but confirm).
- Residency for tax and regulation when live trading starts (UK term-time vs Thailand summers).
