"""
Paper-trading dashboard (step 4/5). Reads the append-only logs under data/paper/ and writes a self-contained
data/paper/dashboard.html plus a text summary on the terminal. Read-only: no orders, no API keys, no network.

  btc-bot dashboard             # real logs -> data/paper/dashboard.html
  btc-bot dashboard --dry-run   # dry-run logs -> data/paper/dryrun/dashboard.html
  btc-bot dashboard --no-html   # terminal summary only (no html, no json)
  btc-bot dashboard --days 30   # days shown in the operations grid (default 14)
Scheduled daily at 23:10 UTC (scheduler/install_tasks.ps1 -> scripts/run.sh dashboard), after A's exit.
Also writes data/paper/dashboard.json (same numbers, one JSON document): the Vite front end in frontend/ renders it.

Sections (B and A are kept separate, plus a combined total):
  1. signal state now            4. combined B + A
  2. B: 50-day trend             5. kill switches / review triggers (STRATEGY_RULES.md 6.2)
  3. A: 21:00-23:00 UTC window   6. operations: runs grid (missed runs), alerts, data feed, log notes

"Expected" = the backtest maths (fresh_oos.build, the same code as backtest.py, signals from signals.py) run on the
actual candles of the same days. Paper minus expected therefore measures EXECUTION (fills, slippage, fees), not
whether the strategy works; the strategy itself is judged by the holdout report (fresh_oos.py).
Demo-book and real-book slippage are shown side by side: the go/no-go reads the REAL-book columns (STRATEGY_RULES.md 6.2).
"""
import argparse, csv, html, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np, pandas as pd
sys.dont_write_bytecode = True
from ..config import DATA_DIR
from ..data.feed import load_hourly, daily_closes
from ..research.fresh_oos import build, BT, BT_B_SWITCHES_YR
from ..strategy import signals as S
from ..trading import ledger as L

DAY = pd.Timedelta(days=1)
RUN_TIMES = {"b-check": (0, 1), "a-precheck": (20, 55), "a-enter": (21, 0), "a-exit": (22, 55), "dashboard": (23, 10)}
GRACE_MIN = 20                      # a scheduled run counts as missing this many minutes after its time
HOLDOUT_START = "2026-08-01"        # first day the research never saw (fresh_oos.py)
# thresholds, STRATEGY_RULES.md 6.2
BT_A_BP = BT[False]["a_bp"]         # backtest +5.7 bp/trade (corrected filter, whole period)
FILL_MIN, SLIP_MAX, BP_TOL, B_SWITCH_MAX, B_DD_MAX = 0.80, 2.0, 3.0, 40, -0.58
A_ATTEMPTED = ("ENTERED", "UNFILLED", "CLOSED", "STILL_OPEN")
A_FINAL = ("ENTERED", "UNFILLED", "CLOSED", "STILL_OPEN", "MISSED_MACHINE_OFF", "ERROR")

NUMERIC = {
    "equity": ["equity_usdt", "btc", "usdt", "price"],
    "a_windows": ["price_2055", "sma200", "equity_start", "target_qty", "entry_filled", "fill_rate", "entry_avg", "entry_slip_real_bp",
                  "entry_slip_demo_bp", "exit_avg", "exit_slip_real_bp", "exit_slip_demo_bp", "fees_usdt", "funding_usdt", "pnl_usdt",
                  "pnl_bp", "real_mid_2100", "real_mid_2300", "demo_mid_2100", "demo_mid_2300", "n_orders"],
    "b_days": ["close_prev", "sma50", "qty", "avg_price", "fee_usdt", "slip_real_bp", "slip_demo_bp", "ref_price_0000", "equity_usdt",
               "btc", "usdt", "delay_min"],
    "fills": ["price", "qty", "fee", "fee_usdt", "realized_pnl", "ref_real_mid", "ref_demo_mid", "slip_real_bp", "slip_demo_bp"],
    "runs": ["duration_s"],
}


# ---------------------------------------------------------------- loading
def utcnow(): return datetime.now(timezone.utc)


def load_logs():
    logs = {n: L.read(n) for n in L.COLUMNS}
    for name, cols in NUMERIC.items():
        for c in cols:
            if c in logs[name]: logs[name][c] = pd.to_numeric(logs[name][c], errors="coerce")
    return logs


def last_per_day(df):
    """One row per day, the last one written (corrections are new rows; the last wins)."""
    if df.empty or "day" not in df: return df
    return df.groupby("day", sort=True).tail(1).set_index("day").sort_index()


def daily_equity(eq, strategy):
    """Equity per day for one strategy, from the snapshots. A snapshot at 00:00-00:29 UTC (the 00:01 b-check) is the
    end of the PREVIOUS day. Index: UTC midnight of the day whose end the value represents."""
    e = eq[eq.strategy == strategy]
    e = e[e.equity_usdt.notna()]
    if e.empty: return pd.Series(dtype=float)
    ts = pd.to_datetime(e.ts_utc, utc=True)
    eff = ts.dt.normalize() - pd.to_timedelta(((ts.dt.hour == 0) & (ts.dt.minute < 30)).astype(int), unit="D")
    s = pd.Series(e.equity_usdt.to_numpy(dtype=float), index=pd.DatetimeIndex(eff))
    return s.groupby(level=0).last().sort_index()


# ---------------------------------------------------------------- expected (backtest maths on the same days)
def expected_series(hourly):
    """Daily log-return series of the backtest maths on complete days: Buy & hold, B alone, A alone (1x), B + A (1x)."""
    hrs = hourly.close.resample("1D").count(); full = hrs[hrs == 24]
    if full.empty: return None
    h = hourly[: full.index[-1] + pd.Timedelta(hours=23)]
    r = build(h)
    return dict(r["strats"], a_on=r["a_on"], last_full=full.index[-1])


def span_stats(s_paper, exp_series):
    """Paper equity (daily, from snapshots) vs the expected curve over the same days. Returns totals and plot points."""
    out = {"paper": None, "expected": None, "maxdd": None, "paper_pts": [], "exp_pts": [], "start": None, "end": None, "days": 0}
    if s_paper.empty: return out
    base = float(s_paper.iloc[0]); out["start"], out["end"] = s_paper.index[0], s_paper.index[-1]
    out["paper"] = float(s_paper.iloc[-1] / base - 1); out["maxdd"] = float((s_paper / s_paper.cummax() - 1).min())
    out["paper_pts"] = [(d + DAY, float(v / base)) for d, v in s_paper.items()]
    out["days"] = int((s_paper.index[-1] - s_paper.index[0]).days)
    if exp_series is not None and len(s_paper) >= 2:
        d0, d1 = s_paper.index[0] + DAY, s_paper.index[-1]
        e = exp_series[d0:d1].fillna(0)
        out["expected"] = float(np.exp(e.sum()) - 1)
        out["exp_pts"] = [(d0, 1.0)] + [(d + DAY, float(v)) for d, v in np.exp(e.cumsum()).items()]
    elif exp_series is not None:
        out["expected"] = 0.0
    return out


def combined_equity(sB, sA):
    """Combined curve = B's daily return + A's daily return (how the backtest adds B + A at 1x each), as growth of 1.
    Before a strategy's first snapshot its equity is taken as unchanged. Independent of the two account sizes."""
    if sB.empty and sA.empty: return pd.Series(dtype=float)
    idx = sB.index.union(sA.index)
    lr = sum(np.log(s.reindex(idx).ffill().bfill()).diff().fillna(0) for s in (sB, sA) if not s.empty)
    return np.exp(lr.cumsum())


