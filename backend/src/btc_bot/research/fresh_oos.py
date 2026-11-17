"""
Fresh out-of-sample check: runs the exact backtest.py strategy maths on data the research never saw
(from 2026-08-01, the day after the research dataset ended). No parameters are changed or fitted.

Usage (after `btc-bot feed`):
  btc-bot holdout                    # holdout = 2026-08-01 .. last complete day
  btc-bot holdout --start 2026-04-20 # any other window (used to test against backtest.py)

Prints: strategy returns on the holdout, Strategy A trade stats vs the backtest, Strategy B switch
count, a monthly table, where the holdout sits in the distribution of same-length windows from the
2023-26 out-of-sample period, and the current B / A signal state. Draws charts/holdout_equity.png.
Step 3 (16 Nov 2026): signals now come from signals.py, with the corrected (live-feasible) A filter.
  --original-filter reproduces the old look-ahead numbers (STRATEGY_RULES.md section 5).
"""
import argparse, sys
from pathlib import Path
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt

from ..config import CHARTS_DIR, DATA_DIR
from ..strategy import signals as S
# ---- identical to backtest.py; do not tune these on the holdout
MAKER, TAKER = 0.0004, 0.0010
WINDOW_HOURS, TREND_MA, FILTER_MA = [21, 22], 50, 200
OOS_START, RESEARCH_END = "2023-01-01", "2026-07-31"
BT_B_SWITCHES_YR = 19                               # backtest reference values (STRATEGY_RULES.md v1.1)
BT = {False: dict(a_bp=5.7, cagr="+75.9%/yr", dd="-58%", sh="1.25"),   # corrected A filter
      True: dict(a_bp=6.5, cagr="+79.2%/yr", dd="-58%", sh="1.29")}    # original (look-ahead) filter


def build(df, original=False):
    """Same series as backtest.py: daily log returns of buy & hold, B, A and B+A."""
    hourly = np.log(df.close).diff().dropna()
    daily_close = df.close.resample("1D").last()
    daily = np.log(daily_close).diff()
    ma50, ma200 = daily_close.rolling(TREND_MA).mean(), daily_close.rolling(FILTER_MA).mean()
    w = hourly[hourly.index.hour.isin(WINDOW_HOURS)]
    cnt = w.groupby(w.index.date).count(); wd = w.groupby(w.index.date).sum()
    wd = wd[cnt == len(WINDOW_HOURS)]; wd.index = pd.to_datetime(wd.index, utc=True); wd = wd.reindex(daily.index)
    a_filter = S.a_allowed_series_original(df, daily_close) if original else S.a_allowed_series(df, daily_close)
    A = (wd - MAKER).where(a_filter).fillna(0)
    pos = S.b_targets(daily_close)
    B = daily * pos - pos.diff().abs().fillna(0) * TAKER
    a_on = a_filter & wd.notna()
    return dict(daily_close=daily_close, ma50=ma50, ma200=ma200, pos=pos, a_on=a_on,
                strats={"Buy & hold": daily, "B alone": B, "A alone (1x)": A, "B + A (1x)": B + A})


