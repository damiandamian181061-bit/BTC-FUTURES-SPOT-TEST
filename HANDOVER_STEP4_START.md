# Handover for the night session of 16 Nov 2026 (~03:30 UK). SUPERSEDED as the start file by `HANDOVER_STEP5_START.md` (22:15 UK): read that first; sections 12-13 below are partly out of date (BNB fee fix, relog command, dust rule, scheduler files).

**Owner:** Damian Craddock. **Project:** BTC trend (B) + evening-window (A) trading system, built for paper trading
first and as a CV project.

**Read order for a new chat:**
1. **This file**: everything from the 16 Nov night session (step 3 done, step 4 started), plus the step 4 build plan.
2. `STRATEGY_RULES.md`: the rulebook (v1.1). Exact rules for A and B. If code disagrees with it, the code is wrong.
3. `PROJECT_CONTEXT.md`: master history of the whole project (martingale -> research -> decision).
4. Only if needed: `HANDOVER_STEP3.md` (step 3 detail), `HANDOVER_STEP2.md` (data feed, holdout, look-ahead discovery),
   `docs/STRATEGY_WRITEUP.md` (original research numbers; still shows pre-correction figures).

**Where we stopped (updated 16 Nov 2026, ~21:40 UTC):** the paper-trading harness is BUILT and passes 49 offline
tests (18 new) plus a full dry-run cycle. See section 12 for what was built this evening and section 13 for what
Damian runs next (connection check after the demo reset, `setup`, `a-test`, `status`). After that: Windows Task
Scheduler entries (section 8.6) and `dashboard.py`. Sections 1-11 below are from the night session and still apply.

---

## 1. The system in five lines (so this file stands alone)

- **B (main position):** at 00:00 UTC, if yesterday's daily close > its 50-day SMA, hold BTC worth 1.0 x account
  (spot); else hold cash. ~19-20 switches/yr. No stops/targets/shorting.
- **A (overlay):** at 20:55 UTC, if the live price > SMA200 of daily closes up to *yesterday*, buy BTCUSDT perpetual
  worth 1.0 x account at 21:00 with **post-only limit** orders (cancel at 21:05 if unfilled, never chase), sell with a
  post-only limit at 22:55, close at market at 23:00 if still open. ~216 trades/yr; none in deep bears.
- Daily close of day D = close of D's 23:00 hourly candle = price at 00:00 UTC on D+1 (Binance BTCUSDT spot, 1h).
- Size always from current account value; **never double after a loss** (martingale permanently dropped).
- **No parameter tuning on data after 2026-07-31.** That data is the only untouched test set.

Current headline numbers (look-ahead-corrected, A at 1x, after fees; research period to 31 Jul 2026):

| | Whole period (Apr 2020 - Jul 2026) | Out-of-sample (2023 - Jul 2026) | Fresh holdout 1 Aug - 15 Nov 2026 |
|---|---|---|---|
| B alone | +55.6%/yr, DD -58.0%, Sharpe 1.07 | +48.2%/yr, DD -26.5% | +24.5% total, DD -6.9% |
| A alone | +13.0%/yr, DD -10.6%, +5.7 bp/trade | +11.2%/yr, +4.4 bp/trade | **-7.0%**, 84 trades, -8.6 bp/trade |
| B + A | **+75.9%/yr**, DD -58.0%, Sharpe 1.25 | +64.8%/yr, DD -23.9% | +15.8% total, DD -10.4% |
| Buy & hold | +41.4%/yr, DD -76.6% | +45.2%/yr | +3.9%, DD -25.9% |

(Original numbers before the look-ahead fix were +79.2%/yr B+A and +15.2%/yr A; reproducible with `--original-filter`.)
A is "on probation": its holdout was its worst stretch on record, but the kill switch needs **two** consecutive
negative quarters; next review end of Q1 2027. Keep A on paper.

**Signal state on 16 Nov 2026:** close (15 Nov) 65,351 | SMA50 79,844 | SMA200 72,978 | live price ~65,073 at 02:55
UTC -> **B = CASH, A = OFF** ("bear" row: zero exposure). So the paper bot will likely sit in cash for a while; that
is correct behaviour, not a bug.

---

## 2. How this session went (chronological)

1. **Read** `PROJECT_CONTEXT.md`, `HANDOVER_STEP2.md`, `STRATEGY_RULES.md` and all code. Step 3 spec was in
   HANDOVER_STEP2 section 9.
2. **Checked the data first:** 62,439 hourly rows to 2026-11-16 01:00 UTC. No historical day is missing its 20:00,
   21:00, 22:00 or 23:00 candle (18 days have <24 candles, all other hours). The corrected vs original A filter differ
   on exactly the 11 days the handover predicted.