def quarter(day): t = pd.Timestamp(day); return f"{t.year}Q{(t.month - 1) // 3 + 1}"
def quarter_end(q): return pd.Period(q, freq="Q").end_time.tz_localize("UTC")


# ---------------------------------------------------------------- the numbers
def compute(now=None, grid_days=14, hourly=None):
    now = now or utcnow()
    now_ts = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now).tz_localize("UTC")
    today = now_ts.normalize()
    logs = load_logs()
    h = load_hourly() if hourly is None else hourly
    dc = daily_closes(h)
    exp = expected_series(h)
    r = {"now": now_ts, "today": today, "dry_run": L._dry, "paper_dir": L.paper_dir(), "logs": logs}

    # ---- signal state (stored data; the real 20:55 check uses the live price)
    try:
        st = S.current_state(h, now=now_ts)
    except Exception as e:  # noqa: BLE001  (a broken data file must not kill the dashboard)
        st = {"ok": False, "errors": [str(e)], "warnings": [], "b_target": None, "a_allowed": None, "b_close": None, "sma50": None,
              "a_price": None, "a_price_source": None, "sma200": None, "state": None, "last_candle": None}
    r["signal"] = st
    r["last_candle"] = h.index[-1] if len(h) else None
    r["data_age_h"] = float((now_ts - (r["last_candle"] + pd.Timedelta(hours=1))).total_seconds() / 3600) if r["last_candle"] is not None else None

    # ---- B
    bd = last_per_day(logs["b_days"]); eq = logs["equity"]
    sB = daily_equity(eq, "B"); sA = daily_equity(eq, "A")
    switches = bd[bd.action.isin(["BUY", "SELL"])] if not bd.empty else bd
    b = {"days": len(bd), "switches": len(switches), "fees": float(switches.fee_usdt.sum()) if len(switches) else 0.0,
         "slip_real": float(switches.slip_real_bp.mean()) if len(switches) and switches.slip_real_bp.notna().any() else None,
         "slip_demo": float(switches.slip_demo_bp.mean()) if len(switches) and switches.slip_demo_bp.notna().any() else None,
         "late_runs": int((bd.delay_min > 30).sum()) if len(bd) else 0, "no_trade": int((bd.status == "NO_TRADE").sum()) if len(bd) else 0,
         "incomplete": int((bd.status == "SWITCH_INCOMPLETE").sum()) if len(bd) else 0, "switch_rows": switches.tail(10)}
    b["span"] = span_stats(sB, exp["B alone"] if exp else None)
    b["bh"] = span_stats(sB, exp["Buy & hold"] if exp else None)["expected"]
    b["switches_yr"] = b["switches"] / max(b["span"]["days"], 1) * 365 if b["span"]["days"] >= 1 else None
    last_b = bd.iloc[-1] if len(bd) else None
    eB = eq[eq.strategy == "B"]
    if len(eB):
        lb = eB.iloc[-1]; b["equity"], b["btc"], b["usdt"], b["equity_ts"] = float(lb.equity_usdt), float(lb.btc), float(lb.usdt), lb.ts_utc
        b["holding"] = "LONG" if lb.btc * (lb.price or 0) >= 0.5 * lb.equity_usdt else "CASH"
    else:
        b.update(equity=None, btc=None, usdt=None, equity_ts=None, holding=last_b.target if last_b is not None else None)
    # signal check: every logged B decision recomputed from the stored data
    b["checks"] = []
    for day, row in bd.iterrows():
        if row.status == "NO_TRADE" or row.target not in ("LONG", "CASH"): continue
        try:
            sig = S.b_signal(dc, day); want = "LONG" if sig["target"] else "CASH"
            ok = want == row.target and (pd.isna(row.sma50) or sig["sma50"] is None or abs(sig["sma50"] - row.sma50) < 0.01)
            b["checks"].append((day, row.target, want, ok))
        except S.SignalError as e:
            b["checks"].append((day, row.target, f"n/a ({e})", True))
    b["mismatches"] = [c for c in b["checks"] if not c[3]]
    r["B"] = b

    # ---- A
    aw = last_per_day(logs["a_windows"])
    counts = aw.status.value_counts().to_dict() if len(aw) else {}
    att = aw[aw.status.isin(A_ATTEMPTED)] if len(aw) else aw
    closed = aw[aw.status == "CLOSED"] if len(aw) else aw
    a = {"days": len(aw), "counts": counts, "allowed": int(aw.allowed.eq("True").sum()) if len(aw) else 0, "attempted": len(att), "closed": len(closed)}
    fr = att.fill_rate.fillna(0) if len(att) else pd.Series(dtype=float)
    a["fill_rate"] = float(fr.mean()) if len(fr) else None
    a["filled_days"] = int((fr > 0).sum()) if len(fr) else 0
    for which in ("real", "demo"):
        cols = [f"entry_slip_{which}_bp", f"exit_slip_{which}_bp"]
        v = pd.concat([closed[c] for c in cols]) if len(closed) else pd.Series(dtype=float)
        a[f"slip_{which}"] = float(v.mean()) if v.notna().any() else None
        a[f"entry_slip_{which}"] = float(att[cols[0]].mean()) if len(att) and att[cols[0]].notna().any() else None
        a[f"exit_slip_{which}"] = float(closed[cols[1]].mean()) if len(closed) and closed[cols[1]].notna().any() else None
    a["avg_bp"] = float(closed.pnl_bp.mean()) if len(closed) and closed.pnl_bp.notna().any() else None
    a["win_rate"] = float((closed.pnl_bp > 0).mean()) if len(closed) else None
    a["pnl_usdt"] = float(closed.pnl_usdt.sum()) if len(closed) else 0.0
    a["fees"] = float(closed.fees_usdt.sum()) if len(closed) else 0.0
    a["funding"] = float(closed.funding_usdt.sum()) if len(closed) else 0.0
    a["exit_types"] = closed.exit_type.value_counts().to_dict() if len(closed) else {}
    a["market_exits"] = sum(v for k, v in a["exit_types"].items() if k != "MAKER")
    a["missed"] = counts.get("MISSED_MACHINE_OFF", 0); a["errors"] = counts.get("ERROR", 0); a["unfilled"] = counts.get("UNFILLED", 0)
    a["still_open"] = counts.get("STILL_OPEN", 0)
    # per-trade comparison with the backtest maths on the same day (after maker fee)
    sim_bp = (exp["A alone (1x)"] * 1e4).where(exp["a_on"]) if exp else pd.Series(dtype=float)
    rows = []
    for day, row in closed.iterrows():
        d = pd.Timestamp(day, tz="UTC"); sb = float(sim_bp[d]) if d in sim_bp.index and pd.notna(sim_bp[d]) else None
        rows.append(dict(day=day, paper=row.pnl_bp, sim=sb, diff=(row.pnl_bp - sb) if sb is not None and pd.notna(row.pnl_bp) else None,
                         fill=row.fill_rate, entry=row.entry_avg, exit=row.exit_avg, exit_type=row.exit_type,
                         es_real=row.entry_slip_real_bp, xs_real=row.exit_slip_real_bp, es_demo=row.entry_slip_demo_bp, xs_demo=row.exit_slip_demo_bp,
                         fees=row.fees_usdt, funding=row.funding_usdt, pnl=row.pnl_usdt, status=row.status))
    a["trades"] = rows
    diffs = [x["diff"] for x in rows if x["diff"] is not None]
    a["sim_same_days"] = float(np.mean([x["sim"] for x in rows if x["sim"] is not None])) if any(x["sim"] is not None for x in rows) else None
    a["exec_drag"] = float(np.mean(diffs)) if diffs else None
    # filter agreement: 20:55 live decision vs the backtest proxy (20:00 candle close) on the same days
    agree = tot = 0
    for day, row in aw.iterrows():
        d = pd.Timestamp(day, tz="UTC")
        if row.allowed in ("True", "False") and exp and d in exp["a_on"].index:
            tot += 1; agree += int((row.allowed == "True") == bool(exp["a_on"][d]))
    a["filter_agree"], a["filter_total"] = agree, tot
    # signal check: every logged 20:55 decision recomputed from the stored closes and the logged price
    a["checks"] = []
    for day, row in aw.iterrows():
        if row.status in ("ERROR", "MISSED_MACHINE_OFF") or row.allowed not in ("True", "False") or pd.isna(row.price_2055): continue
        try:
            sig = S.a_signal(dc, row.price_2055, day); want = "True" if sig["allowed"] else "False"
            a["checks"].append((day, row.allowed, want, want == row.allowed))
        except S.SignalError as e:
            a["checks"].append((day, row.allowed, f"n/a ({e})", True))
    a["mismatches"] = [c for c in a["checks"] if not c[3]]
    # rolling 90 days and quarters (paper), plus the simulated A on the actual candles since the holdout began
    recent = closed[pd.to_datetime(closed.index, utc=True) > today - pd.Timedelta(days=90)] if len(closed) else closed
    a["roll90_n"] = len(recent); a["roll90_bp"] = float(recent.pnl_bp.mean()) if len(recent) and recent.pnl_bp.notna().any() else None
    a["quarters"] = []
    if len(closed):
        for q, g in closed.groupby([quarter(d) for d in closed.index]):
            a["quarters"].append(dict(q=q, n=len(g), bp=float(g.pnl_bp.mean()), usdt=float(g.pnl_usdt.sum()), done=quarter_end(q) < today))
    a["sim_quarters"] = []
    if exp:
        simA = exp["A alone (1x)"][HOLDOUT_START:]; on = exp["a_on"][HOLDOUT_START:]
        for q, g in simA[on].groupby([quarter(d) for d in simA[on].index]):
            a["sim_quarters"].append(dict(q=q, n=len(g), bp=float(g.mean() * 1e4), total=float(np.exp(g.sum()) - 1), done=quarter_end(q) < today))
    a["span"] = span_stats(sA, exp["A alone (1x)"] if exp else None)
    eA = eq[eq.strategy == "A"]
    a["equity"] = float(eA.iloc[-1].equity_usdt) if len(eA) else None; a["equity_ts"] = eA.iloc[-1].ts_utc if len(eA) else None
    a["position"] = float(eA.iloc[-1].btc) if len(eA) else None
    a["recent_rows"] = aw.tail(15)
    r["A"] = a

    # ---- combined
    cmb = combined_equity(sB, sA)
    c = {"sum": (b["equity"] or 0) + (a["equity"] or 0) if (b["equity"] is not None or a["equity"] is not None) else None}
    c["span"] = span_stats(cmb, exp["B + A (1x)"] if exp else None) if not cmb.empty else span_stats(pd.Series(dtype=float), None)
    c["bh"] = span_stats(cmb, exp["Buy & hold"] if exp else None)["expected"] if not cmb.empty else None
    c["bh_pts"] = span_stats(cmb, exp["Buy & hold"] if exp else None)["exp_pts"] if not cmb.empty else []
    r["C"] = c

    # ---- kill switches / review triggers (STRATEGY_RULES.md 6.2)
    ks = []
    done_q = [q for q in a["quarters"] if q["done"]]
    if not a["quarters"]: ks.append(("A: 90-day average per trade negative two quarters running", "stop A, full review", "no paper trades yet", "na"))
    else:
        last2 = done_q[-2:]; cur = [q for q in a["quarters"] if not q["done"]]
        txt = ", ".join(f"{q['q']} {q['bp']:+.1f} bp ({q['n']})" for q in a["quarters"])
        if len(last2) == 2 and all(q["bp"] < 0 for q in last2): s = "bad"
        elif done_q and done_q[-1]["bp"] < 0: s = "warn"
        elif not done_q and cur and cur[0]["bp"] < 0: s = "warn"
        else: s = "ok"
        ks.append(("A: 90-day average per trade negative two quarters running", "stop A, full review", txt, s))
    if a["fill_rate"] is None: ks.append(("A: limit-order fill rate < 80%", "A not viable at these fees", "no entries attempted yet", "na"))
    else: ks.append(("A: limit-order fill rate < 80%", "A not viable at these fees", f"{a['fill_rate']:.0%} over {a['attempted']} day(s)", "ok" if a["fill_rate"] >= FILL_MIN else ("warn" if a["attempted"] < 20 else "bad")))
    if a["slip_real"] is None: ks.append(("A: average slippage > 2 bp vs the REAL mid", "A not viable at these fees", "no closed trades yet", "na"))
    else: ks.append(("A: average slippage > 2 bp vs the REAL mid", "A not viable at these fees", f"real {a['slip_real']:+.2f} bp | demo {a['slip_demo']:+.2f} bp ({a['closed']} trades)", "ok" if a["slip_real"] <= SLIP_MAX else ("warn" if a["closed"] < 20 else "bad")))
    if a["avg_bp"] is None: ks.append((f"A: realised average per trade more than {BP_TOL:.0f} bp below backtest ({BT_A_BP:+.1f} bp)", "do not go live; review", "no closed trades yet", "na"))
    else:
        v = f"paper {a['avg_bp']:+.1f} bp vs backtest {BT_A_BP:+.1f} (same days simulated {a['sim_same_days']:+.1f}; execution drag {a['exec_drag']:+.1f})" if a["sim_same_days"] is not None else f"paper {a['avg_bp']:+.1f} bp vs backtest {BT_A_BP:+.1f}"
        ks.append((f"A: realised average per trade more than {BP_TOL:.0f} bp below backtest ({BT_A_BP:+.1f} bp)", "do not go live; review", v, "ok" if a["avg_bp"] >= BT_A_BP - BP_TOL else ("warn" if a["closed"] < 30 else "bad")))
    if b["switches_yr"] is None or b["span"]["days"] < 30: ks.append(("B: more than ~40 switches a year", "regime change; review", f"{b['switches']} switch(es) in {b['span']['days']} day(s): too early to annualise", "na"))
    else: ks.append(("B: more than ~40 switches a year", "regime change; review", f"{b['switches']} in {b['span']['days']} days = {b['switches_yr']:.0f}/yr (backtest ~{BT_B_SWITCHES_YR})", "ok" if b["switches_yr"] <= B_SWITCH_MAX else "bad"))
    if b["span"]["maxdd"] is None: ks.append(("B: drawdown beyond -58% (worst backtest)", "stop and review", "no equity history yet", "na"))
    else: ks.append(("B: drawdown beyond -58% (worst backtest)", "stop and review", f"max drawdown {ddf(b['span']['maxdd'])}", "ok" if b["span"]["maxdd"] > B_DD_MAX else "bad"))
    n_chk = len(b["checks"]) + len(a["checks"]); n_bad = len(b["mismatches"]) + len(a["mismatches"])
    ks.append(("Either: logged signal differs from signals.py on the same data", "stop; it's a bug until proven otherwise",
               f"{n_chk - n_bad}/{n_chk} decisions agree" if n_chk else "no decisions logged yet", "na" if not n_chk else ("ok" if not n_bad else "bad")))
    r["kill"] = ks

    # ---- operations
    runs = logs["runs"]; cmds = list(RUN_TIMES)
    sched = runs[runs.command.isin(cmds)] if len(runs) else runs
    first_day = pd.Timestamp(sched.day.min(), tz="UTC") if len(sched) else today
    days = [today - pd.Timedelta(days=k) for k in range(grid_days)][::-1]
    days = [d for d in days if d >= first_day] if len(sched) else []        # nothing scheduled yet -> empty grid
    grid, missed = [], 0
    for d in days:
        ds = d.strftime("%Y-%m-%d"); cells = []
        for cmd in cmds:
            hit = sched[(sched.day == ds) & (sched.command == cmd)]
            if len(hit): cells.append((hit.iloc[-1].status, hit.iloc[-1].note))
            else:
                due = d + pd.Timedelta(hours=RUN_TIMES[cmd][0], minutes=RUN_TIMES[cmd][1] + GRACE_MIN)
                if cmd == "dashboard" and d == today: cells.append(("now", "this run"))
                elif d == first_day: cells.append(("-", "first day: runs before the scheduler started are not counted"))
                elif now_ts < due: cells.append(("pending", f"due {RUN_TIMES[cmd][0]:02d}:{RUN_TIMES[cmd][1]:02d} UTC"))
                else: cells.append(("MISSING", "no run logged")); missed += 1
        grid.append((ds, cells))
    al = logs["alerts"]
    week = al[pd.to_datetime(al.ts_utc, utc=True) > now_ts - pd.Timedelta(days=7)] if len(al) else al
    ops = {"grid": grid, "cmds": cmds, "missed": missed, "first_day": first_day, "alerts": al.tail(15).iloc[::-1],
           "alerts_7d": week.level.value_counts().to_dict() if len(week) else {}, "runs_total": len(runs),
           "errors_7d": int((runs[pd.to_datetime(runs.ts_utc, utc=True) > now_ts - pd.Timedelta(days=7)].status == "ERROR").sum()) if len(runs) else 0}
    ops["feed"] = None
    p = DATA_DIR / "update_log.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f: rows_ = list(csv.DictReader(f))
        if rows_: ops["feed"] = rows_[-1]
    notes = []
    for cmd, pat in (("a-enter", "early by"), ("a-exit", "early by"), ("b-check", "late run")):
        lp = L.paper_dir() / "logs" / f"{cmd}.log"
        if lp.exists():
            lines = [ln.strip() for ln in lp.read_text(encoding="utf-8", errors="replace").splitlines() if pat in ln]
            notes += [f"{cmd}: {ln}" for ln in lines[-3:]]
    ops["notes"] = notes
    r["ops"] = ops
    starts = [x for x in (b["span"]["start"], a["span"]["start"]) if x is not None]
    r["paper_start"] = min(starts) if starts else None
    r["paper_days"] = int((today - r["paper_start"]).days) + 1 if starts else 0
    return r


