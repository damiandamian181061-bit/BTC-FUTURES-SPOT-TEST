"""
Data feed for the BTC trend + evening-window system (step 2 of PROJECT_CONTEXT.md).

What it does
  1. Reads data/btc_1h.csv and finds the last stored hour.
  2. Downloads every *closed* Binance spot BTCUSDT 1h candle since then (REST API, paginated).
  3. Re-downloads the last 24 stored hours and checks they match what is on disk
     (catches a wrong symbol / wrong market / revised data before anything is appended).
  4. Sanity-checks the new candles (order, duplicates, OHLC consistency, gaps, extreme moves).
  5. Appends atomically to data/btc_1h.csv (old file kept as data/btc_1h.csv.bak).
  6. Rebuilds data/btc_1d.csv from the hourly file (00:00 UTC days, same as backtest.py)
     and cross-checks the new daily closes against Binance's own 1d candles.
  7. Appends one line per run to data/update_log.csv.

Usage (from anywhere; paths are relative to the project folder):
  python code/datafeed.py              # update
  python code/datafeed.py --dry-run    # fetch + check, write nothing
  python code/datafeed.py --price      # print the current BTCUSDT price and exit

Exit code 0 = ok (or nothing new), 1 = a check failed and nothing was written,
2 = Binance could not be reached. A scheduler can alert on non-zero.

Other modules (signals.py, the paper-trading harness) should import:
  load_hourly(), daily_closes(), latest_price()
Needs: pandas. Network: data-api.binance.vision or api.binance.com.
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HOURLY_CSV = ROOT / "data" / "btc_1h.csv"
DAILY_CSV = ROOT / "data" / "btc_1d.csv"
LOG_CSV = ROOT / "data" / "update_log.csv"
SYMBOL = "BTCUSDT"
# data-api.binance.vision is Binance's public market-data-only host; api.binance.com is the main one.
# Override with BTC_FEED_BASE_URL (used by the tests to point at a local mock).
BASE_URLS = [os.environ["BTC_FEED_BASE_URL"]] if os.environ.get("BTC_FEED_BASE_URL") else [
    "https://data-api.binance.vision", "https://api.binance.com", "https://api1.binance.com", "https://api2.binance.com"]
HOUR_MS, DAY_MS = 3_600_000, 86_400_000
OVERLAP_HOURS = 24
MAX_GAP_HOURS = 24      # a hole longer than this is a fetch problem, not an exchange outage -> fail
WARN_MOVE, FAIL_MOVE = 0.10, 0.30   # abs hourly return that triggers a warning / a failure


class FeedError(Exception): pass
class NetworkError(Exception): pass


# ---------------------------------------------------------------- network
def _get(path, params, retries=3):
    """GET a Binance public endpoint, trying each base URL; returns parsed JSON."""
    last = None
    for base in BASE_URLS:
        url = f"{base}{path}?{urllib.parse.urlencode(params)}"
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "btc-strategy-datafeed/1.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                last = f"{base}: HTTP {e.code}"
                if e.code in (418, 429):            # rate limited: back off, same host
                    time.sleep(int(e.headers.get("Retry-After", 5 * (attempt + 1)))); continue
                if e.code in (403, 451): break      # region/host blocked: try next host
                time.sleep(2 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = f"{base}: {e}"; time.sleep(2 * (attempt + 1))
    raise NetworkError(f"could not reach Binance ({last})")


def fetch_klines(interval, start_ms, end_ms):
    """All klines with open_time in [start_ms, end_ms). Returns raw Binance rows."""
    step = HOUR_MS if interval == "1h" else DAY_MS
    rows, cur = [], start_ms
    while cur < end_ms:
        batch = _get("/api/v3/klines", {"symbol": SYMBOL, "interval": interval, "startTime": cur,
                                        "endTime": end_ms - 1, "limit": 1000})
        if not batch: break
        rows += batch
        nxt = int(batch[-1][0]) + step
        if nxt <= cur: break
        cur = nxt
        if len(batch) < 1000: break
    return rows


def latest_price():
    """Current BTCUSDT last-trade price (float). For the 20:55 UTC SMA200 pre-check."""
    return float(_get("/api/v3/ticker/price", {"symbol": SYMBOL})["price"])


# ---------------------------------------------------------------- data helpers
def _to_ms(t):
    t = int(t)
    return t // 1000 if t > 1e14 else t      # Binance spot zips switched to microseconds in 2025


def klines_to_frame(rows, now_ms):
    """Binance rows -> DataFrame indexed by UTC open time, closed candles only."""
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                            index=pd.DatetimeIndex([], tz="UTC", name="ts"))
    df = pd.DataFrame([r[:7] for r in rows], columns=["open_time", "open", "high", "low", "close", "volume", "close_time"])
    df["open_time"] = df.open_time.map(_to_ms); df["close_time"] = df.close_time.map(_to_ms)
    df = df[df.close_time < now_ms]                 # drop the candle that is still forming
    df["ts"] = pd.to_datetime(df.open_time, unit="ms", utc=True)
    return df.set_index("ts")[["open", "high", "low", "close", "volume"]].astype(float)


def load_hourly(path=None):
    return pd.read_csv(path or HOURLY_CSV, index_col=0, parse_dates=True)


def daily_closes(hourly=None):
    """Daily close (= last hourly close, i.e. the price at 00:00 UTC the next morning), labelled by the
    UTC day the candle covers, same as Binance 1d candles. Identical to backtest.py's daily_close."""
    h = load_hourly() if hourly is None else hourly
    return h.close.resample("1D").last()


