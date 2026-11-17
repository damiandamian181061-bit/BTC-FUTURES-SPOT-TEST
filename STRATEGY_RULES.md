# Strategy Rules: B (trend) and A (evening window)

**The rulebook.** This file states exactly what the system does, to the minute. If code, a backtest or a discussion
disagrees with this file, either the code is wrong or this file must be updated *on purpose*, with the reason noted in
the change log at the bottom.

Version 1.1, 16 Nov 2026. Includes the look-ahead correction to A's filter (see section 5).
All times are **UTC**. All prices are Binance **BTCUSDT**.

---

## 0. The system in one paragraph

Two independent parts. **B** holds Bitcoin while its price is above its 50-day average and holds cash when it is not.
It is the main engine and trades about 20 times a year. **A** buys Bitcoin at 21:00 and sells it at 23:00 UTC on days
when the price is above its 200-day average, using limit orders only. It is a small overlay and trades about 216 times a
year. Neither part uses stop-losses, take-profits, shorting or doubling. Size is always a fixed fraction of the
account's current value.

---

## 1. Definitions (used by both strategies)

| Term | Exact meaning |
|---|---|
| Hourly candle `H` | Binance spot BTCUSDT 1h kline, labelled by its **open** time. The "21:00 candle" covers 21:00:00-21:59:59 |
| Daily close of day D, `C[D]` | close of day D's 23:00 hourly candle = the price at **00:00 UTC on D+1**. Code: `hourly.close.resample("1D").last()` |
| `SMA50[D]` | average of `C[D-49] ... C[D]` (50 completed daily closes, ending with day D) |
| `SMA200[D]` | average of `C[D-199] ... C[D]` (200 completed daily closes) |
| Account value `E` | everything: B's holding (BTC at market price + cash) + A's sub-account equity. Revalued at every decision |
| bp | basis point = 0.01%. 10 bp = 0.10% |
| Maker / taker | maker = your limit order rests on the book and someone trades against it (cheaper); taker = you cross the spread (dearer) |

If fewer than 50 (B) or 200 (A) daily closes exist, there is no signal: B is in cash, A does not trade.

---

## 2. Strategy B: 50-day trend (main position)

### 2.1 Rule
At **00:00 UTC** on day D, once the previous day has closed:

```
if  C[D-1] > SMA50[D-1]:   target = LONG  (hold BTC worth 1.0 x E)
else:                      target = CASH  (hold 0 BTC)
```
Strictly greater than. A close exactly equal to the average = CASH.

### 2.2 Execution
1. ~00:01 UTC: run `datafeed.py` to download the 23:00 candle that has just closed. **If it fails (exit code not 0),
   do nothing and send an alert.** Never trade on stale data.
2. Compute the target. If the target equals the current state, **do nothing** (most days).
3. If it differs: buy (CASH->LONG) or sell everything (LONG->CASH). Time is not critical: market order, or a limit
   order at the touch that is re-priced until filled within ~15 minutes.
4. Log: date, `C[D-1]`, `SMA50`, target, order, fill price, fee, slippage vs the 00:00 price.

### 2.3 What B never does
No stop-loss, no take-profit, no partial exits, no adding to a winner, no shorting below the average (tested: worse
in both periods), no overriding the signal by hand. The **only** exit is the close crossing back below SMA50.

### 2.4 Instrument
Spot BTC is the default (no funding costs, legal for retail in the UK and Thailand). See section 4.3 for the sizing
issue this creates when A runs alongside it.

### 2.5 What to expect from B (backtest, Apr 2020 - Jul 2026, after fees)
| Period | Return | Max drawdown | Sharpe | Buy & hold (same period) |
|---|---|---|---|---|
| In-sample 2020-22 | +65.9%/yr | -57.9% | 1.02 | +36.6%/yr, DD -76.6% |
| Out-of-sample 2023 - Jul 2026 | +48.2%/yr | -26.5% | 1.17 | +45.2%/yr, DD -53.0% |
| Whole period | +55.6%/yr | -58.0% | 1.07 | +41.4%/yr, DD -76.6% |
| **Fresh holdout 1 Aug - 15 Nov 2026** | **+24.5% total** | **-6.9%** | | +3.9% total, DD -25.9% |

