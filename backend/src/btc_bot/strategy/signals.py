"""
Signal engine for the BTC trend + evening-window system.
Implements STRATEGY_RULES.md v1.1 sections 2.1 and 3.1. The bot AND the backtest both use this file,
so the two cannot drift apart.

Definitions (STRATEGY_RULES.md section 1)
  C[D]       daily close of UTC day D = close of D's 23:00 hourly candle = price at 00:00 UTC on D+1
  SMA50[D]   mean of C[D-49..D];  SMA200[D] mean of C[D-199..D]. Fewer closes -> no signal.

Strategy B (decided 00:00 UTC on day D, after datafeed.py has stored D-1's 23:00 candle)
  target = 1 (LONG) if C[D-1] > SMA50[D-1] else 0 (CASH).  Strictly greater.
Strategy A (decided 20:55 UTC on day D)
  allowed = live price P > SMA200[D-1].  Strictly greater. Uses YESTERDAY's SMA200, never today's close.
  Historical proxy for P: close of the 20:00 candle on D (= price at 21:00, the entry price).
  The original backtest used C[D] > SMA200[D], which is known only at 00:00 on D+1, 3 h after the
  window (look-ahead). That version is kept as a_allowed_series_original() for the record only.

Functions
  b_targets(daily_close)            vectorised B targets, whole history (index = day D the target applies to)
  a_allowed_series(hourly)          vectorised corrected A filter, whole history
  a_allowed_series_original(hourly) the old look-ahead filter (do not trade on this)
  b_signal / b_target(daily_close, day)               one day, using only closes before `day`
  a_signal / a_allowed(daily_close, price_now, day)   one day, using only closes before `day`
  current_state(hourly=None, now=None, price_now=None) what the bot should do right now, with checks

Command line (run from the project folder):
  btc-bot signals              # state now; A uses the last stored hourly close as the price
  btc-bot signals --live       # A uses the live Binance price (needs network)
  btc-bot signals --at "2026-11-16 02:40"   # state as it was at a past UTC time
  btc-bot signals --days 10    # also print the last 10 days of signals
Exit code 0 = signals computed, 1 = a check failed: do not trade, alert.
"""
import argparse, math, sys
from pathlib import Path
import pandas as pd

from ..data.feed import load_hourly, daily_closes, latest_price, NetworkError

TREND_MA = 50          # Strategy B moving average (days)
FILTER_MA = 200        # Strategy A trend filter (days)
A_PROXY_HOUR = 20      # backtest stand-in for the 20:55 price: close of the 20:00 candle
DAY, HOUR = pd.Timedelta(days=1), pd.Timedelta(hours=1)


class SignalError(Exception):
    """Data not good enough to decide. The bot must not trade and must alert."""


def _utc(t):
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _day(t):
    return _utc(t).normalize()


def sma(daily_close, n):
    """Simple moving average of the last n daily closes, ending with that day. NaN until n closes exist."""
    return daily_close.rolling(n).mean()


# ---------------------------------------------------------------- vectorised (backtest + tests)
def b_targets(daily_close):
    """B's target for every day D: 1 if C[D-1] > SMA50[D-1] else 0. First day (no yesterday) = 0.
    Equals backtest.py's original `(daily_close > ma50).astype(int).shift(1)` except day one (NaN there)."""
    above = (daily_close > sma(daily_close, TREND_MA)).astype(int)
    return above.shift(1).fillna(0).astype(int)


def a_proxy_price(hourly, index=None):
    """Close of the 20:00 candle per UTC day (the backtest's stand-in for the 20:55 live price)."""
    p = hourly.close[hourly.index.hour == A_PROXY_HOUR].copy()
    p.index = p.index.normalize()
    return p if index is None else p.reindex(index)


def a_allowed_series(hourly, daily_close=None):
    """Corrected A filter for every day D: price at 21:00 on D > SMA200[D-1]. Missing data -> False."""
    dc = daily_closes(hourly) if daily_close is None else daily_close
    return a_proxy_price(hourly, dc.index) > sma(dc, FILTER_MA).shift(1)