def build_daily(h):
    d = h.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    d["hours"] = h.close.resample("1D").count()
    return d.dropna(subset=["close"])


# ---------------------------------------------------------------- checks
def check_new(old, new):
    """Return (errors, warnings) for the candles about to be appended."""
    err, warn = [], []
    if new.empty: return err, warn
    idx = new.index
    if not idx.is_monotonic_increasing: err.append("new candles not in time order")
    if idx.duplicated().any(): err.append(f"{int(idx.duplicated().sum())} duplicate timestamps in new candles")
    if idx[0] <= old.index[-1]: err.append(f"first new candle {idx[0]} is not after last stored {old.index[-1]}")
    if (idx.minute != 0).any() or (idx.second != 0).any(): err.append("candle open times not on the hour")
    if (new[["open", "high", "low", "close"]] <= 0).any().any(): err.append("non-positive price")
    if (new.volume < 0).any(): err.append("negative volume")
    bad = (new.high < new[["open", "close"]].max(axis=1)) | (new.low > new[["open", "close"]].min(axis=1))
    if bad.any(): err.append(f"{int(bad.sum())} candles with high/low inconsistent with open/close")
    full = pd.concat([old.close.iloc[-1:], new.close])
    gaps = full.index.to_series().diff().dt.total_seconds().div(3600).iloc[1:]
    for ts, g in gaps[gaps > 1].items():
        (err if g > MAX_GAP_HOURS else warn).append(f"gap of {g:.0f} h before {ts}")
    ret = full.pct_change().iloc[1:].abs()
    for ts, m in ret[ret > WARN_MOVE].items():
        (err if m > FAIL_MOVE else warn).append(f"hourly move of {m:.1%} at {ts}")
    return err, warn


def check_overlap(old, fetched):
    """Stored hours must match a fresh download of the same hours."""
    common = old.index.intersection(fetched.index)
    if len(common) == 0: return ["overlap check: Binance returned none of the last stored hours"]
    a, b = old.loc[common], fetched.loc[common]
    px = ((a[["open", "high", "low", "close"]] - b[["open", "high", "low", "close"]]).abs() > 1e-6).any(axis=1)
    vol = ((a.volume - b.volume).abs() > 1e-6 * b.volume.abs().clip(lower=1)).values
    n = int((px.values | vol).sum())
    return [f"overlap check: {n}/{len(common)} stored hours differ from Binance (first: {common[(px.values | vol)][0]})"] if n else []


