# Handover: Step 3 (signal engine) session, 16 Nov 2026

**Read order for a new chat:** `PROJECT_CONTEXT.md` -> this file -> `STRATEGY_RULES.md` (the rulebook) ->
`HANDOVER_STEP2.md` only for data-feed details or the look-ahead discovery.

**Where we left off:** step 3 is built and tested, and confirmed on Damian's laptop (WSL, 16 Nov 02:55 UTC): 19/19 tests
pass, `signals.py --live` fetched the live price (65,073) -> B CASH, A OFF. Step 4 (paper-trading harness) is next.

---

## 1. Summary

1. Built `code/signals.py`: the one place that turns data into B's target and A's go/no-go. The bot and the
   backtest both use it, so they can't drift apart.
2. Built `code/test_signals.py`: 19 tests, all passing (pandas 2.3 on Claude's side).
3. Fixed the look-ahead in the backtest: `backtest.py` and `fresh_oos.py` now take their signals from `signals.py`
   (corrected A filter by default; `--original-filter` reproduces the old numbers). `backtest.py` now stops at
   2026-07-31 by default, so the research numbers no longer drift as the data grows.
4. Re-run results match HANDOVER_STEP2 section 7 exactly: B+A +75.9%/yr whole period (Sharpe 1.25, DD -58.0%),
   A out of sample +11.2%/yr, +5.7 bp/trade, 1,359 trades. Holdout: A -7.0% (84 trades, -8.6 bp), B+A +15.8%.
5. No strategy rule or parameter changed. STRATEGY_RULES.md stays at v1.1.

## 2. `signals.py` reference

| Function | What it returns |
|---|---|
| `b_targets(daily_close)` | Series of 0/1, one per day D: target for D (decided 00:00 on D) = `C[D-1] > SMA50[D-1]`. Day one = 0 |
| `a_allowed_series(hourly)` | Series of bool per day D: close of the 20:00 candle on D > `SMA200[D-1]`. Missing data = False |
| `a_allowed_series_original(hourly)` | the old look-ahead filter `C[D] > SMA200[D]`, for the record only |
| `b_signal(dc, day)` / `b_target(dc, day)` | one day, using only closes before `day`; dict has close, sma50, target |
| `a_signal(dc, price, day)` / `a_allowed(dc, price, day)` | one day, live price vs SMA200 to yesterday |
| `current_state(hourly=None, now=None, price_now=None)` | everything the bot needs at `now`, plus `ok`, `warnings`, `errors` |
| `history_table(hourly)` | per-day table of both signals and inputs (for logs and eyeballing) |

Rules built in:
- Strictly greater than. Equal = CASH / OFF.
- Fewer than 50 / 200 closes = no signal (CASH / OFF).
- `SignalError` (bot must not trade, must alert) if yesterday's daily close isn't there (stale data / feed not run),
  or the 20:55 price is missing, zero, negative or NaN.
- `current_state()` uses only candles that had closed by `now`, so it can be replayed at any past time.
  `ok = False` if yesterday's **23:00 candle** is missing (close not final; rule 6.1.6). Other missing hours of
  yesterday give a warning only (matches the backtest, which takes the last available hour).
- No historical day is missing its 20:00, 21:00, 22:00 or 23:00 candle, so these edge rules only matter live.

CLI: `python3 code/signals.py` (state now; A uses last stored close and says so), `--live` (live Binance price for A),
`--at "2026-11-16 02:40"` (replay), `--days 10` (recent table). Exit 0 = ok, 1 = do not trade.

## 3. Tests (`code/test_signals.py`)

1. B equals backtest.py's original `pos` on every day (exact), and an independent plain-Python loop.
2. A equals the corrected filter computed by an independent loop on every day. The corrected and original filters
   differ on exactly the 11 known days (10 in the research period, plus 19 Aug 2026).
3. Hand-checked days, cross-checked against `data/btc_1d.csv` (separate code path):
   B 1 Aug 2026 CASH (62,888 < 63,440), 3 Aug LONG (63,570 > 63,407), 23 Oct CASH (81,416 < 81,824), 16 Nov CASH.
   A 19 Aug 2026 OFF (21:00 price 69,048 < SMA200 69,082). The **original** filter said ON because the 00:00 close on
   20 Aug (69,335, after the window) was above the average: a textbook look-ahead example. 20 Aug ON, 12 Nov OFF.
4. `current_state()` at 16 Nov 02:40 UTC: B CASH (65,351 vs 79,844), A OFF (SMA200 72,978), "bear" row.
5. No look-ahead: (a) on 499 days (every signal change + every 7th day), signals from data cut at D-1 23:59 (B) /
   D 20:59 (A) equal the full-data signals; (b) multiplying every candle after a cutoff by random factors changes no
   signal up to the cutoff; (c) the **original** filter fails (b), proving the test can catch look-ahead.
6. Edge cases: too few closes, exact equality, stale data, bad price, missing 23:00 candle, feed not yet run at 00:01,
   missing intraday hour (warning only), `now` ignores later candles.

## 4. Commands for Damian (WSL, one line each)

```bash
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/test_signals.py
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/signals.py --live --days 5
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/backtest.py | head -20
cd "/mnt/c/Users/damia/Documents/BTC Strategy Project" && python3 code/datafeed.py && python3 code/signals.py --live
```
The last one is the daily routine: update data, then signals. The WSL pandas (apt) is older than Claude's; if
anything fails there, paste the error.

## 5. Findings worth keeping

- **Residual 5 minutes.** The backtest proxy for the 20:55 price is the 20:00 candle close (= 21:00). Using the 19:00
  close (an hour before the decision) instead: A whole period +13.1%/yr (vs +13.0%), OOS +10.5%/yr (vs +11.2%).
  Not material, but A's OOS margin over the +10%/yr bar is thin either way.
- `backtest.py` and `fresh_oos.py` both use `signals.py` now. Charts redrawn with the corrected filter
  (`charts/equity_curves.png`, `drawdowns.png`, `hour_of_day.png`, `holdout_equity.png`).
- `STRATEGY_WRITEUP.md` (both copies) still shows the original (look-ahead) figures. Not updated this session.

## 6. Step 4 spec notes (paper harness)

- Call `current_state(price_now=latest_price())` at 20:55 and `current_state()` after `datafeed.py` at 00:01.
  Trade only if `ok` and `datafeed.py` exited 0. Log the whole dict.
- Open questions still open (from HANDOVER_STEP2 section 10): Deribit vs Binance Futures testnet; VPS vs laptop
  (WSL cron or Windows Task Scheduler calling `wsl`); B spot vs perpetual and the sizing conflict (RULES 4.3);
  whether to start the harness with B only.

## 7. Step 4 progress (16 Nov 2026, ~03:25 UTC)

- **Venue:** Binance Demo Trading (replaced the old futures testnet). Spot demo `https://demo-api.binance.com`,
  futures demo `https://demo-fapi.binance.com`. Two keys: `btc-B-spot` (B) and `btc-A-futures` (A), withdrawals off.
- **Keys:** stored in Bitwarden + `~/.config/btc-bot/secrets.env` inside WSL (chmod 600), OUTSIDE the project folder so
  Claude never reads them. Never paste keys into chat.
- **Built:** `code/exchange.py` (stdlib client, HMAC signing verified against Binance's doc example, clock-offset sync,
  secrets loader), `code/connection_check.py` (read-only), `code/test_exchange.py` (5 offline tests pass).
- **First live check: ALL OK.** Spot demo 5,000 USDT + 0.05 BTC; futures demo 5,000 USDT; one-way mode; laptop clock
  ~0.6 s behind Binance (corrected automatically).
  Fees: spot 0.10% maker and taker (B's backtest charges 0.10% per switch: consistent); futures maker 0.02% (as assumed),
  taker 0.04% (backtest assumes 0.05%: slightly conservative; do not retune).
- **Caveat found:** demo BTCUSDT perp spread was 3.2 bp (bid 65,106.40 / ask 65,127.30); the real market is ~0.01 bp.
  Binance says demo market data is "realistic", not real. So demo fill rates and slippage may not reflect live.
  **Design decision for the harness:** log the REAL Binance book (public fapi/data-api endpoints) alongside every demo
  order, and measure slippage against the real mid, so the go/no-go (fill >= 80%, slippage <= 2 bp) isn't judged on
  demo microstructure alone.
- Machine: laptop + WSL for now (Damian's choice); Task Scheduler entries to wake WSL; log "machine off" separately
  from "order unfilled". Dashboard: B and A in separate sections plus a combined total.