def stats(p):
    p = p.dropna(); cum = np.exp(p.sum()) - 1
    eq = np.exp(p.cumsum()); dd = min((eq / eq.cummax() - 1).min(), 0)
    sh = p.mean() / p.std() * np.sqrt(365) if p.std() > 0 else float("nan")
    return cum, (1 + cum) ** (365 / len(p)) - 1, dd, sh


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--start", default="2026-08-01"); ap.add_argument("--end", default=None)
    ap.add_argument("--original-filter", action="store_true", help="old A filter with look-ahead (for the record)")
    a = ap.parse_args(); bt = BT[a.original_filter]
    df = df_all = pd.read_csv(DATA_DIR / "btc_1h.csv", index_col=0, parse_dates=True)
    # use complete UTC days only (the feed can stop mid-day)
    hrs = df.close.resample("1D").count(); last_full = hrs[hrs == 24].index[-1]
    df = df[: last_full + pd.Timedelta(hours=23)]
    r = build(df, a.original_filter); ST = r["strats"]
    end = a.end or str(last_full.date())
    if pd.Timestamp(a.start, tz="UTC") > last_full:
        print(f"No complete days after {a.start} yet (data ends {df.index[-1]}). Run code/datafeed.py first."); return
    n_days = len(ST["Buy & hold"][a.start:end])

    print(f"Data: {df.index[0].date()} .. {df.index[-1]}  ({len(df):,} hours) | A filter: "
          + ("ORIGINAL (look-ahead)" if a.original_filter else "corrected (21:00 price > SMA200 to yesterday)"))
    c = stats(ST["B + A (1x)"][str(r['ma200'].first_valid_index().date()):RESEARCH_END])
    print(f"Engine check, B+A 1x to {RESEARCH_END}: {c[1]:+.1%}/yr, maxDD {c[2]:.0%}, Sharpe {c[3]:.2f} "
          f"(backtest.py: {bt['cagr']}, {bt['dd']}, {bt['sh']})\n")
    print(f"=== Holdout {a.start} .. {end}  ({n_days} days; strategy parameters unchanged) ===")
    print(f"{'':16s} {'total':>8s} {'maxDD':>7s} {'annualised*':>12s} {'Sharpe*':>8s}")
    for n, s in ST.items():
        cum, cagr, dd, sh = stats(s[a.start:end])
        print(f"{n:16s} {cum:+8.1%} {dd:7.1%} {cagr:+12.0%} {sh:+8.2f}")
    print("* annualised figures from a few months of data are very noisy; read total and drawdown first.\n")

    A = ST["A alone (1x)"][a.start:end]; on = r["a_on"][a.start:end]; trades = A[on]
    print("=== Strategy A (21:00-23:00 UTC, SMA200 filter) ===")
    print(f"days allowed by SMA200 filter: {int(on.sum())}/{n_days}")
    if len(trades):
        t = trades.mean() / trades.std() * np.sqrt(len(trades)) if len(trades) > 1 else float("nan")
        print(f"trades {len(trades)} | win rate {(trades > 0).mean():.1%} | avg {trades.mean()*1e4:+.1f} bp/trade after maker fee "
              f"(backtest {bt['a_bp']:+.1f}) | t-stat {t:+.2f} | best {trades.max():+.2%} | worst {trades.min():+.2%}")
    else:
        print("no trades: price was below SMA200 the whole period (expected behaviour in a bear).")
    pos = r["pos"][a.start:end]; sw = int(pos.diff().abs().fillna(0).sum())
    print("\n=== Strategy B (50-day trend) ===")
    print(f"days long {int(pos.sum())}/{n_days} | switches {sw} (~{sw / n_days * 365:.0f}/yr annualised; backtest ~{BT_B_SWITCHES_YR}/yr)")

    print("\n=== Monthly (total return) ===")
    m = pd.DataFrame({n: ST[n][a.start:end].groupby(ST[n][a.start:end].index.strftime("%Y-%m")).sum().pipe(np.exp) - 1
                      for n in ("Buy & hold", "B alone", "A alone (1x)", "B + A (1x)")})
    print(m.apply(lambda col: col.map(lambda x: f"{x:+.1%}")).to_string())

    # where does the holdout sit among same-length windows of the 2023-26 OOS period?
    print(f"\n=== Holdout vs every {n_days}-day window in the {OOS_START}..{RESEARCH_END} out-of-sample period ===")
    for n in ("B + A (1x)", "A alone (1x)", "Buy & hold"):
        roll = (np.exp(ST[n][OOS_START:RESEARCH_END].rolling(n_days).sum()) - 1).dropna()
        h = np.exp(ST[n][a.start:end].sum()) - 1
        print(f"{n:14s} holdout {h:+7.1%} | past windows: 10th pct {roll.quantile(.1):+7.1%}, median {roll.median():+7.1%}, "
              f"90th pct {roll.quantile(.9):+7.1%} | holdout percentile {(roll < h).mean():.0%}")

    st = S.current_state(df_all, now=last_full + pd.Timedelta(days=1, minutes=1))
    print(f"\n=== Signal state at {st['day'].date()} 00:01 UTC (signals.py) ===")
    print(f"B: close {st['b_close']:,.0f} vs SMA50 {st['sma50']:,.0f} -> {'LONG' if st['b_target'] else 'CASH'} | "
          f"A: last stored close {st['a_price']:,.0f} vs SMA200 {st['sma200']:,.0f} -> {'ON' if st['a_allowed'] else 'OFF'} "
          "(the live 20:55 check uses the current price: btc-bot signals --live)")

    fig, ax = plt.subplots(figsize=(10, 4.8))
    for n, s in ST.items():
        eq = np.exp(s[a.start:end].fillna(0).cumsum()); ax.plot(eq.index, eq, label=n, lw=1.5)
    ax.axhline(1, color="grey", lw=.8); ax.set_ylabel("growth of 1"); ax.grid(alpha=.3); ax.legend()
    label = "Fresh out-of-sample holdout" if a.start == "2026-08-01" else "Strategy check"
    ax.set_title(f"{label} {a.start} to {end} (parameters unchanged, fees in)")
    fig.tight_layout(); CHARTS_DIR.mkdir(parents=True, exist_ok=True); out = CHARTS_DIR / ("holdout_equity.png" if a.start == "2026-08-01" else f"check_{a.start}_{end}.png"); fig.savefig(out, dpi=130); print(f"\nchart: {out}")


if __name__ == "__main__":
    main()