# ---------------------------------------------------------------- formatting
def pct(x, d=2): return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.{d}%}"
def ddf(x): return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.1%}"
def bp(x, d=1): return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.{d}f} bp"
def usd(x, d=2): return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{d}f}"
def num(x, d=2): return "" if x is None or (isinstance(x, float) and np.isnan(x)) or x == "" else (f"{float(x):,.{d}f}" if d else f"{float(x):,.0f}")
def esc(x): return html.escape("" if x is None else str(x))
STATUS_CLASS = {"OK": "ok", "now": "ok", "NO_TRADE": "warn", "MISSED": "bad", "ERROR": "bad", "MISSING": "bad", "pending": "na", "-": "na",
                "CLOSED": "ok", "ENTERED": "ok", "ALLOWED": "ok", "SKIPPED_FILTER": "na", "UNFILLED": "warn", "STILL_OPEN": "bad",
                "MISSED_MACHINE_OFF": "bad", "SWITCHED": "ok", "NO_CHANGE": "na", "SWITCH_INCOMPLETE": "bad", "MAKER": "ok", "MIXED": "warn", "MARKET": "warn"}
KILL_LABEL = {"ok": "OK", "warn": "WATCH", "bad": "TRIGGERED", "na": "no data yet"}


def badge(text, cls=None): return f'<span class="badge {cls or STATUS_CLASS.get(str(text), "na")}">{esc(text)}</span>'


