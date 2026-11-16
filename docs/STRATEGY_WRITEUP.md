# BTC Trend + Evening-Window Strategy: Research Write-up

**Author:** Damian Craddock (analysis assisted by Claude)
**Date:** 16 November 2026
**Status:** Backtest complete. Not yet paper-traded. No real money.

---

## 1. Summary

This project started as a test of a martingale ("double after every loss") plan for daily futures trades. Simulation and real Bitcoin data showed the martingale adds risk without adding return under every direction rule tested. The research then moved to finding where a real edge exists in Bitcoin's hourly data and how to size it safely.

Two effects survived an out-of-sample test (fit on 2019–2022, tested on 2023–2026, fees included):

1. **A trend filter** (hold BTC above its 50-day moving average, cash below) keeps most of the bull-market return and avoids most of the bear-market loss.
2. **A late-evening window** (long 21:00–23:00 UTC, only when price is above its 200-day average, limit orders only) earns about 14–17% a year with a maximum drawdown around 10%, consistently in both periods.

Combined as one portfolio (B as the main holding, A traded on top at 1× account size):

| Period | Buy & hold | B + A portfolio |
|---|---|---|
| 2020–22 (in-sample) | +37%/yr, max drawdown −77% | +94%/yr, max drawdown −58% |
| 2023–26 (out-of-sample) | +45%/yr, max drawdown −53% | +69%/yr, max drawdown −24% |
| Whole period (Apr 2020 – Jul 2026) | +41%/yr | +79%/yr, Sharpe 1.3 |

The portfolio beat buy-and-hold in every halving-cycle phase. It still lost 50% in calendar 2022. It is a risk-reduction strategy around Bitcoin's trend, not a way to avoid Bitcoin's risk.

---

## 2. Data

| Item | Detail |
|---|---|
| Instrument | Binance spot BTCUSDT |
| Frequency | 1-hour candles (open, high, low, close, volume), UTC |
| Range | 2019-10-01 00:00 to 2026-07-31 23:00 |
| Rows | 59,869 hours, no missing months, 17 small gaps (largest 6 hours) |
| Source | Binance public data (`data.binance.vision`) monthly zips, obtained via two GitHub mirrors: `Aladin000/BuyTheWeekendDip` (2019-10 to 2026-07) and `asadahmad23cse/TradeVex-Server` (2025–2026) |
| File | `data/btc_1h.csv` |
| Build script | `code/build_dataset.py` (merges the monthly CSVs, de-duplicates, checks gaps) |

Daily series are built by resampling to 00:00 UTC closes. Returns are log returns throughout.

**Split:** in-sample 2019-10-01 to 2022-12-31 (28,477 hours); out-of-sample 2023-01-01 to 2026-07-31 (31,391 hours). All strategy choices (window hours, moving-average lengths) were fixed from the in-sample period or from prior published research, then tested unchanged on the out-of-sample period.

**Fees used:** Binance USDT-margined perpetual regular-user rates. Maker 0.02% per side (0.04% round trip); taker 0.05% per side (0.10% round trip). Funding payments and slippage are **not** modelled. The 2-hour window straddles the 00:00/08:00/16:00 UTC funding times only if held past 00:00, which it never is, so funding is zero for A; B holds spot or would pay funding if run on perpetuals.

---

## 3. Part 1: Why the martingale was rejected

### 3.1 Coin-flip theory
- Bet 1 unit, double after each loss, reset after a win. With capital to survive 9 losses (1,023 units), the exact probability of a 10-loss streak is **2.0% in 50 trades, 4.4% in 100, 38.5% in 1,000, 91.4% in 5,000**.
- Expected value is exactly zero at every cap. Splitting into capped accounts changes *when* the losses arrive, not their total. Twenty 50-trade accounts have a 33% chance of at least one blow-up versus 38.5% for one 1,000-trade account.
- Capping at 5 losses: lose 31 units once per ~62 trades, win 1 unit otherwise. Still zero EV. Over 100 trades, ~47% chance of being down before costs, ~49% after a 3% cost.
- A 1:2 reward-to-risk ratio with random entries gives a 1/3 win rate and zero EV; the optional stopping theorem guarantees no sizing scheme changes this.
- Fees scale with the bet, so at small stakes (£10 on a micro future) they take 10–15% of each trade and turn zero EV negative.