def a_allowed_series_original(hourly, daily_close=None):
    """The ORIGINAL backtest filter C[D] > SMA200[D]. Uses the close 3 h after the window: look-ahead.
    Kept only so the old numbers can be reproduced (backtest.py --original-filter)."""
    dc = daily_closes(hourly) if daily_close is None else daily_close
    return dc > sma(dc, FILTER_MA)


# ---------------------------------------------------------------- one day (what the bot calls)
def _closes_before(daily_close, day):
    """Daily closes strictly before `day`; the last one must be yesterday's, or the data is stale."""
    past = daily_close[daily_close.index < day]
    if past.empty or past.index[-1] != day - DAY or pd.isna(past.iloc[-1]):
        last = "none" if past.dropna().empty else past.dropna().index[-1].date()
        raise SignalError(f"no daily close for {(day - DAY).date()} (last available: {last}); run datafeed.py first")
    return past


def b_signal(daily_close, day):
    """B for `day`, using only closes before `day`. Returns dict(day, close, sma50, target)."""
    day = _day(day)
    past = _closes_before(daily_close, day)
    m = sma(past, TREND_MA).iloc[-1]
    c = float(past.iloc[-1])
    target = 0 if pd.isna(m) else int(c > m)
    return {"day": day, "close": c, "sma50": None if pd.isna(m) else float(m), "target": target}


def b_target(daily_close, day):
    """1 (LONG) or 0 (CASH) for `day`. Raises SignalError if yesterday's close is missing."""
    return b_signal(daily_close, day)["target"]


def a_signal(daily_close, price_now, day):
    """A for `day`, using only closes before `day` and the price at 20:55. Returns dict(day, price, sma200, allowed)."""
    day = _day(day)
    if price_now is None or not math.isfinite(float(price_now)) or float(price_now) <= 0:
        raise SignalError(f"invalid price for the 20:55 check: {price_now!r}")
    past = _closes_before(daily_close, day)
    m = sma(past, FILTER_MA).iloc[-1]
    allowed = False if pd.isna(m) else bool(float(price_now) > m)
    return {"day": day, "price": float(price_now), "sma200": None if pd.isna(m) else float(m), "allowed": allowed}


def a_allowed(daily_close, price_now, day):
    """True if A may trade on `day`. Raises SignalError on stale data or a bad price."""
    return a_signal(daily_close, price_now, day)["allowed"]


# ---------------------------------------------------------------- live state
STATE_ROWS = {(1, True): "bull (B long, A trades)", (0, True): "pullback (B cash, A trades)",
              (1, False): "early recovery (B long, A off)", (0, False): "bear (B cash, A off)"}


def current_state(hourly=None, now=None, price_now=None):
    """What the bot should do at time `now` (default: now), using only candles closed by `now`.
    price_now: the live price for A's 20:55 check (from datafeed.latest_price()). If None, the last stored
    hourly close is used and flagged in `warnings` (fine for a status check, not for the real 20:55 decision).
    Returns a dict; `ok` is False if any check failed, in which case the bot must not trade and must alert."""
    now = pd.Timestamp.now(tz="UTC") if now is None else _utc(now)
    h = load_hourly() if hourly is None else hourly
    h = h[h.index + HOUR <= now]                       # candles that had closed by `now`
    today, yday = now.normalize(), now.normalize() - DAY
    s = {"now": now, "day": today, "last_candle": h.index[-1] if len(h) else None,
         "b_target": None, "b_close": None, "sma50": None,
         "a_allowed": None, "a_price": None, "a_price_source": None, "sma200": None,
         "state": None, "warnings": [], "errors": []}
    if h.empty:
        s["errors"].append("no hourly data"); s["ok"] = False; return s
    dc = daily_closes(h)

    if yday + pd.Timedelta(hours=23) not in h.index:   # C[D-1] must be the 23:00 candle, not an earlier hour
        s["errors"].append(f"23:00 candle for {yday.date()} missing (last candle {h.index[-1]}): yesterday's close "
                           "is not final. No trade, alert.")
    missing = 24 - int(h.close[yday:yday + pd.Timedelta(hours=23)].count())
    if 0 < missing < 24:
        s["warnings"].append(f"{yday.date()} has {missing} missing hourly candle(s) (Binance outage?); close still valid")
    try:
        b = b_signal(dc, today)
        s.update(b_target=b["target"], b_close=b["close"], sma50=b["sma50"])
        if b["sma50"] is None: s["warnings"].append(f"fewer than {TREND_MA} daily closes: B has no signal (CASH)")
    except SignalError as e:
        s["errors"].append(f"B: {e}")

    if price_now is None:
        price_now, src = float(h.close.iloc[-1]), f"last stored close ({h.index[-1] + HOUR:%Y-%m-%d %H:%M} UTC)"
        s["warnings"].append("A uses the last stored close, not a live price: for the real 20:55 check use --live")
    else:
        src = "live"
    try:
        a = a_signal(dc, price_now, today)
        s.update(a_allowed=a["allowed"], a_price=a["price"], a_price_source=src, sma200=a["sma200"])
        if a["sma200"] is None: s["warnings"].append(f"fewer than {FILTER_MA} daily closes: A has no signal (off)")
    except SignalError as e:
        s["errors"].append(f"A: {e}")

    if s["b_target"] is not None and s["a_allowed"] is not None:
        s["state"] = STATE_ROWS[(s["b_target"], s["a_allowed"])]
    s["ok"] = not s["errors"]
    return s