- ~20 switches a year; long ~54% of days.
- **Most long spells lose.** Of 63 long spells, only 25% made money. Median spell is 4 days long; the average spell
  made +9.4%, because the winners are huge (best +414% in 2020-21) and the losers are small (worst -9.9%). This is
  normal for trend-following: you sit through many small whipsaw losses to be in for the big moves. **Losing 4-5
  switches in a row is expected, not a sign it's broken.**
- Bad year: 2022, -50% (choppy bear, repeated false starts), vs -64% for buy & hold.
- Years: 2020 +314%, 2021 +127%, 2022 -50%, 2023 +140%, 2024 +78%, 2025 +4%, 2026 to 15 Nov +15%.

---

## 3. Strategy A: 21:00-23:00 UTC window (overlay)

### 3.1 Rule
On day D:

```
20:55 UTC   P = current BTCUSDT price (live ticker)
            if  P > SMA200[D-1]:  trade today      (SMA200 of the 200 closes up to and including yesterday)
            else:                 no trade today
21:00 UTC   enter long, size = 1.0 x E
22:55 UTC   exit everything
```
Strictly greater than. **Important:** the filter uses yesterday's SMA200 and the live price at 20:55, **not** today's
closing price (today's close happens at 00:00, after the trade). The original backtest made that mistake; see section 5.

### 3.2 Execution (step by step)
| Time (UTC) | Action |
|---|---|
| 20:55 | Pre-check: price vs `SMA200[D-1]`. Log both. If below, stop for the day. Also stop if the exchange or data is unavailable |
| 21:00:00 | Place a **post-only** (maker-only) limit **buy** at the best bid for size `1.0 x E / price` |
| 21:00-21:05 | If the bid moves up, cancel and re-post at the new best bid (still post-only). Partial fills are kept |
| 21:05 | Cancel anything unfilled. **If nothing filled, skip the day. Never chase with a market order.** Log the fill rate |
| 22:55 | Place a post-only limit **sell** at the best ask for the whole position |
| 22:55-23:00 | Re-post at the new best ask if it moves |
| 23:00 | Anything still open is closed **at market**. The exit matters more than the fee: A never holds past 23:00 |

Log every order: time, price, size, filled size, fee, slippage vs mid-price at 21:00 / 23:00, funding paid.

### 3.3 What A never does
No stop-loss inside the window (2-hour exposure; worst historical window -4.3%). No holding past 23:00. No market
entries. No increasing size after a loss. No trading when the 20:55 check says no. No trading other hours.

### 3.4 Instrument
BTCUSDT perpetual future (USDT-margined), **isolated margin**, in a **separate sub-account** that cannot touch B's
holding. Only on a legal venue. Until then, **paper/testnet only** (UK: FCA retail ban on crypto derivatives;
Thailand: SEC proposal not adopted as of Nov 2026).

### 3.5 Why limit orders are compulsory
A's average edge is about **+6 bp before fees**. Maker fees cost ~4 bp per round trip; taker fees ~10 bp. At maker
fees A makes money; at taker fees it loses ~8-10%/yr. **The fee is the whole edge**, so a missed fill is better than
a market order.

### 3.6 What to expect from A (backtest with the corrected filter, after maker fees, 1x size)
| Period | Return | Max drawdown | Sharpe | Avg per trade |
|---|---|---|---|---|
| In-sample 2020-22 | +15.6%/yr | -10.3% | 1.07 | +7.8 bp |
| Out-of-sample 2023 - Jul 2026 | +11.2%/yr | -8.8% | 1.02 | +4.4 bp |
| Whole period | +13.0%/yr | -10.6% | 1.04 | +5.7 bp |
| **Fresh holdout 1 Aug - 15 Nov 2026** | **-7.0% total** | -9.2% | | **-8.6 bp** (84 trades) |

- ~216 trades a year; zero in a deep bear (none at all in 2022). Win rate 51.6%: barely more than a coin flip, and
  the edge is in slightly bigger wins. Best window +5.5%, worst -4.3%.
- Years: 2020 +28%, 2021 +16%, 2022 0% (no trades), 2023 +5%, 2024 +24%, 2025 +13%, 2026 to 15 Nov -7%.
- **Status: on probation.** The Aug-Nov 2026 holdout was A's worst stretch on record (~3 standard errors below the
  backtest average). One bad quarter does not trigger the kill switch (6.2), but A stays on paper until it proves
  itself with real fills.