### 3.2 Real-data test (daily BTC, one trade per day, 20% of account per unit, cap 5, 0.10% fee)

| Direction rule | Sizing | 2019–22 | Max DD | 2023–26 | Max DD |
|---|---|---|---|---|---|
| Always long | flat | +5% | −28% | +7% | −19% |
| Always long | doubling | +12% | −85% | +167% | −29% |
| Fade yesterday | flat | +38% | −20% | −28% | −29% |
| Fade yesterday | doubling | −62% | −85% | −68% | −72% |
| Follow yesterday | flat | −58% | −59% | −20% | −29% |
| Follow yesterday | doubling | −99% | −99% | −81% | −87% |

Doubling improved only "always long" in 2023–26, a period when BTC rose 280%; the same rule had an 85% drawdown in 2019–22. Doubling after losses means being largest during a run of losses, which in Bitcoin is usually a crash that continues.

### 3.3 Is "a loss predicts a win" true in Bitcoin?
Slightly. Lag-1 autocorrelation of daily returns: −0.085 (2019–22, significant), −0.039 (2023–26, not significant). P(up day | previous down day) = 55.9% then 52.2%. The effect is small, fading, and is a *direction* signal, not a reason to change size. A flat-size "fade yesterday" rule made +72%/yr in 2019–22 and lost 36%/yr in 2023–26: the edge did not persist.

---

## 4. Part 2: Where the edge is

### 4.1 Hour-of-day
Average return per hour was computed for both periods. The hour-by-hour pattern is mostly noise: correlation between the 2019–22 and 2023–26 hourly means is 0.03. The exception is **21:00–23:00 UTC**, positive and statistically meaningful in both periods (t ≈ 2.4 and 2.0 at 21:00; 1.0 and 3.1 at 22:00). This matches Quantpedia's published finding (Gemini data 2015–2022). Gross return ≈ +7.8 bp/day in-sample, +7.1 bp/day out-of-sample.

See `charts/hour_of_day.png`.

**Volume does not predict return.** The busiest hours (12:00–16:00 UTC, US session) had slightly negative average returns; the highest-volume quartile of hours had the lowest mean return. The profitable 21:00–22:00 hours are among the quietest.

**Fees decide everything for the window.** At taker fees (10 bp) the window nets −2 to −3 bp/day and loses 8–10% a year. At maker fees (4 bp) it nets +3 to +4 bp/day.

### 4.2 Filters on the window (maker fee)

| Variant | 2019–22 | 2023–26 |
|---|---|---|
| 21–23 UTC every day | +14.9%/yr, DD −26%, Sharpe 0.73 | +12.1%/yr, DD −10%, Sharpe 0.88 |
| only when > 50d MA | +10.2%/yr, DD −15%, Sharpe 1.18 | +7.2%/yr, DD −9%, Sharpe 0.95 |
| **only when > 200d MA** | **+13.8%/yr, DD −10%, Sharpe 1.61** | **+14.0%/yr, DD −9%, Sharpe 1.58** |
| only on high-volatility days | +19.0%/yr, DD −10%, Sharpe 1.51 | +4.0%/yr, DD −12%, Sharpe 1.48 |

The 200-day filter was chosen: near-identical return, drawdown and Sharpe in both periods.

### 4.3 Trend following (daily, full-day holds)

