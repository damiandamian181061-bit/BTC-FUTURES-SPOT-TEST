"""
BTC strategy backtest: Strategy B (50-day trend) + Strategy A (21:00-23:00 UTC window, 200-day filter).
Reproduces every table in docs/STRATEGY_WRITEUP.md and draws charts/.
Usage (run from the project root):
  python3 code/backtest.py                    # research numbers, corrected A filter (STRATEGY_RULES.md v1.1)
  python3 code/backtest.py --original-filter  # the original v1.0 numbers (A filter with look-ahead), for the record
  python3 code/backtest.py --end 2026-11-15   # include data after the research period (NOT for tuning)
Data: data/btc_1h.csv - Binance spot BTCUSDT 1-hour candles, UTC. Research period 2019-10-01 .. 2026-07-31.
Signals come from code/signals.py (the same code the bot uses).
Step 3 change (16 Nov 2026): A's filter is now the live-feasible one (21:00 price > SMA200 of closes up to
yesterday) instead of the day's own 00:00 close > SMA200 (look-ahead); data is cut at --end (default 2026-07-31).
Charts are only redrawn for the corrected run.
"""
import argparse, os, sys
import pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import signals as S

MAKER = 0.0004   # Binance USDT-M regular-user maker fee, in+out  (0.02% x 2)
TAKER = 0.0010   # taker fee, in+out (0.05% x 2)
WINDOW_HOURS = [21, 22]   # hold from 21:00 to 23:00 UTC
TREND_MA = 50             # Strategy B moving average (days)
FILTER_MA = 200           # Strategy A trend filter (days)
IS_END, OOS_START, RESEARCH_END = "2022-12-31", "2023-01-01", "2026-07-31"

ap = argparse.ArgumentParser(description="B + A backtest")
ap.add_argument("--original-filter", action="store_true", help="use the original look-ahead A filter (v1.0 numbers)")
ap.add_argument("--end", default=RESEARCH_END, help=f"last day of data to use (default {RESEARCH_END})")
args = ap.parse_args()
df = pd.read_csv("data/btc_1h.csv", index_col=0, parse_dates=True)
df = df[df.index < pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1)]
print(f"Data {df.index[0]} .. {df.index[-1]} | A filter: " + ("ORIGINAL (look-ahead, v1.0, for the record only)"
      if args.original_filter else "corrected: 21:00 price > SMA200 to yesterday (v1.1)") + "\n")
hourly = np.log(df.close).diff().dropna()
daily_close = df.close.resample("1D").last()
daily = np.log(daily_close).diff()
ma50, ma200 = daily_close.rolling(TREND_MA).mean(), daily_close.rolling(FILTER_MA).mean()

# ---- Strategy A: long 21:00-23:00 UTC with limit orders, only when close > 200d MA
w = hourly[hourly.index.hour.isin(WINDOW_HOURS)]
cnt = w.groupby(w.index.date).count(); wd = w.groupby(w.index.date).sum()
wd = wd[cnt == len(WINDOW_HOURS)]; wd.index = pd.to_datetime(wd.index, utc=True); wd = wd.reindex(daily.index)
a_on = S.a_allowed_series_original(df, daily_close) if args.original_filter else S.a_allowed_series(df, daily_close)
A = (wd - MAKER).where(a_on).fillna(0)

# ---- Strategy B: 100% long when yesterday's close > 50d MA, else cash; taker fee on each switch
pos = S.b_targets(daily_close)   # = (daily_close > ma50).astype(int).shift(1), first day 0
B = daily * pos - pos.diff().abs().fillna(0) * TAKER

start = str(ma200.first_valid_index().date())
strats = {"Buy & hold": daily, "B alone": B, "A alone (1x)": A, "B + A (A at 1x)": B + A, "B + A (A at 2x)": B + 2 * A}

def stats(p):
    p = p.dropna(); yrs = len(p) / 365; cum = np.exp(p.sum()) - 1
    eq = np.exp(p.cumsum()); dd = (eq / eq.cummax() - 1).min()
    sh = p.mean() / p.std() * np.sqrt(365) if p.std() > 0 else float("nan")
    return cum, (1 + cum) ** (1 / yrs) - 1, dd, sh

print(f"=== Overall from {start} ===")
for n, s in strats.items():
    for lbl, seg in (("IS", s[start:IS_END]), ("OOS", s[OOS_START:]), ("ALL", s[start:])):
        cum, cagr, dd, sh = stats(seg)
        print(f"{n:18s} {lbl:3s} | total {cum:+8.0%} | {cagr:+6.1%}/yr | maxDD {dd:6.1%} | Sharpe {sh:+.2f}")
    print()

