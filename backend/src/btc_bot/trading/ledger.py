"""
Append-only CSV logs for the paper-trading harness, under data/paper/ (dry runs: data/paper/dryrun/).

One file per kind of record; every row carries a UTC timestamp. Columns are fixed (COLUMNS below) so a typo in a
field name raises instead of silently creating a new column. Files are created with a header on first write.
Never edits or deletes: corrections are new rows. The dashboard and the monthly live-vs-backtest comparison read
these files back with read().

  runs       one row per scheduler run (heartbeat): command, status, duration. Missed runs = gaps here.
  alerts     anything that needs a human: data failed, signal not ok, order rejected, position open after 23:00...
  signals    what signals.py said at each decision (both strategies), with the inputs
  orders     every order event: placed / re-posted / cancelled / filled / market fallback, with demo AND real book
  fills      every fill with fee, and slippage vs the real mid at the decision time
  equity     account value snapshots per strategy (and the combined total)
  a_windows  one row per A day: filter, entry fill rate, entry/exit prices, fees, P&L in USDT and bp, status
  b_days     one row per B day: close vs SMA50, target, holding before/after, any switch, fees
"""
import csv, os, time, traceback
from datetime import datetime, timezone
from pathlib import Path

from ..config import PAPER_DIR

BASE_DIR = PAPER_DIR          # tests point this at a temp folder
_dry = False

COLUMNS = {
    "runs": ["ts_utc", "command", "day", "dry_run", "status", "duration_s", "note"],
    "alerts": ["ts_utc", "level", "command", "message"],
    "signals": ["ts_utc", "day", "strategy", "decision", "price", "price_source", "sma", "close_prev", "state", "ok", "warnings", "errors"],
    "orders": ["ts_utc", "day", "strategy", "venue", "event", "order_id", "client_id", "side", "type", "post_only", "reduce_only",
               "price", "qty", "filled", "avg_price", "status", "demo_bid", "demo_ask", "real_bid", "real_ask", "note"],
    "fills": ["ts_utc", "day", "strategy", "venue", "order_id", "trade_id", "side", "price", "qty", "fee", "fee_asset", "fee_usdt",
              "maker", "realized_pnl", "ref_real_mid", "ref_demo_mid", "slip_real_bp", "slip_demo_bp"],
    "equity": ["ts_utc", "day", "strategy", "equity_usdt", "btc", "usdt", "price", "note"],
    "a_windows": ["day", "status", "allowed", "price_2055", "sma200", "equity_start", "target_qty", "entry_filled", "fill_rate",
                  "entry_avg", "entry_slip_real_bp", "entry_slip_demo_bp", "exit_avg", "exit_type", "exit_slip_real_bp", "exit_slip_demo_bp",
                  "fees_usdt", "funding_usdt", "pnl_usdt", "pnl_bp", "real_mid_2100", "real_mid_2300", "demo_mid_2100", "demo_mid_2300",
                  "n_orders", "note"],
    "b_days": ["day", "status", "close_prev", "sma50", "target", "held_before", "action", "qty", "avg_price", "fee_usdt",
               "slip_real_bp", "slip_demo_bp", "ref_price_0000", "equity_usdt", "btc", "usdt", "delay_min", "note"],
}


def set_dry_run(flag):
    global _dry
    _dry = bool(flag)


def paper_dir():
    return BASE_DIR / "dryrun" if _dry else BASE_DIR


def path(name):
    if name not in COLUMNS: raise KeyError(f"unknown log {name!r}; known: {', '.join(COLUMNS)}")
    return paper_dir() / f"{name}.csv"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fmt(v):
    if v is None: return ""
    if isinstance(v, bool): return str(v)
    if isinstance(v, float): return f"{v:.10g}"
    if isinstance(v, (list, tuple)): return " | ".join(str(x) for x in v)
    return str(v)


def append(name, **row):
    """Append one row. Unknown field names raise. ts_utc / day default to now / today."""
    cols = COLUMNS[name]
    bad = set(row) - set(cols)
    if bad: raise KeyError(f"{name}: unknown field(s) {sorted(bad)}")
    if "ts_utc" in cols: row.setdefault("ts_utc", now_iso())
    if "day" in cols: row.setdefault("day", today())
    if "dry_run" in cols: row.setdefault("dry_run", _dry)
    p = path(name); p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists() or p.stat().st_size == 0
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(cols)
        w.writerow([_fmt(row.get(c)) for c in cols])
    return row


def read(name):
    """All rows of one log as a pandas DataFrame (empty frame with the right columns if the file doesn't exist)."""
    import pandas as pd
    p = path(name)
    if not p.exists(): return pd.DataFrame(columns=COLUMNS[name])
    return pd.read_csv(p, dtype=str, keep_default_na=False)


def rows(name):
    """All rows as a list of dicts (no pandas)."""
    p = path(name)
    if not p.exists(): return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def last(name, **match):
    """Last row matching all given field values, or None."""
    for r in reversed(rows(name)):
        if all(r.get(k) == _fmt(v) for k, v in match.items()): return r
    return None


def alert(command, message, level="ERROR"):
    """Log + print an alert. Levels: ERROR (needs a human), WARN, INFO."""
    print(f"ALERT {level}: {message}")
    return append("alerts", level=level, command=command, message=message)


class Run:
    """Context manager: writes the heartbeat row to runs.csv. Set run.status / run.note inside the block.
    An exception inside becomes status ERROR + an alert, and is re-raised so the command exits non-zero."""
    def __init__(self, command, day=None):
        self.command, self.day, self.status, self.note, self.t0 = command, day, "OK", "", time.time()

    def __enter__(self): return self

    def __exit__(self, et, ev, tb):
        if et is not None:
            self.status = "ERROR"
            self.note = (self.note + " | " if self.note else "") + f"{et.__name__}: {ev}"
            alert(self.command, f"{et.__name__}: {ev}")
            print("".join(traceback.format_exception(et, ev, tb))[-2000:])
        kw = {"command": self.command, "status": self.status, "duration_s": round(time.time() - self.t0, 1), "note": self.note}
        if self.day: kw["day"] = self.day
        append("runs", **kw)
        return False