def tile(k, v, s=""): return f'<div class="tile"><div class="k">{esc(k)}</div><div class="v">{v}</div><div class="s">{s}</div></div>'


def table(cols, rows, cls=""):
    if not rows: return '<p class="muted small">nothing logged yet</p>'
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def nice_step(span, n=5):
    raw = max(span, 1e-9) / n; mag = 10 ** np.floor(np.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag: return m * mag
    return 10 * mag


def line_chart(lines, title, w=880, h=280):
    """Inline SVG line chart. lines: [dict(name, pts=[(Timestamp, growth-of-1)], color, dash)]. Theme-aware via CSS vars."""
    lines = [ln for ln in lines if ln["pts"]]
    if not lines: return f'<p class="muted small">{esc(title)}: no equity history yet</p>'
    ml, mr, mt, mb = 56, 16, 30, 28
    xs = [p[0] for ln in lines for p in ln["pts"]]; ys = [p[1] for ln in lines for p in ln["pts"]]
    x0, x1 = min(xs), max(xs)
    if x1 == x0: x0, x1 = x0 - DAY, x1 + DAY
    y0, y1 = min(ys + [1.0]), max(ys + [1.0])
    pad = (y1 - y0) * 0.1 or 0.005; y0, y1 = y0 - pad, y1 + pad
    step = nice_step(y1 - y0); y0 = np.floor(y0 / step) * step; y1 = np.ceil(y1 / step) * step
    dec = max(0, -int(np.floor(np.log10(step * 100)))) if step * 100 < 1 else 0
    X = lambda t: ml + (t - x0) / (x1 - x0) * (w - ml - mr)
    Y = lambda v: mt + (y1 - v) / (y1 - y0) * (h - mt - mb)
    out = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{esc(title)}">',
           f'<text x="{ml}" y="18" style="font-size:13px;font-weight:600;fill:currentColor">{esc(title)}</text>']
    v = y0
    while v <= y1 + 1e-12:
        out.append(f'<line x1="{ml}" x2="{w - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" style="stroke:var(--line);stroke-width:{1.5 if abs(v - 1) < 1e-9 else 0.6}"/>')
        out.append(f'<text x="{ml - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" style="font-size:11px;fill:var(--muted)">{(v - 1) * 100:+.{dec}f}%</text>')
        v += step
    n_days = max(1, (x1 - x0).days); tick_days = max(1, int(np.ceil(n_days / 6)))
    t = x0.normalize()
    while t <= x1:
        if t >= x0:
            out.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{mt}" y2="{h - mb}" style="stroke:var(--line);stroke-width:0.4"/>')
            out.append(f'<text x="{X(t):.1f}" y="{h - 10}" text-anchor="middle" style="font-size:11px;fill:var(--muted)">{t:%d %b}</text>')
        t += pd.Timedelta(days=tick_days)
    for ln in lines:
        pts = ln["pts"]; style = f'stroke:{ln["color"]};stroke-width:{ln.get("width", 1.8)};fill:none' + (";stroke-dasharray:5 4" if ln.get("dash") else "")
        if len(pts) == 1: out.append(f'<circle cx="{X(pts[0][0]):.1f}" cy="{Y(pts[0][1]):.1f}" r="3.5" style="fill:{ln["color"]}"/>')
        else: out.append(f'<polyline points="{" ".join(f"{X(a):.1f},{Y(bb):.1f}" for a, bb in pts)}" style="{style}"/>')
    lx = w - mr
    for ln in reversed(lines):
        label = esc(ln["name"]); tw = 7 * len(ln["name"]) + 26
        lx -= tw
        out.append(f'<line x1="{lx}" x2="{lx + 16}" y1="14" y2="14" style="stroke:{ln["color"]};stroke-width:2{";stroke-dasharray:5 4" if ln.get("dash") else ""}"/>')
        out.append(f'<text x="{lx + 20}" y="18" style="font-size:11px;fill:var(--muted)">{label}</text>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- HTML
CSS = """
:root{--bg:#f6f8fa;--card:#fff;--fg:#1f2328;--muted:#6e7781;--line:#d0d7de;--ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;--na:#6e7781;
--okbg:#dafbe1;--warnbg:#fff8c5;--badbg:#ffebe9;--nabg:#eaeef2}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--card:#161b22;--fg:#e6edf3;--muted:#8b949e;--line:#30363d;--ok:#3fb950;--warn:#d29922;
--bad:#f85149;--na:#8b949e;--okbg:#12361f;--warnbg:#3b2e00;--badbg:#4a1518;--nabg:#21262d}}
body{font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:16px}
.wrap{max-width:1120px;margin:0 auto} h1{font-size:20px;margin:0 0 2px} h2{font-size:16px;margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:13px;margin:14px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:14px 0}
.tiles{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 12px}
.tile{flex:1 1 150px;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px 10px;min-width:140px}
.tile .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em} .tile .v{font-size:18px;font-weight:600;margin:2px 0}
.tile .s{font-size:12px;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:4px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap} th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:600;font-size:12px} td.l,th.l{text-align:left;white-space:normal}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;font-weight:600}
.ok{background:var(--okbg);color:var(--ok)} .warn{background:var(--warnbg);color:var(--warn)} .bad{background:var(--badbg);color:var(--bad)} .na{background:var(--nabg);color:var(--na)}
.muted{color:var(--muted)} .small{font-size:12px} svg{max-width:100%;height:auto;display:block;margin:6px 0}
.grid td{text-align:center} .scroll{overflow-x:auto} .kill td:nth-child(1),.kill td:nth-child(2){text-align:left;white-space:normal}
.sig{display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-size:14px} .sig b{font-size:15px}
"""


def render_html(r):
    b, a, c, ops, st = r["B"], r["A"], r["C"], r["ops"], r["signal"]
    now = r["now"]; H = []
    H.append(f'<div class="wrap"><h1>BTC paper trading: B (50-day trend) + A (21:00-23:00 UTC window){" <span class=\'badge warn\'>DRY RUN</span>" if r["dry_run"] else ""}</h1>')
    H.append(f'<div class="muted small">generated {now:%Y-%m-%d %H:%M} UTC | logs: {esc(r["paper_dir"])} | paper trading since '
             f'{r["paper_start"]:%d %b %Y} ({r["paper_days"]} day(s)) | read-only: this page places no orders | rules: STRATEGY_RULES.md v1.1</div>'
             if r["paper_start"] is not None else f'<div class="muted small">generated {now:%Y-%m-%d %H:%M} UTC | logs: {esc(r["paper_dir"])} | no paper rows yet</div>')
    # signals
    bsig = ("LONG" if st.get("b_target") else "CASH") if st.get("b_target") is not None else "n/a"
    asig = ("ON" if st.get("a_allowed") else "OFF") if st.get("a_allowed") is not None else "n/a"
    age = r["data_age_h"]
    age_cls = "na" if age is None else ("ok" if age <= 3 else ("warn" if age <= 12 else "bad"))
    H.append('<div class="card"><h2>1. Signal state now (from stored candles)</h2><div class="sig">'
             f'<span>B: <b>{badge(bsig, "ok" if bsig == "LONG" else "na")}</b> close {num(st.get("b_close"), 0)} vs SMA50 {num(st.get("sma50"), 0)}</span>'
             f'<span>A: <b>{badge(asig, "ok" if asig == "ON" else "na")}</b> price {num(st.get("a_price"), 0)} [{esc(st.get("a_price_source"))}] vs SMA200 {num(st.get("sma200"), 0)}</span>'
             f'<span>row: <b>{esc(st.get("state"))}</b></span>'
             f'<span>data: last candle {r["last_candle"]:%d %b %H:%M} UTC {badge(f"{age:.1f} h old", age_cls) if age is not None else ""}</span>'
             f'<span>signals ok: {badge("yes" if st.get("ok") else "NO", "ok" if st.get("ok") else "bad")}</span></div>')
    if st.get("warnings"): H.append('<p class="muted small">' + " | ".join(esc(w) for w in st["warnings"]) + "</p>")
    if st.get("errors"): H.append('<p class="small"><span class="badge bad">errors</span> ' + " | ".join(esc(e) for e in st["errors"]) + "</p>")
    H.append('<p class="muted small">The real 20:55 decision uses the live price (harness a-precheck); this line uses the last stored close. '
             'B decides at 00:01 UTC on yesterday\'s close. Nothing trades while the row is "bear": that is correct behaviour.</p></div>')
    # B
    sp = b["span"]
    H.append('<div class="card"><h2>2. Strategy B: 50-day trend (spot demo)</h2><div class="tiles">')
    H.append(tile("holding", badge(b["holding"] or "n/a", "ok" if b["holding"] == "LONG" else "na"), f'{num(b["btc"], 5)} BTC + {usd(b["usdt"])} USDT' if b["equity"] is not None else ""))
    H.append(tile("equity", f'{usd(b["equity"])} USDT', f'at {esc(b["equity_ts"])}' if b["equity_ts"] else ""))
    H.append(tile("paper return", pct(sp["paper"]), f'expected {pct(sp["expected"])} | buy & hold {pct(b["bh"])} | {sp["days"]} day(s)'))
    H.append(tile("max drawdown", ddf(sp["maxdd"]), "limit -58% (worst backtest)"))
    H.append(tile("switches", f'{b["switches"]}', (f'{b["switches_yr"]:.0f}/yr annualised, backtest ~{BT_B_SWITCHES_YR}, review >40' if b["switches_yr"] is not None and sp["days"] >= 30 else f'{b["days"]} day row(s); backtest ~{BT_B_SWITCHES_YR}/yr')))
    H.append(tile("fees paid", f'{usd(b["fees"])} USDT', "0.10% assumed per switch in the backtest"))
    H.append(tile("avg slippage", f'real {bp(b["slip_real"], 2)}', f'demo {bp(b["slip_demo"], 2)} | negative = better than mid'))
    H.append(tile("runs", f'{b["days"]} day(s) logged', f'{b["no_trade"]} no-trade, {b["late_runs"]} late (>30 min), {b["incomplete"]} incomplete'))
    H.append("</div>")
    H.append(line_chart([dict(name="B paper", pts=sp["paper_pts"], color="#1f6feb"), dict(name="B expected (same days)", pts=sp["exp_pts"], color="#8b949e", dash=True)],
                        "B: paper equity vs the backtest maths on the same days (growth since paper start)"))
    H.append("<h3>switches (last 10)</h3>")
    rows = [[esc(d), badge(x.status), esc(x.action), num(x.qty, 5), num(x.avg_price), num(x.fee_usdt), num(x.slip_real_bp, 2), num(x.slip_demo_bp, 2),
             num(x.close_prev, 0), num(x.sma50, 0), num(x.delay_min, 0), f'<span class="small muted">{esc(x.note)}</span>'] for d, x in b["switch_rows"].iterrows()]
    H.append(table(["day", "status", "action", "qty BTC", "avg price", "fee USDT", "slip real bp", "slip demo bp", "close D-1", "SMA50", "delay min", "note"], rows))
    chk = f'{len(b["checks"]) - len(b["mismatches"])}/{len(b["checks"])} logged B decisions agree with signals.py' if b["checks"] else "no B decisions logged yet"
    H.append(f'<p class="small">{badge("signal check", "bad" if b["mismatches"] else ("ok" if b["checks"] else "na"))} {chk}'
             + ("".join(f' | <b>{esc(d)}</b> logged {esc(t)} but signals.py says {esc(w)}' for d, t, w, _ in b["mismatches"])) + "</p></div>")
    # A
    sp = a["span"]; cnt = a["counts"]
    H.append('<div class="card"><h2>3. Strategy A: 21:00-23:00 UTC window (USD-M futures demo)</h2><div class="tiles">')
    H.append(tile("equity", f'{usd(a["equity"])} USDT', (f'position {num(a["position"], 3)} BTC | ' if a["position"] else "") + (f'at {esc(a["equity_ts"])}' if a["equity_ts"] else "")))
    H.append(tile("paper return", pct(sp["paper"]), f'expected {pct(sp["expected"])} | {sp["days"]} day(s)'))
    H.append(tile("days", f'{a["days"]}', f'{a["allowed"]} allowed by the filter, {cnt.get("SKIPPED_FILTER", 0)} skipped, {a["attempted"]} entries attempted'))
    H.append(tile("fill rate", f'{a["fill_rate"]:.0%}' if a["fill_rate"] is not None else "n/a", f'go/no-go >= 80% | {a["filled_days"]}/{a["attempted"]} days got any fill, {a["unfilled"]} unfilled'))
    H.append(tile("avg slippage per side", f'real {bp(a["slip_real"], 2)}', f'demo {bp(a["slip_demo"], 2)} | go/no-go <= 2 bp vs REAL mid'))
    H.append(tile("avg per trade", bp(a["avg_bp"]), f'backtest {BT_A_BP:+.1f} bp | same days simulated {bp(a["sim_same_days"])} | drag {bp(a["exec_drag"])}'))
    H.append(tile("closed trades", f'{a["closed"]}', f'win rate {pct(a["win_rate"], 0)[1:] if a["win_rate"] is not None else "n/a"} | P&L {usd(a["pnl_usdt"])} USDT'))
    H.append(tile("fees + funding", f'{usd(a["fees"])} + {usd(a["funding"])} USDT', f'exits: {", ".join(f"{k} {v}" for k, v in a["exit_types"].items()) or "none"}'))
    H.append(tile("rolling 90 days", bp(a["roll90_bp"]), f'{a["roll90_n"]} trade(s) | kill switch: negative two quarters running'))
    H.append(tile("problems", f'{a["missed"] + a["errors"] + a["still_open"]}', f'{a["missed"]} missed (machine off), {a["errors"]} errors, {a["still_open"]} still open after 23:00'))
    H.append("</div>")
    H.append(line_chart([dict(name="A paper", pts=sp["paper_pts"], color="#8957e5"), dict(name="A expected (same days)", pts=sp["exp_pts"], color="#8b949e", dash=True)],
                        "A: paper equity vs the backtest maths on the same days (growth since paper start)"))
    H.append("<h3>windows (last 15)</h3>")
    rows = [[esc(d), badge(x.status), esc(x.allowed), num(x.price_2055, 0), num(x.sma200, 0), f'{x.fill_rate:.0%}' if pd.notna(x.fill_rate) else "",
             num(x.entry_avg), num(x.exit_avg), badge(x.exit_type) if x.exit_type else "", num(x.entry_slip_real_bp, 2), num(x.exit_slip_real_bp, 2),
             num(x.entry_slip_demo_bp, 2), num(x.exit_slip_demo_bp, 2), num(x.fees_usdt, 4), num(x.funding_usdt, 4), num(x.pnl_usdt), num(x.pnl_bp, 1),
             f'<span class="small muted">{esc(x.note)}</span>'] for d, x in a["recent_rows"].iterrows()]
    H.append('<div class="scroll">' + table(["day", "status", "allowed", "price 20:55", "SMA200", "fill", "entry", "exit", "exit type", "entry slip real", "exit slip real",
                                             "entry slip demo", "exit slip demo", "fees", "funding", "P&L USDT", "P&L bp", "note"], rows) + "</div>")
    if a["trades"]:
        H.append("<h3>paper vs expected, per closed trade (last 15; bp after fees; expected = backtest maths on that day's candles)</h3>")
        rows = [[esc(t["day"]), num(t["paper"], 1), num(t["sim"], 1), num(t["diff"], 1), f'{t["fill"]:.0%}' if pd.notna(t["fill"]) else "", badge(t["exit_type"])] for t in a["trades"][-15:]]
        H.append(table(["day", "paper bp", "expected bp", "difference", "fill", "exit"], rows))
    H.append("<h3>by quarter</h3>")
    rows = [[esc(q["q"]) + ("" if q["done"] else " (in progress)"), "paper", q["n"], num(q["bp"], 1), num(q["usdt"])] for q in a["quarters"]]
    rows += [[esc(q["q"]) + ("" if q["done"] else " (in progress)"), f"simulated on actual candles (holdout from {HOLDOUT_START})", q["n"], num(q["bp"], 1), pct(q["total"], 1)] for q in a["sim_quarters"]]
    H.append(table(["quarter", "source", "trades", "avg bp/trade", "total"], rows))
    chk = f'{len(a["checks"]) - len(a["mismatches"])}/{len(a["checks"])} logged 20:55 decisions agree with signals.py' if a["checks"] else "no 20:55 decisions logged yet"
    H.append(f'<p class="small">{badge("signal check", "bad" if a["mismatches"] else ("ok" if a["checks"] else "na"))} {chk}'
             + ("".join(f' | <b>{esc(d)}</b> logged {esc(t)} but signals.py says {esc(w)}' for d, t, w, _ in a["mismatches"]))
             + (f' | filter agreed with the backtest proxy (20:00 close) on {a["filter_agree"]}/{a["filter_total"]} days' if a["filter_total"] else "") + "</p>")
    H.append('<p class="muted small">Demo futures microstructure is not the real book (spread 0.02-4.6 bp seen vs 0.02 bp real): judge fills and slippage on the REAL-mid columns.</p></div>')
    # combined
    sp = c["span"]
    H.append('<div class="card"><h2>4. Combined B + A</h2><div class="tiles">')
    H.append(tile("sum of both accounts", f'{usd(c["sum"])} USDT', f'B {usd(b["equity"])} + A {usd(a["equity"])}'))
    H.append(tile("combined return", pct(sp["paper"]), f'B return + A return per day, as the backtest adds them | {sp["days"]} day(s)'))
    H.append(tile("expected (same days)", pct(sp["expected"]), f'buy & hold {pct(c["bh"])}'))
    H.append(tile("max drawdown", ddf(sp["maxdd"]), "combined curve"))
    H.append("</div>")
    H.append(line_chart([dict(name="B+A paper", pts=sp["paper_pts"], color="#238636"), dict(name="B+A expected", pts=sp["exp_pts"], color="#8b949e", dash=True),
                         dict(name="buy & hold", pts=c["bh_pts"], color="#d29922", dash=True, width=1.2)], "B + A: combined paper vs expected vs buy & hold (growth since paper start)"))
    H.append("</div>")
    # kill switches
    H.append('<div class="card"><h2>5. Kill switches and review triggers (STRATEGY_RULES.md 6.2)</h2>')
    rows = [[esc(t), esc(act), esc(v), badge(KILL_LABEL[s], s)] for t, act, v, s in r["kill"]]
    H.append(table(["trigger", "action if hit", "current reading", "status"], rows, "kill"))
    H.append('<p class="muted small">Go/no-go for A is read after 90 days of paper trading (STRATEGY_RULES.md 6.2). WATCH = below the line but too few trades to call. '
             'The simulated quarters above are context from the holdout, not paper results.</p></div>')
    # operations
    H.append('<div class="card"><h2>6. Operations</h2><div class="tiles">')
    H.append(tile("missed scheduled runs", f'{ops["missed"]}', f'in the grid below (since {ops["first_day"]:%d %b})'))
    H.append(tile("alerts, last 7 days", " ".join(f'{v} {k}' for k, v in ops["alerts_7d"].items()) or "none", f'{ops["errors_7d"]} run(s) ended in ERROR'))
    fd = ops["feed"]
    H.append(tile("data feed, last run", f'{badge(fd["status"], "ok" if fd["status"] in ("OK", "NO_NEW") else "bad")} {esc(fd["run_utc"])}' if fd else "n/a",
                  (f'+{fd["rows_added"]} rows to {esc(fd["last_new"][:16])}' + (f' | {esc(fd["errors"])}' if fd.get("errors") else "")) if fd else "no update_log.csv"))
    H.append(tile("runs logged", f'{ops["runs_total"]}', "all commands, including manual ones"))
    H.append("</div><h3>scheduled runs by day (UTC)</h3>")
    rows = [[esc(ds)] + [f'<span title="{esc(note)}">{badge(s)}</span>' for s, note in cells] for ds, cells in ops["grid"]]
    H.append(table(["day"] + ops["cmds"], rows, "grid") if rows else '<p class="muted small">no scheduled runs yet (install scheduler/install_tasks.ps1)</p>')
    H.append('<p class="muted small">MISSING = no run logged by its time + 20 min (laptop asleep, WSL failed to start, task not installed). '
             'NO_TRADE = the run refused to trade (failed data update or signal not ok): see alerts.</p>')
    if ops["notes"]: H.append("<h3>timing notes from the logs</h3><ul class='small'>" + "".join(f"<li>{esc(n)}</li>" for n in ops["notes"]) + "</ul>")
    H.append("<h3>alerts (latest 15)</h3>")
    rows = [[esc(x.ts_utc), badge(x.level, {"ERROR": "bad", "WARN": "warn", "INFO": "na"}.get(x.level, "na")), esc(x.command), f'<span class="l">{esc(x.message)}</span>'] for _, x in ops["alerts"].iterrows()]
    H.append(table(["time", "level", "command", "message"], rows))
    H.append("</div>")
    H.append(f'<p class="muted small">Dashboard built by code/dashboard.py from {esc(r["paper_dir"])}/*.csv and data/btc_1h.csv. Expected curves: fresh_oos.build (= backtest.py) with signals.py. '
             'No parameter is tuned on data after 31 Jul 2026.</p></div>')
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>BTC paper trading dashboard</title><style>{CSS}</style></head><body>" + "".join(H) + "</body></html>")


def write_html(r, out=None):
    out = Path(out) if out else r["paper_dir"] / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".html.tmp"); tmp.write_text(render_html(r), encoding="utf-8"); tmp.replace(out)
    return out