phases = [("2020-05-11","2021-05-11","2020 halving yr1 (bull)"), ("2021-05-11","2022-05-11","2020 halving yr2 (bear)"),
          ("2022-05-11","2023-05-11","2024 halving -2y (bottom)"), ("2023-05-11","2024-04-20","2024 halving -1y (recovery)"),
          ("2024-04-20","2025-04-20","2024 halving yr1 (bull)"), ("2025-04-20","2026-04-20","2024 halving yr2 (bear)"),
          ("2026-04-20","2026-07-31","since Apr 2026 (3m)")]
rows = []
for a, b, l in phases:
    row = {"phase": l}
    for n in ("Buy & hold", "B alone", "A alone (1x)", "B + A (A at 1x)"):
        cum, cagr, dd, sh = stats(strats[n][a:b]); row[n] = f"{cum:+.0%} ({dd:.0%})"
    rows.append(row)
print("=== By halving-cycle phase: total return (worst drawdown) ===")
print(pd.DataFrame(rows).set_index("phase").to_string())

print("\n=== Calendar years ===")
for y in range(2020, 2027):
    s = strats["B + A (A at 1x)"][f"{y}"]; h = daily[f"{y}"]
    print(f"{y}: B+A {np.exp(s.sum())-1:+6.0%} | buy&hold {np.exp(h.sum())-1:+6.0%} | days long in B {int(pos[f'{y}'].sum())}/{len(h)} | A trades {int((A[f'{y}']!=0).sum())}")
print("\nB switches/yr:", round(pos.diff().abs().sum() / (len(pos) / 365), 1),
      "| A trades/yr:", round((A != 0).sum() / (len(A[start:]) / 365)),
      "| A win rate:", f"{(A[A!=0]>0).mean():.1%}", "| A avg/trade:", f"{A[A!=0].mean()*1e4:+.1f} bp",
      "| A worst single window:", f"{A[A!=0].min():.1%}")

if args.original_filter or args.end != RESEARCH_END:
    print("\n(charts not redrawn: they show the corrected research run only)"); sys.exit(0)

# ---- Charts
fig, ax = plt.subplots(figsize=(11, 5.5))
for n, s in strats.items():
    if n == "B + A (A at 2x)": continue
    eq = np.exp(s[start:].fillna(0).cumsum()); ax.plot(eq.index, eq, label=n, lw=1.4)
ax.set_yscale("log"); ax.set_ylabel("Growth of 1 (log scale)"); ax.set_title("BTC: buy & hold vs Strategy B, A and B+A (fees included)")
ax.axvline(pd.Timestamp(OOS_START, tz="UTC"), color="grey", ls="--", lw=1); ax.text(pd.Timestamp(OOS_START, tz="UTC"), ax.get_ylim()[1]*0.7, " out-of-sample →", color="grey")
ax.legend(); ax.grid(alpha=.3); fig.tight_layout(); fig.savefig("charts/equity_curves.png", dpi=130)

fig, ax = plt.subplots(figsize=(11, 4))
for n in ("Buy & hold", "B + A (A at 1x)"):
    eq = np.exp(strats[n][start:].fillna(0).cumsum()); ax.plot(eq.index, eq / eq.cummax() - 1, label=n, lw=1.2)
ax.set_title("Drawdown from peak"); ax.set_ylabel("drawdown"); ax.legend(); ax.grid(alpha=.3); fig.tight_layout(); fig.savefig("charts/drawdowns.png", dpi=130)

fig, ax = plt.subplots(figsize=(11, 4))
hr_is = hourly[start:IS_END]; hr_oos = hourly[OOS_START:]
ax.bar(np.arange(24) - .2, hr_is.groupby(hr_is.index.hour).mean() * 1e4, .4, label="2020-22"); ax.bar(np.arange(24) + .2, hr_oos.groupby(hr_oos.index.hour).mean() * 1e4, .4, label="2023-26")
ax.set_xticks(range(24)); ax.set_xlabel("hour (UTC)"); ax.set_ylabel("avg return, bp"); ax.set_title("Average BTC return by hour of day"); ax.legend(); ax.grid(alpha=.3, axis="y"); fig.tight_layout(); fig.savefig("charts/hour_of_day.png", dpi=130)
print("\ncharts written to charts/")