3. **Built `code/signals.py`** (section 4). Its output on 16 Nov matched the handover exactly.
4. **Built `code/test_signals.py`** (19 tests). Two test-side typos fixed (a rounded hard-coded SMA; a date-slice
   syntax). All 19 pass. Then changed one line (`date_range(freq="h")` -> `to_timedelta(unit="h")`) for older pandas.
5. **Fixed the look-ahead in the backtests:** `backtest.py` and `fresh_oos.py` now take signals from `signals.py`.
   - `backtest.py --original-filter` reproduces the old v1.0 numbers exactly (+79.2%/yr, A +15.2%/yr).
   - `backtest.py` (default, corrected) gives +75.9%/yr, Sharpe 1.25, A OOS +11.2%/yr, +5.7 bp, 1,359 trades: an
     exact match with HANDOVER_STEP2 section 7.
   - `backtest.py` now cuts data at 2026-07-31 by default (`--end` to change), so research numbers don't drift.
   - `fresh_oos.py` holdout (corrected): A -7.0%, 84 trades, -8.6 bp; B+A +15.8%; A at the 2nd percentile of past
     107-day windows (was "0th" with the old filter). `--original-filter` reproduces -6.8% / 85 trades / +16.1%.
   - Charts redrawn with the corrected filter (equity_curves, drawdowns, hour_of_day, holdout_equity).
6. **Residual-proxy check:** the backtest uses the 20:00 candle close (= price at 21:00) as the stand-in for the 20:55
   live price: 5 minutes late. Using the 19:00 close (an hour early) instead: A whole period +13.1%/yr (vs +13.0%),
   OOS +10.5%/yr (vs +11.2%), 1,363 vs 1,359 trades. Not material, but A's OOS margin over the +10%/yr bar is thin.
7. **Docs updated:** PROJECT_CONTEXT.md (step 3 marked done, corrected headline), STRATEGY_RULES.md (checklist,
   correction log note, change-log row: no rule change), HANDOVER_STEP3.md written.
8. **Damian ran the tests on his laptop (WSL):** first screenshot was an *older* fresh_oos output (from before the
   edits; "85 trades / +6.5"). Then ran the new commands: **19/19 tests OK**, `signals.py --live --days 5` fetched a
   live price (65,073) -> B CASH, A OFF, exit OK. (The `NaN` in today's `price_21h` is expected: 21:00 hadn't happened.)
   Pasting tip that worked: right-click or Ctrl+Shift+V in Windows Terminal.