# ---------------------------------------------------------------- JSON for the Vite front end (frontend/)
def clean(o):
    """Recursively make a value JSON-safe: numpy scalars -> Python, NaN/Inf -> null, Timestamps -> ISO strings,
    DataFrames -> list of row dicts (the index becomes a column when it is not a plain range)."""
    if o is None or isinstance(o, str): return o
    if o is pd.NaT: return None
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, pd.DataFrame):
        df = o if isinstance(o.index, pd.RangeIndex) else o.reset_index()
        return [clean(rec) for rec in df.to_dict("records")]
    if isinstance(o, pd.Series): return clean(o.tolist())
    if isinstance(o, (pd.Timestamp, datetime)): return o.isoformat()
    if isinstance(o, Path): return str(o)
    if isinstance(o, (bool, np.bool_)): return bool(o)
    if isinstance(o, (int, np.integer)): return int(o)
    if isinstance(o, (float, np.floating)): return None if (np.isnan(o) or np.isinf(o)) else float(o)
    return str(o)


def payload(r):
    """Every dashboard number as one JSON-safe dict (schema 1). frontend/src/types.ts mirrors this shape."""
    b, a, c, ops, st = r["B"], r["A"], r["C"], r["ops"], r["signal"]
    def span(sp): return {"paper_return": sp["paper"], "expected_return": sp["expected"], "max_dd": sp["maxdd"], "days": sp["days"], "start": sp["start"], "end": sp["end"]}
    def curve(sp, **extra): return {"paper": [[t, v] for t, v in sp["paper_pts"]], "expected": [[t, v] for t, v in sp["exp_pts"]], **extra}
    def mism(lst): return [{"day": d, "logged": t, "computed": w} for d, t, w, _ in lst]
    bsig = ("LONG" if st.get("b_target") else "CASH") if st.get("b_target") is not None else None
    asig = ("ON" if st.get("a_allowed") else "OFF") if st.get("a_allowed") is not None else None
    a_keys = ("equity", "equity_ts", "position", "counts", "allowed", "attempted", "closed", "fill_rate", "filled_days", "slip_real", "slip_demo",
              "entry_slip_real", "exit_slip_real", "entry_slip_demo", "exit_slip_demo", "avg_bp", "win_rate", "pnl_usdt", "fees", "funding",
              "exit_types", "market_exits", "missed", "errors", "unfilled", "still_open", "sim_same_days", "exec_drag", "filter_agree",
              "filter_total", "roll90_n", "roll90_bp", "quarters", "sim_quarters", "trades")
    out = {
        "schema": 1, "generated_utc": r["now"], "dry_run": r["dry_run"], "paper_dir": r["paper_dir"], "paper_start": r["paper_start"],
        "paper_days": r["paper_days"],
        "thresholds": {"fill_min": FILL_MIN, "slip_max_bp": SLIP_MAX, "bp_tolerance": BP_TOL, "backtest_a_bp": BT_A_BP, "b_switch_max_yr": B_SWITCH_MAX,
                       "b_dd_max": B_DD_MAX, "backtest_b_switches_yr": BT_B_SWITCHES_YR, "holdout_start": HOLDOUT_START},
        "signal": {"b": bsig, "a": asig, "state": st.get("state"), "b_close": st.get("b_close"), "sma50": st.get("sma50"), "a_price": st.get("a_price"),
                   "a_price_source": st.get("a_price_source"), "sma200": st.get("sma200"), "ok": bool(st.get("ok")), "warnings": list(st.get("warnings", [])),
                   "errors": list(st.get("errors", [])), "last_candle": r["last_candle"], "data_age_h": r["data_age_h"]},
        "B": {**span(b["span"]), "holding": b["holding"], "equity": b["equity"], "btc": b["btc"], "usdt": b["usdt"], "equity_ts": b["equity_ts"],
              "bh_return": b["bh"], "days_logged": b["days"], "switches": b["switches"], "switches_yr": b["switches_yr"], "fees": b["fees"],
              "slip_real": b["slip_real"], "slip_demo": b["slip_demo"], "late_runs": b["late_runs"], "no_trade": b["no_trade"], "incomplete": b["incomplete"],
              "checks": len(b["checks"]), "mismatches": mism(b["mismatches"]), "curve": curve(b["span"]), "switch_rows": b["switch_rows"]},
        "A": {**span(a["span"]), **{k: a[k] for k in a_keys}, "days_logged": a["days"], "checks": len(a["checks"]), "mismatches": mism(a["mismatches"]),
              "curve": curve(a["span"]), "recent_rows": a["recent_rows"]},
        "C": {**span(c["span"]), "sum": c["sum"], "bh_return": c["bh"], "curve": curve(c["span"], bh=[[t, v] for t, v in c["bh_pts"]])},
        "kill": [{"trigger": t, "action": act, "reading": v, "status": s} for t, act, v, s in r["kill"]],
        "ops": {"missed": ops["missed"], "first_day": ops["first_day"], "cmds": ops["cmds"],
                "grid": [{"day": ds, "cells": [{"status": s, "note": n} for s, n in cells]} for ds, cells in ops["grid"]],
                "alerts": ops["alerts"], "alerts_7d": ops["alerts_7d"], "errors_7d": ops["errors_7d"], "runs_total": ops["runs_total"],
                "feed": ops["feed"], "notes": ops["notes"]},
    }
    return clean(out)