---

## 4. Running them together

### 4.1 Portfolio states
| Price vs averages | B | A | Exposure 21:00-23:00 | Exposure other 22 h |
|---|---|---|---|---|
| Above SMA50 and SMA200 (bull) | LONG 1x | trades 1x | **2x long** | 1x long |
| Above SMA200, below SMA50 (pullback) | CASH | trades 1x | 1x long | 0 |
| Below SMA200, above SMA50 (early recovery) | LONG 1x | off | 1x long | 1x long |
| Below both (bear) | CASH | off | 0 | 0 |

(Strictly, B uses yesterday's close vs SMA50 and A uses the 20:55 price vs SMA200, so on crossing days the row can
change between 00:00 and 20:55. Each rule is applied as written; there is no conflict because A is flat at 00:00.)

**Current state (16 Nov 2026 00:00 UTC):** close 65,351, SMA50 79,844, SMA200 72,978 -> **bear row: B CASH, A off.**

### 4.2 Combined performance (backtest, corrected A filter, A at 1x)
| Period | B + A | Max DD | Sharpe | Buy & hold |
|---|---|---|---|---|
| In-sample 2020-22 | +91.7%/yr | -57.9% | 1.21 | +36.6%/yr |
| Out-of-sample 2023 - Jul 2026 | +64.8%/yr | -23.9% | 1.34 | +45.2%/yr |
| Whole period | +75.9%/yr | -58.0% | 1.25 | +41.4%/yr |
| Fresh holdout Aug-Nov 2026 | +15.8% total | -10.4% | | +3.9% total |

Years: 2020 +428%, 2021 +163%, 2022 -50%, 2023 +151% (B&H +156%), 2024 +120% (B&H +121%), 2025 +18% (B&H -6%),
2026 to 15 Nov +7% (B&H -25%). The system does not beat buy & hold every calendar year; it wins by losing far less in
bears. A at 2x was +98.8%/yr whole-period in backtest but only +8% in the holdout (vs +16% at 1x): **stay at 1x**.

### 4.3 Sizing (and an open problem)
- Both parts are sized from the **current** total account value `E`, re-measured before every order. After a loss,
  positions get smaller automatically; after a win, bigger. **Never double after a loss.**
- The backtest assumes B is long **1.0 x E** and A, during its window, is long **another 1.0 x E** at the same time.
- **Open problem for step 4:** if B is spot and A's collateral sits in a separate sub-account (planned: ~1/3 of `E`,
  so A's 1x E position is ~3x leverage on that collateral, needing a ~30% move in 2 hours to liquidate), then B can only
  hold ~2/3 of `E` in BTC, not 1.0x. Options to decide: (a) accept B at ~0.67x (lower return and drawdown than the
  backtest); (b) run B as a 1x-notional perpetual too (adds funding cost; needs a legal venue); (c) put less collateral
  in A's sub-account (higher leverage there; e.g. 10% collateral means a ~10% two-hour move liquidates, and the worst
  seen was -4.3%). Until decided, paper trading should record B at 1.0x E to match the backtest.

Worked example (E = £10,000, bull state, BTC = 80,000): B holds 0.125 BTC. At 21:00 A buys a further 0.125 BTC on
the perpetual (notional £10,000) with post-only limit orders and sells it by 23:00. If A loses 1% in the window,
E falls to ~£9,900 and the next day both parts are sized from £9,900.