| Variant | 2019–22 | 2023–26 |
|---|---|---|
| Buy & hold | +24%/yr, DD −77%, Sharpe 0.28 | +45%/yr, DD −53%, Sharpe 0.80 |
| Long > 200d MA, else cash | +34%/yr, DD −64%, Sharpe 0.71 | +35%/yr, DD −32%, Sharpe 0.80 |
| **Long > 50d MA, else cash** | **+61%/yr, DD −58%, Sharpe 1.04** | **+48%/yr, DD −27%, Sharpe 1.17** |
| Long > 200d MA, short below | +39%/yr, DD −82%, Sharpe 0.57 | +27%/yr, DD −47%, Sharpe 0.51 |

The 50-day long/cash version was chosen. Shorting below the average was worse in both periods: Bitcoin's bear-market rallies are violent.

### 4.4 The four-year cycle
Halvings: 11 May 2020 and 20 April 2024. The "long two years after, short two years before" story fits the 2020 cycle (+240% then −48% in year 2) but breaks on the 2024 cycle: the two "bear" years before the April 2024 halving returned +123%, and the "bull" two years after returned +17%. With two cycles in the data, the calendar rule cannot be validated. The 50-day moving average is used instead: it follows the cycle from price, with a lag, rather than predicting it from dates.

---

## 5. Part 3: The combined portfolio

### 5.1 Construction
- **Strategy B (main holding):** 100% of account in BTC when yesterday's 00:00 UTC close > 50-day simple moving average of daily closes; otherwise 100% cash/stablecoin. Taker fee charged on each switch.
- **Strategy A (overlay):** at 21:00 UTC, if the current price > 200-day SMA of daily closes, buy 1× account value of BTC perpetual with a limit order (maker fee); sell at 23:00 UTC with a limit order. Otherwise no trade. Sized as a fixed fraction of current account value.
- Portfolio daily return = B return + A return (A at 1×). A "2×" variant doubles the overlay.

### 5.2 Results

| | 2020-04-17 to 2022-12-31 | 2023-01-01 to 2026-07-31 | Whole period |
|---|---|---|---|
| Buy & hold | +133% total, +36.6%/yr, DD −76.6%, Sharpe 0.45 | +280%, +45.2%/yr, DD −53.0%, Sharpe 0.80 | +786%, +41.4%/yr, Sharpe 0.60 |
| B alone | +294%, +65.9%/yr, DD −57.9%, Sharpe 1.02 | +310%, +48.2%/yr, DD −26.5%, Sharpe 1.17 | +1,514%, +55.6%/yr, Sharpe 1.07 |
| A alone (1×) | +52%, +16.8%/yr, DD −10.3%, Sharpe 1.15 | +60%, +14.0%/yr, DD −8.8%, Sharpe 1.28 | +143%, +15.2%/yr, Sharpe 1.20 |
| **B + A (1×)** | **+500%, +93.8%/yr, DD −57.8%, Sharpe 1.23** | **+555%, +68.9%/yr, DD −23.9%, Sharpe 1.41** | **+3,830%, +79.2%/yr, Sharpe 1.29** |
| B + A (2×) | +815%, +126%/yr, DD −58.6%, Sharpe 1.34 | +946%, +92.5%/yr, DD −22.6%, Sharpe 1.52 | +9,470%, +106%/yr, Sharpe 1.40 |

By halving-cycle phase (total return, worst drawdown inside the phase):

| Phase | Buy & hold | B alone | A alone | B + A |
|---|---|---|---|---|
| 2020 halving, year 1 (bull) | +550% (−25%) | +377% (−25%) | +40% (−10%) | +566% (−27%) |
| 2020 halving, year 2 (bear) | −48% (−57%) | +1% (−37%) | +7% (−7%) | +8% (−37%) |
| 2 yrs before 2024 halving (bottom) | −13% (−50%) | +2% (−33%) | +5% (−9%) | +7% (−33%) |
| 1 yr before 2024 halving (recovery) | +135% (−20%) | +120% (−15%) | +15% (−6%) | +152% (−17%) |
| 2024 halving, year 1 (bull) | +33% (−28%) | +15% (−22%) | +18% (−7%) | +36% (−19%) |
| 2024 halving, year 2 (bear) | −11% (−50%) | +13% (−25%) | +11% (−3%) | +26% (−24%) |
| Since Apr 2026 (3 months) | −15% (−29%) | −3% (−13%) | 0% | −3% (−13%) |