def write_json(r, out=None):
    out = Path(out) if out else r["paper_dir"] / "dashboard.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp"); tmp.write_text(json.dumps(payload(r), allow_nan=False, indent=1), encoding="utf-8"); tmp.replace(out)
    return out


# ---------------------------------------------------------------- terminal summary
def print_summary(r):
    b, a, c, ops, st = r["B"], r["A"], r["C"], r["ops"], r["signal"]
    print(f"=== BTC paper-trading dashboard {r['now']:%Y-%m-%d %H:%M} UTC{' [DRY RUN]' if r['dry_run'] else ''} | logs {r['paper_dir']} ===")
    bsig = ("LONG" if st.get("b_target") else "CASH") if st.get("b_target") is not None else "n/a"
    asig = ("ON" if st.get("a_allowed") else "OFF") if st.get("a_allowed") is not None else "n/a"
    print(f"Data: last candle {r['last_candle']} ({r['data_age_h']:.1f} h old) | B {bsig} (close {num(st.get('b_close'), 0)} vs SMA50 {num(st.get('sma50'), 0)}) | "
          f"A {asig} ({num(st.get('a_price'), 0)} [{st.get('a_price_source')}] vs SMA200 {num(st.get('sma200'), 0)}) | {st.get('state')} | ok={st.get('ok')}"
          if r["last_candle"] is not None else "Data: none")
    for e in st.get("errors", []): print("  signal ERROR:", e)
    sp = b["span"]
    print(f"B: holding {b['holding']} | equity {usd(b['equity'])} USDT | return {pct(sp['paper'])} (expected {pct(sp['expected'])}, buy&hold {pct(b['bh'])}) over {sp['days']} day(s) | "
          f"maxDD {ddf(sp['maxdd'])} | switches {b['switches']}" + (f" (~{b['switches_yr']:.0f}/yr)" if b["switches_yr"] is not None and sp["days"] >= 30 else "")
          + f" | fees {usd(b['fees'])} | slip real {bp(b['slip_real'], 2)} / demo {bp(b['slip_demo'], 2)} | signal checks {len(b['checks']) - len(b['mismatches'])}/{len(b['checks'])}")
    sp = a["span"]
    print(f"A: equity {usd(a['equity'])} USDT | return {pct(sp['paper'])} (expected {pct(sp['expected'])}) | days {a['days']}: {a['allowed']} allowed, {a['attempted']} attempted, "
          f"{a['closed']} closed, {a['unfilled']} unfilled, {a['missed']} missed, {a['errors']} errors | fill rate {f'{a['fill_rate']:.0%}' if a['fill_rate'] is not None else 'n/a'} | "
          f"slip/side real {bp(a['slip_real'], 2)} / demo {bp(a['slip_demo'], 2)} | avg/trade {bp(a['avg_bp'])} (same days simulated {bp(a['sim_same_days'])}, backtest {BT_A_BP:+.1f}) | "
          f"P&L {usd(a['pnl_usdt'])} USDT | exits {a['exit_types'] or '{}'} | signal checks {len(a['checks']) - len(a['mismatches'])}/{len(a['checks'])}")
    if a["sim_quarters"]:
        print("   simulated A by quarter (holdout, actual candles): " + " | ".join(f"{q['q']}{'' if q['done'] else '*'} {q['n']} trades {q['bp']:+.1f} bp {q['total']:+.1%}" for q in a["sim_quarters"]) + "   (* in progress)")
    sp = c["span"]
    print(f"B+A: sum of accounts {usd(c['sum'])} USDT | combined return {pct(sp['paper'])} (expected {pct(sp['expected'])}, buy&hold {pct(c['bh'])}) | maxDD {ddf(sp['maxdd'])}")
    print("Kill switches (STRATEGY_RULES 6.2):")
    for t, act, v, s in r["kill"]: print(f"   [{KILL_LABEL[s]:>11s}] {t}: {v}")
    print(f"Operations: missed scheduled runs {ops['missed']} (grid since {ops['first_day']:%d %b}) | alerts last 7 d {ops['alerts_7d'] or 'none'} | runs ending in ERROR last 7 d {ops['errors_7d']}"
          + (f" | feed {ops['feed']['status']} at {ops['feed']['run_utc']}" if ops["feed"] else ""))
    for ds, cells in ops["grid"][-7:]:
        print("   " + ds + "  " + " | ".join(f"{cmd} {s}" for cmd, (s, _) in zip(ops["cmds"], cells)))
    for n in ops["notes"]: print("   note:", n)
    for _, x in ops["alerts"].head(3).iterrows(): print(f"   alert {x.ts_utc} {x.level} {x.command}: {x.message[:90]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="BTC paper-trading dashboard (read-only).")
    ap.add_argument("--dry-run", action="store_true", help="read the dry-run logs (data/paper/dryrun/)")
    ap.add_argument("--no-html", action="store_true", help="terminal summary only (no html, no json)")
    ap.add_argument("--days", type=int, default=14, help="days shown in the operations grid")
    ap.add_argument("--out", default=None, help="write the HTML here instead of <logs>/dashboard.html (the JSON goes next to it)")
    ap.add_argument("--now", default=None, help="replay: pretend it is this UTC time, e.g. '2026-11-20 23:10' (tests)")
    a = ap.parse_args(argv)
    L.set_dry_run(a.dry_run)
    with L.Run("dashboard") as run:
        r = compute(now=pd.Timestamp(a.now, tz="UTC") if a.now else None, grid_days=a.days)
        print_summary(r)
        if not a.no_html:
            out = write_html(r, a.out); print("written:", out)
            outj = write_json(r, Path(a.out).with_suffix(".json") if a.out else None); print("written:", outj)
            run.note = f"html+json {out.name}; missed runs {r['ops']['missed']}; alerts 7d {sum(r['ops']['alerts_7d'].values())}"
        else:
            run.note = "text only"
    return 0


if __name__ == "__main__":
    sys.exit(main())