### 4.4 Local times (for checking the bot is awake)
| UTC | UK winter (GMT) | UK summer (BST) | Bangkok (UTC+7) |
|---|---|---|---|
| 00:00-00:15 B check/switch | 00:00 | 01:00 | 07:00 |
| 20:55 A pre-check | 20:55 | 21:55 | 03:55 |
| 21:00-21:05 A entry | 21:00 | 22:00 | 04:00 |
| 22:55-23:00 A exit | 22:55 | 23:55 | 05:55 |

---

## 5. Correction log: A's filter (16 Nov 2026)

The original `backtest.py` filtered A with `daily_close[D] > ma200[D]`, i.e. day D's **closing** price, known at 00:00
on D+1, three hours **after** the window. That is look-ahead bias. The live-feasible rule (section 3.1) uses the 20:55
price vs `SMA200[D-1]`; in backtests the 20:55 price is approximated by the close of the 20:00 candle. The two
disagree on 11 of 2,404 days.

| | Original (look-ahead) | Corrected |
|---|---|---|
| A out-of-sample | +14.0%/yr, +5.5 bp/trade | +11.2%/yr, +4.4 bp/trade |
| A whole period | +15.2%/yr, +6.5 bp/trade | +13.0%/yr, +5.7 bp/trade |
| B + A whole period | +79.2%/yr, Sharpe 1.29 | +75.9%/yr, Sharpe 1.25 |