def write_atomic(df, path):
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp); os.replace(tmp, path)


def log_run(row):
    new = not LOG_CSV.exists()
    with open(LOG_CSV, "a", encoding="utf-8") as f:
        if new: f.write("run_utc,status,rows_added,first_new,last_new,warnings,errors\n")
        f.write(",".join(str(row.get(k, "")).replace(",", ";") for k in
                         ("run_utc", "status", "rows_added", "first_new", "last_new", "warnings", "errors")) + "\n")


# ---------------------------------------------------------------- main
def update(dry_run=False, now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    run_utc = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    old = load_hourly()
    last_ms = int(old.index[-1].timestamp() * 1000)
    print(f"stored: {len(old):,} hours, {old.index[0]} -> {old.index[-1]}")

    fetched = klines_to_frame(fetch_klines("1h", last_ms - (OVERLAP_HOURS - 1) * HOUR_MS, now_ms), now_ms)
    errors = check_overlap(old, fetched)
    new = fetched[fetched.index > old.index[-1]]
    e2, warnings = check_new(old, new); errors += e2

    # cross-check complete new days against Binance's own daily candles
    if not new.empty and not errors:
        h_all = pd.concat([old, new]); dly = build_daily(h_all)
        first_day = new.index[0].normalize()
        mine = dly[(dly.index >= first_day) & (dly.hours == 24)]
        if len(mine):
            off = klines_to_frame(fetch_klines("1d", int(mine.index[0].timestamp() * 1000), now_ms), now_ms)
            both = mine.index.intersection(off.index)
            diff = (mine.loc[both, "close"] - off.loc[both, "close"]).abs() > 1e-6
            if diff.any(): warnings.append(f"{int(diff.sum())} daily closes differ from Binance 1d candles (first {both[diff.values][0].date()})")
            print(f"daily cross-check: {len(both)} complete new days, {int(diff.sum())} mismatches vs Binance 1d")

    for w in warnings: print("WARNING:", w)
    for e in errors: print("ERROR:", e)
    row = dict(run_utc=run_utc, rows_added=0 if errors else len(new), warnings=" | ".join(warnings), errors=" | ".join(errors),
               first_new="" if new.empty else new.index[0], last_new="" if new.empty else new.index[-1])
    if errors:
        print("nothing written."); row["status"] = "FAILED"
        if not dry_run: log_run(row)
        return 1
    if new.empty:
        print("up to date - no new closed candles."); row["status"] = "NO_NEW"
        if not dry_run: log_run(row)
        return 0
    print(f"new: {len(new):,} hours, {new.index[0]} -> {new.index[-1]}")
    if dry_run:
        print("dry run - nothing written."); return 0
    h_all = pd.concat([old, new])
    if HOURLY_CSV.exists():
        bak = HOURLY_CSV.with_suffix(".csv.bak")
        if bak.exists(): bak.unlink()
        os.replace(HOURLY_CSV, bak)
    write_atomic(h_all, HOURLY_CSV)
    write_atomic(build_daily(h_all), DAILY_CSV)
    row["status"] = "OK"; log_run(row)
    print(f"written: {HOURLY_CSV.name} now {len(h_all):,} hours to {h_all.index[-1]}; {DAILY_CSV.name} rebuilt.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Update data/btc_1h.csv from Binance.")
    ap.add_argument("--dry-run", action="store_true", help="fetch and check, write nothing")
    ap.add_argument("--price", action="store_true", help="print current BTCUSDT price and exit")
    a = ap.parse_args()
    try:
        if a.price:
            print(f"{SYMBOL} {latest_price():,.2f}"); sys.exit(0)
        sys.exit(update(dry_run=a.dry_run))
    except NetworkError as e:
        print("ERROR:", e)
        if not a.dry_run: log_run(dict(run_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                                         status="NO_NETWORK", errors=str(e)))
        sys.exit(2)