9. **Step 4 decisions** (Damian's answers):
   - Testnet: **Binance** (Futures). Reason: same BTCUSDT contract and fee schedule as the backtest; Deribit's main BTC
     perpetual is BTC-margined (inverse), which adds conversions.
   - Machine: **his laptop with WSL**, not a VPS (for now). Asked if the device needs to be powerful: no. The bot runs 6
     times a day for a second or two; 1 CPU / 1 GB is plenty. What matters is being awake at the run times.
   - Strategies: **both B and A**, but **kept separate in the dashboard**.
10. **Found that Binance's futures testnet is now "Demo Trading"** (searched Binance docs):
    - Futures demo REST: `https://demo-fapi.binance.com` (docs: developers.binance.com, USD-M futures general info).
    - Spot demo REST: `https://demo-api.binance.com` (docs: Binance spot "Demo Mode" general info).
    - Keys are created at demo.binance.com -> account icon -> API Management, using a normal Binance login.
    - Concern raised: Binance stopped onboarding new UK users. **Resolved:** Damian already has a Binance account and
      logged into demo.binance.com fine (screenshot showed DEMO TRADING, BTC/USDT ~65,078).
11. Damian offered to send me his Binance login: **declined** (security; he did it himself in ~5 minutes).
12. **API keys created** (both "System generated" = HMAC): `btc-B-spot` and `btc-A-futures`. Both show Enable Reading,
    Enable Spot & Margin & Stock Trading, Enable Futures ticked; withdrawals not enabled. Two keys chosen on purpose:
    mirrors the rulebook's separate accounts, and one key can be rotated without stopping the other strategy.
    Keys saved in **Bitwarden**.
13. **Keys file:** created inside WSL at `~/.config/btc-bot/secrets.env` (full path `/home/damian/.config/btc-bot/secrets.env`),
    `chmod 600`, filled with nano. Deliberately **outside the project folder** so Claude (which can read the project
    folder) never sees them, and so they're never in zips/backups. Damian asked how to save in nano: Ctrl+O, Enter, Ctrl+X.
    **Never paste keys into chat.**
14. **Built `code/exchange.py`, `code/connection_check.py`, `code/test_exchange.py`** (section 5). 5/5 offline tests pass
    (incl. the HMAC example signature from Binance's docs).
15. **First live connection check on the laptop: "ALL OK: both demo accounts reachable."** Results in section 6.
16. Damian asked for this file before sleeping. Next session: build the harness (section 8).

---

## 3. Decisions log (this session)

| # | Decision | Why |
|---|---|---|
| 1 | A's filter = live 20:55 price > SMA200[D-1]; backtest proxy = 20:00 candle close | Original used the day's own 00:00 close (3 h after the window) = look-ahead. Rule already in STRATEGY_RULES v1.1 |
| 2 | One signal module (`signals.py`) used by bot AND backtests | So live and backtest signals can't drift apart (rule 6.2: any live/backtest mismatch = bug) |
| 3 | Keep the original filter callable (`--original-filter`) | For the record / reproducibility of v1.0 numbers |
| 4 | `backtest.py` stops at 2026-07-31 by default | Research numbers stay fixed as data grows; post-July data stays a holdout |
| 5 | Missing 23:00 candle of yesterday at decision time -> no trade + alert; other missing hours -> warning only | Rule 6.1.6; matches backtest's `resample().last()` for history |
| 6 | Strictly greater-than; <50/<200 closes -> no signal | STRATEGY_RULES 1, 2.1, 3.1 |
| 7 | Paper venue: Binance Demo Trading (spot for B, USD-M futures for A) | Same contract and fees as backtest |
| 8 | Two API keys, HMAC, no withdrawals | Separation of B and A; least privilege |
| 9 | Secrets in Bitwarden + `~/.config/btc-bot/secrets.env` (WSL, chmod 600), never in project folder or chat | Claude can read the project folder; keep keys out of reach and out of backups |
| 10 | Runs on the laptop via WSL for now | Damian's choice. Needs awake laptop at run times (section 8.6) |
| 11 | Build both B and A; dashboard shows them separately + a combined total | Damian's choice. A's fill rate is the main thing paper trading must measure |
| 12 | Measure slippage against the **real** Binance book, not only the demo book | Demo spread was 3.2 bp vs ~0.01 bp real (section 6) |
| 13 | Don't change the fee assumptions after seeing demo fees | Overfitting guard (STRATEGY_RULES 7); taker 0.04% vs assumed 0.05% just makes the backtest slightly conservative |

---

## 4. `code/signals.py` (step 3, built and confirmed)

| Function | Returns |
|---|---|
| `sma(daily_close, n)` | rolling mean, NaN until n closes |
| `b_targets(daily_close)` | 0/1 per day D (target FOR day D, decided 00:00 on D) = `C[D-1] > SMA50[D-1]`; day one 0 |
| `a_proxy_price(hourly, index)` | close of the 20:00 candle per day |
| `a_allowed_series(hourly, daily_close=None)` | bool per day: 20:00 close on D > `SMA200[D-1]` (corrected); missing -> False |
| `a_allowed_series_original(...)` | old look-ahead filter `C[D] > SMA200[D]` (record only) |
| `b_signal(dc, day)` / `b_target(dc, day)` | one day, closes strictly before `day`; dict: day, close, sma50, target |
| `a_signal(dc, price, day)` / `a_allowed(dc, price, day)` | one day; dict: day, price, sma200, allowed |
| `current_state(hourly=None, now=None, price_now=None)` | dict: now, day, last_candle, b_target, b_close, sma50, a_allowed, a_price, a_price_source, sma200, state (portfolio row), warnings, errors, **ok** |
| `history_table(hourly, start=None)` | per-day table: prev_close, sma50_prev, b_target, price_21h, sma200_prev, a_allowed, a_original |
| `SignalError` | raised on stale data (yesterday's close missing) or bad price (None/0/neg/NaN) |

- `current_state(now=...)` only uses candles closed by `now` (`index + 1h <= now`), so any past moment can be replayed.
- If `price_now` is None, A uses the last stored close and adds a warning ("use --live for the real 20:55 check").
- `ok = False` if yesterday's 23:00 candle is missing or any SignalError occurs -> bot must not trade, must alert.
- CLI: `python3 code/signals.py [--live] [--at "YYYY-MM-DD HH:MM"] [--days N]`; exit 0 ok / 1 do not trade.
- Imports `load_hourly, daily_closes, latest_price, NetworkError` from `datafeed.py`.

**Tests (`code/test_signals.py`, 19, all pass on Claude's side, pandas 2.3, and on Damian's WSL):**
1. B == backtest.py's original `pos` on every day, and == a plain-Python loop.
2. A == corrected filter via an independent loop on every day; differs from the original on exactly these 11 days:
   2021-09-08, 2021-09-12, 2021-12-28, 2023-01-13, 2023-08-17, 2024-07-13, 2024-08-26, 2024-09-30, 2025-03-12,
   2025-03-20 (10 in the research period) and 2026-08-19 (of 2,403 days to 15 Nov).
3. Hand-checked, cross-checked against `data/btc_1d.csv`:
   B: 1 Aug 2026 CASH (62,887.88 < 63,439.78) | 3 Aug LONG (63,570.00 > 63,406.89) | 23 Oct CASH (81,416.09 < 81,824.18)
   | 16 Nov CASH (65,351.05 < 79,843.77).
   A: **19 Aug 2026 OFF** (21:00 price 69,048.06 < SMA200 69,081.97); the original filter said ON because the 00:00 close
   on 20 Aug (69,334.79, after the window) was above SMA200[19 Aug] 69,034.94: the textbook look-ahead example.
   20 Aug ON (72,671.75 > 69,034.94) | 12 Nov OFF (71,442.02 < 73,172.86).
4. `current_state` at 16 Nov 02:40 UTC: B CASH, A OFF, close 65,351, SMA50 79,844, SMA200 72,978, "bear".
5. No look-ahead: (a) 499 days (every signal change + every 7th day) give identical signals with data truncated at
   D-1 23:59 (B) / D 20:59 (A); (b) scrambling every candle after a cutoff (x0.3-3.0 random) changes no signal up to
   the cutoff; (c) the **original** filter fails (b), proving the test can catch look-ahead.
6. Edge cases: too few closes, exact equality = CASH/OFF, stale data raises, bad price raises, missing 23:00 candle
   blocks trading, feed not yet run at 00:01 blocks trading, missing intraday hour = warning only, `now` cut-off.

---

## 5. Exchange code (step 4, started)

**`code/exchange.py`** (standard library only: urllib, hmac, hashlib, json)
- `SPOT_DEMO_URL = https://demo-api.binance.com` (override env `BTC_BOT_SPOT_URL`)
- `FUTURES_DEMO_URL = https://demo-fapi.binance.com` (override env `BTC_BOT_FUTURES_URL`). Binance has moved these
  hosts before, so they're overridable.
- `SECRETS_PATH = ~/.config/btc-bot/secrets.env` (override env `BTC_BOT_SECRETS`). Needs `B_SPOT_API_KEY`,
  `B_SPOT_API_SECRET`, `A_FUTURES_API_KEY`, `A_FUTURES_API_SECRET`.
- `load_secrets(path)` -> (dict, warnings). Strips spaces/quotes, ignores comments; raises `SecretsError` if missing/empty;
  warns if the file is readable by others. `mask(s)` shows first 4 + last 2 chars only.
- `BinanceClient(base_url, api_key, api_secret, futures=False, recv_window=5000)`:
  `get(path, params, signed)`, `post(path, params)`, `delete(path, params)` (POST/DELETE are signed),
  `sync_time()` (measures clock offset, applied to every signed timestamp), `sign(secret, query)` (HMAC-SHA256),
  raises `ExchangeError(msg, status, code)` with Binance's error code.
- `spot_client(secrets)`, `futures_client(secrets)`.
- Signing per Binance docs: HMAC-SHA256 of the full query string with the secret, `signature` appended last, key in
  header `X-MBX-APIKEY`, `timestamp` in ms, `recvWindow` default 5000.

**`code/connection_check.py`** (read-only; places NO orders; never prints secrets)
- Spot: time sync, `/api/v3/account` (canTrade, balances), `/api/v3/account/commission`, `/api/v3/ticker/price`.
- Futures: time sync, `/fapi/v3/balance` (fallback v2), `/fapi/v1/positionSide/dual`, `/fapi/v3/positionRisk`
  (fallback v2), `/fapi/v1/commissionRate`, `/fapi/v1/premiumIndex` (mark, funding), `/fapi/v1/ticker/bookTicker`.
- Exit 0 "ALL OK", 1 lists problems (hedge mode, no USDT, open position, rejected key with codes -2014/-2015/-1022).

**`code/test_exchange.py`** (5 offline tests, pass): signature equals Binance's documented example
(`c8db5682...6b71`); signed GET/POST round trip against a fake server that verifies the HMAC; wrong secret -> code
-1022; clock offset applied; secrets-file parsing/permissions/missing values.

---

## 6. First live connection check (16 Nov 2026 ~03:25 UTC, Damian's laptop): ALL OK

| | B: spot demo | A: USD-M futures demo |
|---|---|---|
| Key shown (masked) | fsGr...Fb | fBxQ...ym |
| Clock offset vs Binance | +617 ms | +565 ms (laptop ~0.6 s behind; corrected automatically; <1 s is fine) |
| Balances | 5,000 USDT + 0.05 BTC | 5,000 USDT wallet, 5,000 available |
| Permissions / mode | canTrade True; canWithdraw True (account flag, not the key; demo funds can't leave) | position mode ONE-WAY (correct for A) |
| Fees | maker 0.10%, taker 0.10% | maker 0.02%, taker 0.04% |
| Price | spot 65,152.91 | mark 65,117.70; funding +0.0093% per 8 h |
| Book | n/a | bid 65,106.40 / ask 65,127.30 = **spread 3.21 bp** |

Interpretation:
- **Fees vs backtest:** B's backtest charges 0.10% per switch, and spot demo charges 0.10% per trade: consistent.
  Futures maker 0.02% = assumption; taker 0.04% < assumed 0.05%, so the backtest is slightly conservative. Don't retune.
- **Demo book is not the real book.** Real BTCUSDT perp spread is about one tick (~0.01-0.02 bp); demo showed 3.2 bp.
  Binance's docs warn demo market data is "realistic", not real. A's edge is ~4.4 bp/trade OOS and the go/no-go is
  fill rate >= 80% and slippage <= 2 bp, so judging fills only on demo microstructure would be misleading in either
  direction. -> **The harness must snapshot the real public book** (`https://fapi.binance.com/fapi/v1/ticker/bookTicker`,
  `.../depth`, and spot `https://data-api.binance.vision/api/v3/ticker/bookTicker`) at every order event and measure
  slippage against the **real** mid. Report both "demo fill rate" and "would-have-filled on the real book" estimates.
- Spot demo starts holding 0.05 BTC while B's target is CASH. Decide at harness start: sell it to reach the CASH state,
  or reset the demo balance in the Demo Trading UI (Binance lets you reset demo balances any time).
- `positionRisk` printed no BTCUSDT line (no position yet), so margin type/leverage weren't shown. The harness must set
  **ISOLATED** margin and leverage for BTCUSDT before A's first trade.

---

## 7. Commands (Damian's laptop: PowerShell -> `wsl` -> Enter; then paste one line at a time)

Pasting in Windows Terminal: right-click or Ctrl+Shift+V. Always use WSL's `python3`, never Windows Python
(Windows Smart App Control blocks numpy's DLLs).

```bash
# daily routine (update data, then today's signals with the live price)
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/datafeed.py && python3 code/signals.py --live

# tests (each should end with OK)
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/test_signals.py
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/test_datafeed.py
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/test_exchange.py

# demo accounts, read only
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/connection_check.py

# research / holdout reports
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/backtest.py | head -20
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/fresh_oos.py

# edit the keys file (nano: paste after '=', Ctrl+O, Enter, Ctrl+X)
nano ~/.config/btc-bot/secrets.env
```

Claude's side: can read/edit/run code in the project folder via the device connection, but **cannot reach Binance or
any exchange** (network policy). Anything touching Binance is run by Damian, who sends screenshots. Claude can't
delete files in the folder (move unwanted files to `_to_delete/` instead). Claude cannot and should not read
`~/.config/btc-bot/secrets.env` (it's outside the connected folder by design).

---

## 8. NEXT: Step 4 build plan (paper-trading harness)

Goal: run B and A on Binance Demo for 90 days and measure what the backtest can't: A's fill rate, slippage, realised
fees and funding, and live-vs-backtest P&L. Everything must log; nothing may trade on bad data.

### 8.1 Files to build (suggested)
- `code/harness.py`: entry point with subcommands, each run by the scheduler:
  `b-check` (00:01), `a-precheck` (20:55), `a-enter` (21:00, manages until 21:05), `a-exit` (22:55, manages until 23:00),
  `status`, `flatten` (emergency: close A, cancel all), `dry-run` flag on everything.
- `code/orders.py`: order helpers on top of `exchange.py` (post-only place/re-price/cancel loops, market fallback,
  fills/fees lookup, exchange filters: tick size, step size, min notional from `exchangeInfo`).
- `code/ledger.py`: append-only CSV logs (or one SQLite file) under `data/paper/`: signals, orders, fills, daily equity,
  runs (incl. "missed: machine off"), alerts.
- `code/dashboard.py`: builds a self-contained `dashboard.html` (or prints a text report) with **separate B and A
  sections plus a combined total** (Damian asked for this).
- `code/test_harness.py`: offline tests against a fake Binance that simulates fills, partial fills, rejects, outages.

### 8.2 B logic (00:01 UTC, spot demo, key btc-B-spot)
1. Run `datafeed.py`; if exit != 0 -> no trade, alert. 2. `current_state()`; if not `ok` -> no trade, alert.
3. If target == current holding state -> log and stop (most days). 4. Else buy/sell to target 1.0 x E (spot).
   Not time-critical: limit at the touch, re-priced, market after ~15 min if unfilled (STRATEGY_RULES 2.2).
5. Log date, C[D-1], SMA50, target, order(s), fill price, fee, slippage vs the 00:00 price **and vs the real book**.
6. **Catch-up:** if the laptop was off at 00:01, run on wake (B isn't time-critical); log the delay.

### 8.3 A logic (futures demo, key btc-A-futures)
- One-time setup: one-way mode (already), `POST /fapi/v1/marginType` ISOLATED, `POST /fapi/v1/leverage` for BTCUSDT.
- 20:55: `current_state(price_now=live price)`; if not ok or not allowed -> log and stop. Also stop if exchange/data
  unavailable. Snapshot the real book.
- 21:00:00: post-only **buy** at best bid (USD-M futures: LIMIT with timeInForce **GTX** = post-only; verify in docs),
  qty = 1.0 x E / price rounded to step size. 21:00-21:05: if the bid moves up, cancel and re-post at the new bid;
  keep partial fills. 21:05: cancel the rest; **if nothing filled, skip the day; never market-buy.**
- 22:55: post-only **sell** (reduce-only) at best ask for the whole position; re-post if the ask moves.
- 23:00: anything still open -> **market** reduce-only sell. A never holds past 23:00.
- If the laptop is asleep at 21:00 -> day logged as **MISSED_MACHINE_OFF**, not as unfilled (keeps fill rate honest).
  If it wakes between 21:00 and 23:00 holding a position -> exit immediately.
- Log every order: time, side, price, qty, filled qty, fee, slippage vs real mid at 21:00/23:00, funding paid.

### 8.4 Sizing (open problem, STRATEGY_RULES 4.3; decide early next session)
The backtest has B long 1.0 x E and, during 21-23, A long another 1.0 x E. In demo, B and A sit in two separate demo
accounts (5,000 USDT each now; spot also holds 0.05 BTC). Options:
- (a) **Virtual equity E tracked by the harness** (e.g. start 10,000 USDT notional), B sized 1.0 x E on spot and A
  1.0 x E on futures, each account just an execution venue. Matches the backtest; needs spot balance >= E (reset demo
  balance if needed). *Claude's leaning: (a), because STRATEGY_RULES 4.3 says paper trading should record B at 1.0 x E.*
- (b) Each strategy sized from its own account's value (simpler; 5,000 each).
Either way: re-measure E before every order; never increase size after a loss.

### 8.5 Measurements and go/no-go (STRATEGY_RULES 6.2)
- A fill rate >= 80%; average slippage <= 2 bp (vs **real** mid); realised average per trade within 3 bp of backtest.
- B: switch count (~19-20/yr; >40 = regime change); live SMA50/SMA200 must equal `signals.py` on the same data.
- Report demo-book and real-book versions side by side. Monthly live-vs-backtest comparison.

### 8.6 Scheduling on the laptop (Damian's choice; no VPS)
- Run times (UTC): 00:01 (B), 20:55, 21:00, 22:55 (A; the entry/exit commands run their own 5-minute loops).
  Local: UK winter = same as UTC; UK summer (BST) = +1 h; Bangkok = +7 h (A window 03:55-06:00 there).
- Windows **Task Scheduler** tasks calling `wsl -e bash -lc 'cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py <cmd>'`.
  Use "Wake the computer to run this task" and set triggers in UTC (or tick "Synchronize across time zones") so BST
  changes don't shift them. Alternative: cron inside WSL (needs systemd enabled; WSL must be running).
- Laptop settings: when plugged in, sleep = Never; closing the lid = Do nothing; keep plugged in; WiFi on.
- Every run writes a heartbeat; the dashboard shows missed runs.

### 8.7 Alerts (later in step 4)
Telegram bot or email for: data update failed, signal not ok, order rejected, unfilled entry, market-fallback exit,
position still open after 23:00, missed runs. Start with a log + dashboard banner; add Telegram once the core works.

### 8.8 Build order for the next session
1. Agree sizing option (8.4) and what to do with the 0.05 BTC on spot (sell vs reset).
2. `orders.py` + `ledger.py` + fake-exchange tests (offline, Claude's side).
3. `harness.py` with `--dry-run`; Damian runs `status` and dry-runs live.
4. One supervised **tiny** live-demo test of A's order sequence outside the window (e.g. `harness.py a-test` that
   places a post-only order far from the market, cancels it, and logs), then of B's switch.
5. Task Scheduler setup (Claude writes the exact steps / an XML or PowerShell one-liner).
6. `dashboard.py` with separate B / A sections.
7. Start the 90-day paper run. First A trade only happens once the price is back above SMA200 (~72,978 and falling);
   B buys when the close goes back above SMA50 (~79,844). Until then the bot correctly does nothing but log.

---

## 9. Open questions (carried forward)
- Sizing / account structure for paper (8.4) and later live (STRATEGY_RULES 4.3: B spot ~0.67x vs perp vs less
  collateral for A).
- Laptop vs VPS: laptop for now; revisit if missed runs pile up (a small VPS in an EU/Asian region would do; Binance
  blocks US IPs).
- B spot vs perpetual for live trading.
- Tax/regulatory residency for live trading (UK term-time vs Thailand summers; FCA retail ban on crypto derivatives;
  Thailand SEC proposal not adopted as of Nov 2026). Paper trading is unaffected.
- `STRATEGY_WRITEUP.md` (both copies) still shows the original look-ahead figures; update before using it for the CV.

## 10. Rules that carry into every chat
- No tuning on data after 2026-07-31. No changes to 50 / 200 / 21:00 / 23:00 / fee assumptions without a written
  reason, a test on unused data and a change-log entry in STRATEGY_RULES.md.
- Size from current account value only. Never double after a loss.
- Any failed data update, missing candle or live-vs-backtest signal mismatch = **no trade + alert**.
- Every backtest number quoted must say which version (original vs corrected) and which period.
- Damian runs code via WSL one-liners; Claude edits files directly but can't fetch market data or reach Binance.
- Never put API keys in chat or in the project folder.

## 11. Folder inventory (16 Nov 2026)
```
HANDOVER_STEP4_START.md  <- this file (start here)
STRATEGY_RULES.md        <- rulebook v1.1
PROJECT_CONTEXT.md       <- master history
HANDOVER_STEP3.md        <- step 3 detail + step 4 progress notes
HANDOVER_STEP2.md        <- data feed, holdout, look-ahead discovery
STRATEGY_WRITEUP.md, docs/STRATEGY_WRITEUP.md   <- original research write-up (pre-correction numbers)
btc_strategy_project.zip <- snapshot from before the step 2 session
code/  datafeed.py, test_datafeed.py (step 2) | signals.py, test_signals.py (step 3) |
       exchange.py, connection_check.py, test_exchange.py (step 4 start) | backtest.py, fresh_oos.py (now use signals.py) |
       analysis.py, build_dataset.py (research) | __pycache__/ (harmless)
data/  btc_1h.csv (62,439 rows to 2026-11-16 01:00 UTC), btc_1h.csv.bak (original 59,869-row research file: keep),
       btc_1d.csv, update_log.csv
charts/ equity_curves.png, drawdowns.png, hour_of_day.png, holdout_equity.png (all corrected filter)
project/ (empty, leftover), _to_delete/ (stray files; Damian can delete)
Outside the folder: ~/.config/btc-bot/secrets.env in WSL (API keys; chmod 600), copies in Bitwarden.
```

---

## 12. Evening session, 16 Nov 2026: harness built (sections 8.1-8.5 done except dashboard/scheduler)

**Decisions**
- **Sizing for paper trading = each strategy from its OWN demo account** (option (b) of 8.4): B = 1.0 x spot account
  value, A = 1.0 x futures account value (`totalMarginBalance`). Reason: each account's result lines up directly with
  the backtest's "B alone" / "A alone" at 1x; the combined curve is the sum of the two daily returns (as in the backtest);
  A's go/no-go tests don't depend on size; everything reconciles to a real balance. Logged in STRATEGY_RULES change log
  as a paper-trading choice, not a rule change. Live sizing (4.3) is still open.
- Damian chose to **reset the demo balances** rather than sell the 0.05 BTC. Run `connection_check.py` after the reset.
- A's isolated leverage: **3x** (1x notional on ~1/3 of the account as margin, rule 4.3/6.1.2; liquidation ~30% away).
- Dry runs log to `data/paper/dryrun/` (fake exchange, auto-fills, state kept in `fake_*.json`); real runs to `data/paper/`.
- `test_datafeed.py` fixed (1 line): its fixture now uses Jan-Jul 2026 only; it had been growing with the live file.

**Files built (all standard library + pandas; no new packages)**
| File | What |
|---|---|
| `code/orders.py` | `Filters` (tick/step/min-notional rounding, Decimal), `book`/`real_book` (demo vs REAL public book), `spot_equity`, `futures_account/position`, `funding_paid`, `futures_setup` (one-way + ISOLATED + leverage, idempotent), `place_limit` (GTX on futures / LIMIT_MAKER on spot), `place_market`, `cancel`, `cancel_all`, `open_orders`, `fills_for` (fees), `fee_usdt`, `slippage_bp`, **`work_order`** (keep one post-only order at the touch, re-post when bid rises / ask falls, keep partials, cancel at deadline, never cross), `market_rest` |
| `code/ledger.py` | append-only CSVs under `data/paper/`: `runs` (heartbeat), `alerts`, `signals`, `orders`, `fills`, `equity`, `a_windows` (one row per A day, last row wins), `b_days`. Fixed columns; unknown field = error. `Run` context manager writes the heartbeat and turns exceptions into alerts |
| `code/fakebinance.py` | fake spot + futures demo on 127.0.0.1 with Binance shapes/error codes (-2010, -2011, -4046, GTX -> EXPIRED), scripted books/fills, auto-fill for dry runs, save/load state |
| `code/harness.py` | commands: `status`, `setup`, `b-check`, `a-precheck`, `a-enter`, `a-exit`, `a-test`, `flatten`; flags `--dry-run`, `--force` (dry-run only), `--deadline-min`, `--poll`, `--leverage` |
| `code/test_harness.py` | 18 tests: rounding, entry fill, re-pricing (bid up twice), partial fill kept, deadline cancel, nothing filled, would-cross on both venues, exit + market fallback (reduce-only, realised P&L), spot fee in BTC, setup idempotent, errors propagate, ledger round trip + heartbeat + dry-run folder |

**Harness behaviour (matches STRATEGY_RULES 2.2 / 3.2)**
- `b-check` (00:01): `datafeed.update()`; exit != 0 -> alert, no trade. `current_state()` not ok -> alert, no trade.
  Holding LONG if BTC >= 50% of spot equity. Target == holding -> `b_days` NO_CHANGE. Else post-only at the touch for 15
  min (`work_order`), then `market_rest`. Logs fills with slippage vs the real mid and vs yesterday's close. Runs late
  (laptop asleep) -> still runs, `delay_min` recorded.
- `a-precheck` (20:55): live spot price (`datafeed.latest_price`) vs SMA200[D-1] -> `a_windows` ALLOWED / SKIPPED_FILTER.
  Refuses if A already holds a position. No orders.
- `a-enter` (21:00): needs today's ALLOWED row (if the pre-check is missing and it's before 21:05, does it late with a
  WARN; after 21:05 -> MISSED_MACHINE_OFF). qty = equity / bid, rounded to 0.001. Post-only buy loop until 21:05; nothing
  filled -> UNFILLED, no market order. Second run the same day -> refuses.
- `a-exit` (22:55): post-only sell (reduce-only) until 23:00, then market for the rest. Started after 23:00 -> market
  at once + alert. No position but pre-check said ALLOWED and no entry ran -> MISSED_MACHINE_OFF. Writes the final
  `a_windows` row: fill rate, entry/exit avg, slippage vs real and demo mid, fees, funding, P&L in USDT and bp.
- `flatten`: cancel all A orders, market-close A. `a-test`: post-only orders 5% below the market on both venues, checks
  they rest, cancels them (supervised plumbing test; cannot fill).
- Every order event logs the demo book AND the real public book (`fapi.binance.com`, `data-api.binance.vision`).

**Dry-run cycle on Claude's side (offline; books default to 65,000):** setup -> precheck OFF (correct: price < SMA200)
-> `a-enter --force` filled 0.076 @ 65,000 -> `a-exit` sold @ 65,000.10 maker -> P&L -4.0 bp (= 2 x 2 bp fees minus
the 1-tick spread gain: arithmetic checks out) -> status shows A equity 4,998.03, flat. `b-check --force` bought
0.07684 BTC on spot with the 0.1% fee taken in BTC.

**Not yet done:** Windows Task Scheduler setup (8.6), `dashboard.py` (8.1), Telegram alerts (8.7), monthly
live-vs-backtest comparison (8.5).

## 13. What Damian runs next (WSL, one line at a time)

```bash
# 0. after resetting the demo balances: read-only check (expect ALL OK; note the balances it prints)
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/connection_check.py

# 1. all offline tests (each ends with OK)
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/test_harness.py

# 2. dry run with the real public book but a fake exchange (no keys used)
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py status --dry-run

# 3. A's one-time futures setup on the real demo account (ISOLATED, 3x; places no orders)
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py setup

# 4. supervised plumbing test: two post-only orders 5% below the market, then cancelled (expect "a-test: ALL OK")
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py a-test

# 5. real status (no orders): balances, position, demo vs REAL book spread, last runs/alerts
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/harness.py status
```
Then paste the outputs (screenshots are fine). Next session: Task Scheduler entries + dashboard, then start the 90-day run.