B was never affected (it already used yesterday's close). Since step 3 (16 Nov 2026) `backtest.py` and `fresh_oos.py`
use the corrected filter via `signals.py` (`--original-filter` reproduces the old figures). `docs/STRATEGY_WRITEUP.md`
still shows the original figures. **This file is the reference.**

Residual check: the proxy (20:00 candle close = price at 21:00) is 5 minutes after the 20:55 decision. Using the
19:00 candle close (price at 20:00, an hour before) instead: A whole period +13.1%/yr (vs +13.0%), out of sample
+10.5%/yr (vs +11.2%). The proxy choice does not change the conclusion.

---

## 6. Risk rules and kill switches (non-negotiable)

### 6.1 Risk rules
1. Size from current `E` only. No martingale, ever.
2. A: isolated margin, separate sub-account, flat by 23:00 every day.
3. B's holding must be in an account A's margin cannot touch.
4. A at 1x until 6 months of paper/live results confirm fill rate and slippage; 2x only after that, and only if
   drawdowns stay inside the backtest range.
5. Exchange outage during A's window: hedge on a second exchange if possible; otherwise accept up to 2 hours of risk.
6. Any failed data update, missing candle at decision time, or mismatch between live and computed signal: **no trade
   + alert**. Missing a trade is cheap; trading on bad data is not.
7. Log everything daily; compare with backtest expectations monthly.

### 6.2 Kill switches and review triggers
| Trigger | Action |
|---|---|
| A: rolling 90-day average per trade negative for **two consecutive quarters** | Stop A, full review. (Counted on paper trades: none yet. Context from the holdout, simulated on actual candles: Aug-Sep 2026 -11.1 bp/trade over 42 trades, Q4 2026 to 16 Nov -6.2 bp over 42: both negative. Next check end of Q1 2027) |
| A paper trading: fill rate < 80% **or** average slippage > 2 bp | A is not viable at these fees. Do not go live |
| A paper trading: realised average per trade more than 3 bp below backtest | Do not go live; review |
| B: more than ~40 switches a year | Regime has changed; review (backtest ~20/yr) |
| B: drawdown beyond -58% (worst backtest) | Stop and review |
| Either: live signal differs from what the backtest code computes on the same data | Stop; it's a bug until proven otherwise |

---

## 7. What is NOT allowed (the overfitting guard)

- Changing 50, 200, 21:00, 23:00, the fee assumptions or the filters **because of data after 31 Jul 2026**. That data
  is the only untouched test; using it to tune spends it. Any future change needs a written reason, a new test on
  data that was not used to pick it, and an entry in the change log.
- Discretionary overrides ("it looks like it'll keep falling, skip B's buy").
- Trading the 4-year halving cycle from the calendar (breaks on the 2024 cycle; two cycles of evidence).
- Adding stops/targets to "improve" the backtest.

---

## 8. Implementation checklist (what the code must do)

| Module | Must do | Status |
|---|---|---|
| `datafeed.py` | append closed 1h candles, validate, `daily_closes()`, `latest_price()` | built, tested, run live 16 Nov 2026 |
| `signals.py` | `b_target` at 00:00 (`C[D-1] > SMA50[D-1]`), `a_allowed` at 20:55 (`P > SMA200[D-1]`); vectorised versions matching the corrected backtest exactly; no-look-ahead test | built + 19 tests pass, 16 Nov 2026 |
| Paper harness | A's order sequence (section 3.2), B's switch (section 2.2), full logging | built 16 Nov 2026 (`harness.py`, `orders.py`, `ledger.py`; 18 tests + dry run); scheduler + dashboard next |
| Reporting | fill rate, slippage, fees, funding, live vs backtest per month; kill-switch checks (6.2) | `dashboard.py` built 16 Nov 2026 (8 tests): fill rate, slippage real/demo, fees, funding, paper vs expected per trade and per period, all 6.2 checks daily; monthly table still to add |
| Scheduler | runs at 00:01, 20:55, 21:00, 21:05, 22:55, 23:00 UTC daily (+ dashboard 23:10); alerts on failure | installed 16 Nov 2026 22:42 UTC (`scheduler/install_tasks.ps1`, 5 tasks); alerts = log + dashboard for now |

---

## 9. Change log

| Date | Version | Change | Reason |
|---|---|---|---|
| 16 Nov 2026 | 1.0 | Rules as decided in the research phase (`docs/STRATEGY_WRITEUP.md`) | |
| 16 Nov 2026 | 1.1 | A's filter = 20:55 price vs SMA200 of closes up to yesterday (was: day's own close vs SMA200) | Original used information from after the trade (look-ahead). All A and B+A numbers restated |
| 16 Nov 2026 | 1.1 | Added sizing open problem (4.3), A probation status, local-time table | Found while writing the rules / from the Aug-Nov holdout |
| 16 Nov 2026 | 1.1 | No rule change. `signals.py` implements sections 2.1 and 3.1; backtest.py / fresh_oos.py now use it | Step 3 |
| 16 Nov 2026 | 1.1 | No rule change. Paper trading sizes each strategy from its own demo account (B = 1.0 x spot account, A = 1.0 x futures account, isolated 3x). Harness built (`code/harness.py`, `orders.py`, `ledger.py`) | Each account reconciles to the backtest's 'B alone' / 'A alone' at 1x; live sizing (4.3) still open |
| 17 Nov 2026 | 1.1 | No rule change. Code moved from `code/` into the `btc_bot` package (`backend/src/btc_bot/`); same modules and tests, plus a read-only FastAPI server and Docker | Project structure only; module names below still apply |
| 16 Nov 2026 | 1.1 | No rule change. `code/dashboard.py` built: computes every 6.2 trigger daily from the paper logs and recomputes each logged decision with `signals.py`. Status note added to the 6.2 A-quarters row (simulated holdout quarters both negative) | Step 4 reporting; the note is context only, the switch still counts paper quarters |
| 17 Nov 2026 | 1.1 | No rule change. The scheduled bot moved from the laptop to the DigitalOcean Droplet (cron, same UTC times; `deploy/digitalocean/README.md`) | The laptop slept through the 17 Nov 20:55/21:00 runs |
| 17 Nov 2026 | 1.1 | No rule change, execution fix. A commands started before 20:50 UTC now never open a window: a-precheck and a-enter do nothing (WARN alert), and a-exit closes any leftover position at market at once, booked to the previous day. Tests: `backend/tests/test_a_window_guard.py` | A late catch-up after midnight was taken as the NEW day's window, so a-enter could post a buy until 21:05 and a-exit could hold past 23:00. That would break 3.2 and 3.3 |