def history_table(hourly, start=None):
    """Per-day table of both signals and their inputs (for eyeballing and for logs)."""
    dc = daily_closes(hourly)
    t = pd.DataFrame({"prev_close": dc.shift(1), "sma50_prev": sma(dc, TREND_MA).shift(1), "b_target": b_targets(dc),
                      "price_21h": a_proxy_price(hourly, dc.index), "sma200_prev": sma(dc, FILTER_MA).shift(1),
                      "a_allowed": a_allowed_series(hourly, dc), "a_original": a_allowed_series_original(hourly, dc)})
    return t if start is None else t[start:]


def _fmt(x):
    return "n/a" if x is None else f"{x:,.0f}"


def main():
    ap = argparse.ArgumentParser(description="Compute today's B and A signals (STRATEGY_RULES.md v1.1).")
    ap.add_argument("--live", action="store_true", help="fetch the live BTCUSDT price for A's check")
    ap.add_argument("--at", default=None, help="evaluate as of this UTC time, e.g. '2026-11-16 02:40'")
    ap.add_argument("--days", type=int, default=0, help="also print the last N days of signals")
    a = ap.parse_args()
    price = None
    if a.live:
        try:
            price = latest_price()
        except NetworkError as e:
            print("ERROR:", e); return 1
    h = load_hourly()
    s = current_state(h, now=a.at, price_now=price)
    print(f"Signals at {s['now']:%Y-%m-%d %H:%M} UTC  (last stored candle {s['last_candle']})")
    print(f"B for {s['day'].date()}:  close {(s['day'] - DAY).date()} {_fmt(s['b_close'])} vs SMA50 {_fmt(s['sma50'])}"
          f"  ->  {'n/a' if s['b_target'] is None else ('LONG' if s['b_target'] else 'CASH')}")
    print(f"A for {s['day'].date()}:  price {_fmt(s['a_price'])} [{s['a_price_source']}] vs SMA200 (to "
          f"{(s['day'] - DAY).date()}) {_fmt(s['sma200'])}  ->  "
          f"{'n/a' if s['a_allowed'] is None else ('ON (trade the window)' if s['a_allowed'] else 'OFF')}")
    print(f"Portfolio state: {s['state'] or 'n/a'}")
    for w in s["warnings"]: print("WARNING:", w)
    for e in s["errors"]: print("ERROR:", e)
    if a.days:
        t = history_table(h[h.index + HOUR <= s["now"]]).tail(a.days)
        print(f"\nLast {a.days} days (b_target/a_allowed = decision FOR that day; a_original = old look-ahead filter):")
        print(t.to_string(float_format=lambda x: f"{x:,.0f}"))
    print("OK" if s["ok"] else "NOT OK: do not trade, alert")
    return 0 if s["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