Calendar years, B + A vs buy & hold: 2020 +428% / +302%; 2021 +171% / +60%; **2022 −50% / −64%**; 2023 +165% / +156%; 2024 +126% / +121%; 2025 +19% / −6%; 2026 (7 months) −8% / −28%.

Operating statistics: B switches ≈ 19 times a year (≈ 2% a year in fees). A trades ≈ 216 days a year, 51.9% win rate, +6.5 bp average per trade after fees, worst single window −4.3%. A had zero trades in 2022 and 2026 because price stayed below the 200-day average.

See `charts/equity_curves.png` and `charts/drawdowns.png`.

---

## 6. Limitations and risks

1. **Two halving cycles.** Everything above rests on 6.8 years of data covering two cycles. Consistency across phases is encouraging, not proof.
2. **The 2024 cycle was much weaker than 2020.** Bull-year returns fell from +550% to +33%. Assume the next cycle is weaker again.
3. **Limit-order fills are assumed.** A's edge is 3–4 bp/day after maker fees. If limit orders fail to fill and the trade is taken at taker fees, A loses money. Fill rate is the single most important unknown and is the reason for the paper-trading step.
4. **Slippage and funding are not modelled.** Each is small per trade but A does ~216 trades a year.
5. **The 50-day filter whipsaws.** It still produced −50% in 2022 and a −58% drawdown in-sample. It reduces crashes; it does not prevent them.
6. **A has one explanation and could be arbitraged away.** The 21:00–23:00 UTC effect is published (Quantpedia). If enough capital trades it, it disappears, and the backtest will not warn you. Monitor A's rolling 90-day average per trade; if it goes negative for two consecutive quarters, stop A.
7. **Tail risk inside the window.** No stop-loss is used in the 2-hour window. The worst historical window was −4.3% at 1×. At 2× overlay that is −8.6% in two hours. Exchange outages during the window are a real risk; keep leverage modest.
8. **Regulation.** UK retail clients cannot legally trade crypto derivatives under the FCA ban (in force since January 2021, still in place as of October 2026). Thailand's SEC proposed a framework for retail access to overseas crypto derivatives on 31 August 2026 with no adoption date yet. Strategy B can be run legally anywhere with spot BTC. Strategy A needs futures and must wait for a legal venue. Paper trading needs no venue.

---

## 7. Reproducing the results

```
cd project
python3 code/backtest.py        # prints every table above, writes charts/
```
`code/analysis.py` reproduces the hour-of-day scan, autocorrelation tests, volume analysis and the strategy comparison tables in sections 3–4. `code/build_dataset.py` rebuilds `data/btc_1h.csv` from the raw monthly Binance zips (not included; see section 2 for the source).

Dependencies: Python 3, pandas, numpy, matplotlib.

---

## 8. References

- Baur, Cahill, Godfrey & Liu (2019). *Bitcoin time-of-day, day-of-week and month-of-year effects in returns and trading volume.* Finance Research Letters 31, 78–92.
- Quantpedia. *Are There Seasonal Intraday or Overnight Anomalies in Bitcoin?* and *The Seasonality of Bitcoin* (quantpedia.com).
- Binance Futures fee schedule: binance.com/support/faq/360033544231.
- FCA ban on crypto derivatives for retail (PS20/10, in force 6 January 2021); The Block, 19 October 2026 update on crypto ETNs.
- Thailand SEC consultation on overseas digital-asset derivatives, 31 August 2026.
- Kelly, J. L. (1956). *A New Interpretation of Information Rate.* Bell System Technical Journal.
