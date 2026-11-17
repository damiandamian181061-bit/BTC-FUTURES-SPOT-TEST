"""
Paper-trading harness (step 4): the entry point the scheduler calls. STRATEGY_RULES.md v1.1 sections 2.2 and 3.2.

  btc-bot harness status                 balances, position, open orders, today's signals. No orders.
  btc-bot harness setup                  A one-time setup: one-way mode, ISOLATED margin, leverage (default 3x)
  btc-bot harness b-check                00:01 UTC  B: update data, compute target, switch spot holding if needed
  btc-bot harness a-precheck             20:55 UTC  A: live price vs SMA200[D-1]; records ALLOWED / SKIPPED_FILTER
  btc-bot harness a-enter                21:00 UTC  A: post-only buy at the bid until 21:05; never market-buys
  btc-bot harness a-exit                 22:55 UTC  A: post-only sell at the ask until 23:00, then market
  btc-bot harness a-test                 supervised test: post-only orders 5% away from the market, then cancelled
  btc-bot harness flatten                emergency: cancel A's orders and close A's position at market
  btc-bot harness relog --strategy B --order-id N   recovery: re-fetch an order and write its fills/day row

Flags: --dry-run (fake exchange seeded from the real public book, auto-fills, logs to data/paper/dryrun/; its fake
       balances persist in data/paper/dryrun/fake_*.json: delete those to start the dry run afresh),
       --deadline-min N (entry/exit loop ends N minutes from now instead of at 21:05 / 23:00: for tests),
       --leverage N (setup), --poll S (seconds between book reads, default 2).
Exit code 0 = ran as intended (including "no trade today"), 1 = alert raised (see data/paper/alerts.csv).

Sizing (decided 16 Nov 2026 evening): each strategy from its OWN demo account. B = 1.0 x spot account value,
A = 1.0 x futures account value (totalMarginBalance). Both match the backtest's 'B alone' / 'A alone' at 1x.
Never increases size after a loss: size is always re-measured from the current balance.
Safety: no trade on a failed data update or a not-ok signal (alert instead). A never holds past 23:00.
A machine that was asleep at 21:00 logs MISSED_MACHINE_OFF, not UNFILLED, so the fill rate stays honest.
"""
import argparse, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.dont_write_bytecode = True
from . import exchange as X, ledger as L, orders as O

A_ENTRY, A_ENTRY_END, A_EXIT, A_EXIT_END = (21, 0), (21, 5), (22, 55), (23, 0)   # UTC
B_LIMIT_MINUTES = 15                   # B: limit at the touch for this long, then market (rule 2.2)
A_LEVERAGE = 3                         # A: 1x notional on ~1/3 collateral (rule 4.3 / 6.1.2)
B_BUY_BUFFER = 0.001                   # keep 0.1% of USDT back on a spot buy (price can tick up before the fill)
LONG_THRESHOLD = 0.5                   # spot: BTC worth >= 50% of equity counts as LONG (for labels)
DUST_FRACTION = 0.01                   # B trades any leftover on the wrong side worth > 1% of equity (and > 2 x min notional)


def utcnow(): return datetime.now(timezone.utc)


def wait_until(t, a, max_wait=120):
    """If launched up to 2 minutes early (the scheduler starts WSL a bit before the window), sleep until exactly `t`."""
    if a.deadline_min or a.dry_run: return
    gap = (t - utcnow()).total_seconds()
    if 0 < gap <= max_wait:
        print(f"early by {gap:.0f}s: waiting until {t:%H:%M:%S} UTC"); time.sleep(gap)
def today_utc(): return utcnow().strftime("%Y-%m-%d")
def at(h, m, d=None): return (d or utcnow()).replace(hour=h, minute=m, second=0, microsecond=0)
def ts(dt): return dt.timestamp()


# ---------------------------------------------------------------- clients (real demo or dry-run fake)
class Venues:
    def __init__(self, dry_run):
        self.dry = dry_run
        if dry_run:
            from . import fakebinance as F
            rb_s, rb_f = O.real_book(False), O.real_book(True)
            self.spot_sim = F.Sim(futures=False, bid=rb_s["bid"] if rb_s else 65000.0, ask=rb_s["ask"] if rb_s else 65000.01, usdt=5000.0)
            self.fut_sim = F.Sim(futures=True, bid=rb_f["bid"] if rb_f else 65000.0, ask=rb_f["ask"] if rb_f else 65000.1, usdt=5000.0)
            self.spot_sim.auto_fill = self.fut_sim.auto_fill = True
            self.state_files = (L.paper_dir() / "fake_spot.json", L.paper_dir() / "fake_futures.json")
            loaded = [sim.load(f) for sim, f in zip((self.spot_sim, self.fut_sim), self.state_files)]
            if any(loaded):                                    # keep today's book, restore balances/positions/orders
                if rb_s: self.spot_sim.bid, self.spot_sim.ask = rb_s["bid"], rb_s["ask"]
                if rb_f: self.fut_sim.bid, self.fut_sim.ask = rb_f["bid"], rb_f["ask"]
            self.srv, base = F.serve(self.spot_sim, self.fut_sim)
            self.spot = X.BinanceClient(base, "dry", "dry", futures=False)
            self.fut = X.BinanceClient(base, "dry", "dry", futures=True)
            print(f"DRY RUN: fake exchange at {base} (books seeded from the real public book: {'yes' if rb_f else 'no, offline'})")
        else:
            sec, warns = X.load_secrets()
            for w in warns: L.alert("harness", w, "WARN")
            self.spot, self.fut = X.spot_client(sec), X.futures_client(sec)
            self.spot.sync_time(); self.fut.sync_time()
        self.fs, self.ff = O.load_filters(self.spot), O.load_filters(self.fut)


def snapshot(futures):
    """Demo book + real book side by side."""
    return O.real_book(futures)


def log_order_event(strategy, venue, futures, demo_client, ev, post_only, reduce_only):
    rb = O.real_book(futures)
    L.append("orders", strategy=strategy, venue=venue, event=ev["msg"], order_id=ev.get("order_id"), side=ev.get("side"),
             price=ev.get("price", ev.get("new_touch")), qty=ev.get("qty"), filled=ev.get("filled", ev.get("filled_so_far")),
             post_only=post_only, reduce_only=reduce_only, demo_bid=ev.get("bid"), demo_ask=ev.get("ask"),
             real_bid=rb and rb["bid"], real_ask=rb and rb["ask"], note=ev.get("note", ev.get("reason", "")))


def log_fills(strategy, venue, side, fills, ref_real_mid, ref_demo_mid, client=None):
    for t in fills:
        L.append("fills", strategy=strategy, venue=venue, order_id=t["order_id"], trade_id=t["trade_id"], side=side, price=t["price"],
                 qty=t["qty"], fee=t["fee"], fee_asset=t["fee_asset"], fee_usdt=O.fee_usdt(t, client), maker=t["maker"], realized_pnl=t["realized_pnl"],
                 ref_real_mid=ref_real_mid, ref_demo_mid=ref_demo_mid, slip_real_bp=O.slippage_bp(side, t["price"], ref_real_mid),
                 slip_demo_bp=O.slippage_bp(side, t["price"], ref_demo_mid))


def signal_state(live_price=None, retry_feed=True):
    """signals.current_state(), updating the data first if yesterday's close is missing."""
    from ..strategy import signals as S
    s = S.current_state(price_now=live_price)
    if not s["ok"] and retry_feed and any("run datafeed" in e or "missing" in e for e in s["errors"]):
        print("signal not ok -> running datafeed.py then retrying once"); run_datafeed()
        s = S.current_state(price_now=live_price)
    return s


def run_datafeed():
    from ..data import feed as datafeed
    try:
        return datafeed.update()
    except datafeed.NetworkError as e:
        print("datafeed: NO NETWORK:", e); return 2


def live_price(dry_run):
    from ..data import feed as datafeed
    try:
        return datafeed.latest_price(), "live"
    except datafeed.NetworkError as e:
        if not dry_run: raise
        return None, f"offline ({e})"


def log_signal(strategy, s):
    dec = (("LONG" if s["b_target"] else "CASH") if strategy == "B" else ("ALLOWED" if s["a_allowed"] else "OFF")) if s["ok"] else "NOT_OK"
    L.append("signals", strategy=strategy, decision=dec, price=s["a_price"] if strategy == "A" else s["b_close"],
             price_source=s["a_price_source"] if strategy == "A" else "close", sma=s["sma200"] if strategy == "A" else s["sma50"],
             close_prev=s["b_close"], state=s["state"], ok=s["ok"], warnings=s["warnings"], errors=s["errors"])
    return dec


# ---------------------------------------------------------------- commands
def cmd_status(v, a):
    s = signal_state(retry_feed=False)
    print(f"Signals ({s['now']:%Y-%m-%d %H:%M} UTC, last candle {s['last_candle']}): B {'LONG' if s['b_target'] else 'CASH'} "
          f"(close {s['b_close']:,.0f} vs SMA50 {s['sma50'] or 0:,.0f}) | A {'ON' if s['a_allowed'] else 'OFF'} "
          f"(price {s['a_price']:,.0f} [{s['a_price_source']}] vs SMA200 {s['sma200'] or 0:,.0f}) | {s['state']} | ok={s['ok']}")
    for w in s["warnings"]: print("  warning:", w)
    for e in s["errors"]: print("  ERROR:", e)
    e = O.spot_equity(v.spot); held = "LONG" if e["btc"] * e["price"] >= LONG_THRESHOLD * e["equity"] else "CASH"
    print(f"B spot:    equity {e['equity']:,.2f} USDT = {e['usdt']:,.2f} USDT + {e['btc']:.5f} BTC @ {e['price']:,.2f}  -> holding {held}")
    L.append("equity", strategy="B", equity_usdt=e["equity"], btc=e["btc"], usdt=e["usdt"], price=e["price"], note="status")
    fa, p = O.futures_account(v.fut), O.futures_position(v.fut)
    print(f"A futures: equity {fa['equity']:,.2f} USDT (wallet {fa['wallet']:,.2f}, unrealised {fa['unrealized']:+,.2f}) | position {p['qty']} BTC "
          f"@ {p['entry']:,.2f} | margin {p['margin_type']} | leverage {p['leverage']}")
    L.append("equity", strategy="A", equity_usdt=fa["equity"], btc=p["qty"], usdt=fa["wallet"], price=None, note="status")
    L.append("equity", strategy="B+A", equity_usdt=e["equity"] + fa["equity"], btc=e["btc"] + p["qty"], usdt=e["usdt"] + fa["wallet"], price=e["price"], note="status")
    for name, c, fut in (("B spot", v.spot, False), ("A futures", v.fut, True)):
        oo = O.open_orders(c); b = O.book(c); rb = O.real_book(fut)
        print(f"{name}: open orders {len(oo)} | demo book {b['bid']:,.2f}/{b['ask']:,.2f} ({b['spread_bp']:.2f} bp)"
              + (f" | REAL book {rb['bid']:,.2f}/{rb['ask']:,.2f} ({rb['spread_bp']:.2f} bp)" if rb else " | real book unreachable"))
        for o in oo: print("   open:", o)
    if p["qty"]: L.alert("status", f"A holds {p['qty']} BTC outside its window? check the time (now {utcnow():%H:%M} UTC)", "WARN")
    runs = L.rows("runs")[-5:]; alerts = L.rows("alerts")[-5:]
    print("last runs:  " + " | ".join(f"{r['ts_utc'][5:16]} {r['command']} {r['status']}" for r in runs))
    print("last alerts:" + (" | ".join(f"{r['ts_utc'][5:16]} {r['level']} {r['message'][:60]}" for r in alerts) or " none"))
    return 0


def cmd_setup(v, a):
    if O.futures_position(v.fut)["qty"]: L.alert("setup", "cannot change margin type with an open position"); return 1
    r = O.futures_setup(v.fut, a.leverage)
    print("A futures setup:", "; ".join(r["events"])); p = O.futures_position(v.fut)
    print(f"now: margin {p['margin_type']} | leverage {p['leverage']}x | position {p['qty']}")
    L.append("alerts", level="INFO", command="setup", message="; ".join(r["events"]))
    return 0


def cmd_b_check(v, a, run):
    """00:01 UTC. Update data, compute B's target, switch the spot holding if it differs."""
    day = today_utc(); run.day = day
    delay_min = (utcnow() - at(0, 0)).total_seconds() / 60
    late = f"late run: {delay_min:.0f} min after 00:00 UTC (catch-up)" if delay_min > 30 else ""
    if late: print(late)
    rc = run_datafeed()
    if rc != 0 and not v.dry:
        L.alert("b-check", f"datafeed.py exit {rc}: data not updated -> NO TRADE (rule 2.2.1)"); run.status = "NO_TRADE"; return 1
    s = signal_state(); dec = log_signal("B", s)
    if not s["ok"]:
        L.alert("b-check", "signal not ok: " + " ; ".join(s["errors"]) + " -> NO TRADE"); run.status = "NO_TRADE"; return 1
    e = O.spot_equity(v.spot); held_long = e["btc"] * e["price"] >= LONG_THRESHOLD * e["equity"]
    held = "LONG" if held_long else "CASH"; target = "LONG" if s["b_target"] else "CASH"
    if a.force and v.dry: target = "CASH" if held_long else "LONG"; print("DRY RUN --force: pretending the target is", target)
    print(f"B {day}: close {s['b_close']:,.2f} vs SMA50 {s['sma50']:,.2f} -> target {target}; holding {held} "
          f"(equity {e['equity']:,.2f} USDT: {e['usdt']:,.2f} USDT + {e['btc']:.5f} BTC)")
    base = dict(close_prev=s["b_close"], sma50=s["sma50"], target=target, held_before=held, ref_price_0000=s["b_close"], delay_min=round(delay_min, 1))
    # "in position" means ALL of the account, not just more than half: leftover BTC in CASH (or idle USDT in LONG)
    # above dust size is traded away, so the holding always matches the rule exactly (e.g. the demo's starting 0.05 BTC)
    dust = max(float(v.fs.min_notional) * 2, DUST_FRACTION * e["equity"])
    stray = e["btc_free"] * e["price"] if target == "CASH" else e["usdt_free"]
    if stray <= dust:
        L.append("b_days", status="NO_CHANGE", action="none", equity_usdt=e["equity"], btc=e["btc"], usdt=e["usdt"], note=late, **base)
        L.append("equity", strategy="B", equity_usdt=e["equity"], btc=e["btc"], usdt=e["usdt"], price=e["price"], note="b-check no change")
        run.note = f"no change ({held})"; print("no change."); return 0
    if target == held: print(f"holding counts as {held} but {stray:,.2f} USDT of it is on the wrong side (> dust {dust:,.2f}): trading it")
    side = "BUY" if target == "LONG" else "SELL"
    b0, rb0 = O.book(v.spot), O.real_book(False)
    qty = v.fs.qty(e["usdt_free"] * (1 - B_BUY_BUFFER) / b0["ask"]) if side == "BUY" else v.fs.qty(e["btc_free"])
    why = v.fs.too_small(qty, b0["bid"])
    if why: L.alert("b-check", f"switch {held}->{target} impossible: {why}"); run.status = "NO_TRADE"; return 1
    print(f"bringing the holding to {target}: {side} {qty} BTC, post-only at the touch for {B_LIMIT_MINUTES} min, then market")
    deadline = time.time() + (a.deadline_min or B_LIMIT_MINUTES) * 60
    ev = lambda rec: log_order_event("B", "spot", False, v.spot, dict(rec, side=side), True, False)
    r = O.work_order(v.spot, side, qty, deadline, v.fs, post_only=True, poll=a.poll, on_event=ev, tag="B")
    fills, n_orders = list(r["fills"]), len(r["orders"])
    if not r["complete"]:
        m = O.market_rest(v.spot, side, qty - r["filled"], v.fs, tag="B")
        if m:
            n_orders += 1; fills += m["fills"]
            log_order_event("B", "spot", False, v.spot, {"msg": "market fallback", "order_id": m["order"]["order_id"], "side": side,
                            "qty": m["order"]["qty"], "filled": m["order"]["filled"], "price": m["avg_price"]}, False, False)
    log_fills("B", "spot", side, fills, rb0 and rb0["mid"], b0["mid"], v.spot)
    e2 = O.spot_equity(v.spot); avg = O.avg_price(fills) if fills else 0.0
    fee = sum(O.fee_usdt(t, v.spot) for t in fills); held_after = "LONG" if e2["btc"] * e2["price"] >= LONG_THRESHOLD * e2["equity"] else "CASH"
    L.append("b_days", status="SWITCHED" if held_after == target else "SWITCH_INCOMPLETE", action=side, qty=sum(t["qty"] for t in fills), avg_price=avg,
             fee_usdt=fee, slip_real_bp=O.slippage_bp(side, avg, rb0 and rb0["mid"]), slip_demo_bp=O.slippage_bp(side, avg, b0["mid"]),
             equity_usdt=e2["equity"], btc=e2["btc"], usdt=e2["usdt"], note=(late + " " if late else "") + f"{n_orders} order(s), {len(fills)} fill(s)", **base)
    L.append("equity", strategy="B", equity_usdt=e2["equity"], btc=e2["btc"], usdt=e2["usdt"], price=e2["price"], note=f"after switch to {target}")
    print(f"done: filled {sum(t['qty'] for t in fills)} @ {avg:,.2f}, fee {fee:.2f} USDT, holding now {held_after}; equity {e2['equity']:,.2f}")
    if held_after != target: L.alert("b-check", f"switch to {target} incomplete: holding {held_after}"); return 1
    run.note = f"switched {held}->{target} @ {avg:,.2f}"
    return 0


def cmd_a_precheck(v, a, run):
    """20:55 UTC. Live price vs SMA200 of closes up to yesterday. Writes today's decision; places no orders."""
    day = today_utc(); run.day = day
    px, src = live_price(v.dry)
    s = signal_state(live_price=px)
    if px is None: s["warnings"].append(f"dry run offline: used stored close ({src})")
    dec = log_signal("A", s)
    pos = O.futures_position(v.fut); fa = O.futures_account(v.fut)
    rb = O.real_book(True); mk = O.premium(v.fut) if not v.dry else None
    print(f"A {day} pre-check at {utcnow():%H:%M} UTC: price {s['a_price'] or 0:,.2f} [{s['a_price_source']}] vs SMA200 {s['sma200'] or 0:,.2f} -> {dec}"
          f" | A equity {fa['equity']:,.2f} USDT | position {pos['qty']}" + (f" | mark {mk['mark']:,.2f} funding {mk['funding_rate']:+.4%}" if mk else ""))
    for w in s["warnings"]: print("  warning:", w)
    if pos["qty"]:
        L.alert("a-precheck", f"A already holds {pos['qty']} BTC before the window: flatten first"); run.status = "NO_TRADE"; return 1
    if not s["ok"]:
        L.alert("a-precheck", "signal not ok: " + " ; ".join(s["errors"]) + " -> no trade today"); run.status = "NO_TRADE"
        L.append("a_windows", day=day, status="ERROR", allowed=False, price_2055=s["a_price"], sma200=s["sma200"], equity_start=fa["equity"], note=" ; ".join(s["errors"]))
        return 1
    L.append("a_windows", day=day, status="ALLOWED" if s["a_allowed"] else "SKIPPED_FILTER", allowed=s["a_allowed"], price_2055=s["a_price"],
             sma200=s["sma200"], equity_start=fa["equity"], note=f"real book {rb['bid']:,.2f}/{rb['ask']:,.2f}" if rb else "real book unreachable")
    L.append("equity", strategy="A", equity_usdt=fa["equity"], btc=0.0, usdt=fa["wallet"], price=s["a_price"], note="a-precheck")
    run.note = dec
    return 0


def a_row(day):
    return L.last("a_windows", day=day)


def cmd_a_enter(v, a, run):
    """21:00 UTC. Post-only buy at the best bid, re-posted as the bid rises, cancelled at 21:05. Never market."""
    day = today_utc(); run.day = day; now = utcnow()
    row = a_row(day)
    if row and row["status"] in ("ENTERED", "UNFILLED", "CLOSED", "STILL_OPEN", "MISSED_MACHINE_OFF", "ERROR"):
        L.alert("a-enter", f"a-enter already ran today (status {row['status']}): not entering again", "WARN"); run.note = "already ran"; return 0
    if row is None or row["status"] not in ("ALLOWED", "SKIPPED_FILTER"):
        if now > at(*A_ENTRY_END) and not a.deadline_min:
            L.alert("a-enter", f"no pre-check and it is {now:%H:%M} UTC (> 21:05): day logged as MISSED_MACHINE_OFF", "WARN")
            L.append("a_windows", day=day, status="MISSED_MACHINE_OFF", note="machine off at 20:55-21:05"); run.status = "MISSED"; return 1
        print("no 20:55 pre-check found: doing it now (late)"); L.alert("a-enter", f"pre-check missing, done late at {now:%H:%M} UTC", "WARN")
        rc = cmd_a_precheck(v, a, run)
        if rc: return rc
        row = a_row(day)
    if a.force and v.dry and row["status"] != "ALLOWED":
        print("DRY RUN --force: pretending the 20:55 filter said ALLOWED"); row = dict(row, status="ALLOWED")
    if row["status"] != "ALLOWED":
        print(f"A {day}: filter said {row['status']}: no trade today."); run.note = row["status"]; return 0
    if now > at(*A_ENTRY_END) and not a.deadline_min:
        L.alert("a-enter", f"started at {now:%H:%M} UTC, after 21:05: entry skipped, day logged as MISSED_MACHINE_OFF", "WARN")
        L.append("a_windows", day=day, status="MISSED_MACHINE_OFF", allowed=True, price_2055=row["price_2055"], sma200=row["sma200"],
                 equity_start=row["equity_start"], note=f"a-enter started {now:%H:%M}"); run.status = "MISSED"; return 1
    if O.futures_position(v.fut)["qty"]:
        L.alert("a-enter", "already holding a position at entry time: not adding"); run.status = "NO_TRADE"; return 1
    wait_until(at(*A_ENTRY), a)
    fa = O.futures_account(v.fut); b0 = O.book(v.fut); rb0 = O.real_book(True)
    now = utcnow(); end = now + timedelta(minutes=a.deadline_min) if a.deadline_min else at(*A_ENTRY_END)
    qty = v.ff.qty(fa["equity"] / b0["bid"])
    why = v.ff.too_small(qty, b0["bid"])
    if why: L.alert("a-enter", f"cannot size the entry: {why} (equity {fa['equity']:.2f})"); run.status = "NO_TRADE"; return 1
    print(f"A {day} entry at {now:%H:%M:%S} UTC: BUY {qty} BTC post-only at the bid ({b0['bid']:,.2f}; real {rb0['bid'] if rb0 else 'n/a'}) until {end:%H:%M} UTC; equity {fa['equity']:,.2f}")
    ev = lambda rec: log_order_event("A", "futures", True, v.fut, dict(rec, side="BUY"), True, False)
    r = O.work_order(v.fut, "BUY", qty, ts(end), v.ff, post_only=True, poll=a.poll, on_event=ev, tag="A")
    log_fills("A", "futures", "BUY", r["fills"], rb0 and rb0["mid"], b0["mid"], v.spot)
    pos = O.futures_position(v.fut); fill_rate = r["filled"] / qty if qty else 0
    fees = sum(O.fee_usdt(t, v.spot) for t in r["fills"])
    status = "ENTERED" if r["filled"] > 0 else "UNFILLED"
    L.append("a_windows", day=day, status=status, allowed=True, price_2055=row["price_2055"], sma200=row["sma200"], equity_start=fa["equity"],
             target_qty=qty, entry_filled=r["filled"], fill_rate=round(fill_rate, 4), entry_avg=r["avg_price"],
             entry_slip_real_bp=O.slippage_bp("BUY", r["avg_price"], rb0 and rb0["mid"]), entry_slip_demo_bp=O.slippage_bp("BUY", r["avg_price"], b0["mid"]),
             fees_usdt=fees, real_mid_2100=rb0 and rb0["mid"], demo_mid_2100=b0["mid"], n_orders=len(r["orders"]),
             note=f"{len(r['orders'])} order(s), {len(r['fills'])} fill(s); position {pos['qty']}")
    print(f"entry result: filled {r['filled']} of {qty} ({fill_rate:.0%}) @ {r['avg_price']:,.2f}; fees {fees:.4f}; position {pos['qty']}")
    if status == "UNFILLED": L.alert("a-enter", "entry unfilled by 21:05: day skipped (rule 3.2); no market order", "INFO")
    run.note = f"{status} {r['filled']}/{qty} @ {r['avg_price']:,.2f}"
    return 0


def cmd_a_exit(v, a, run, emergency=False):
    """22:55 UTC. Post-only sell at the ask until 23:00, then market for whatever is left. Also used by flatten."""
    day = today_utc(); run.day = day; now = utcnow()
    end = now + timedelta(minutes=a.deadline_min) if a.deadline_min else at(*A_EXIT_END)
    if emergency: end = now
    pos = O.futures_position(v.fut); row = a_row(day) or {}
    if pos["qty"] <= 0:
        if row.get("status") == "ENTERED":
            L.alert("a-exit", "a_windows says ENTERED but no position found: check the account"); return 1
        if row.get("status") == "ALLOWED":          # pre-check said yes, but no entry run happened
            L.append("a_windows", day=day, status="MISSED_MACHINE_OFF", allowed=True, price_2055=row.get("price_2055"), sma200=row.get("sma200"),
                     equity_start=row.get("equity_start"), note="pre-check ALLOWED but a-enter never ran")
            L.alert("a-exit", "no position and no entry run: day logged as MISSED_MACHINE_OFF", "WARN"); run.status = "MISSED"; return 1
        print(f"A {day}: nothing to exit (position 0, day status {row.get('status', 'none')})."); run.note = "flat"; return 0
    if now > at(*A_EXIT_END) and not a.deadline_min and not emergency:
        L.alert("a-exit", f"exit started at {now:%H:%M} UTC, after 23:00: closing at market immediately", "WARN"); end = now
    if not emergency: wait_until(at(*A_EXIT), a)
    b0 = O.book(v.fut); rb0 = O.real_book(True); qty = v.ff.qty(pos["qty"])
    if a.deadline_min and not emergency: end = utcnow() + timedelta(minutes=a.deadline_min)
    print(f"A {day} exit at {now:%H:%M:%S} UTC: SELL {qty} BTC post-only at the ask ({b0['ask']:,.2f}) until {end:%H:%M} UTC, then market")
    ev = lambda rec: log_order_event("A", "futures", True, v.fut, dict(rec, side="SELL"), True, True)
    r = O.work_order(v.fut, "SELL", qty, ts(end), v.ff, post_only=True, reduce_only=True, poll=a.poll, on_event=ev, tag="A")
    fills, exit_type = list(r["fills"]), "MAKER"
    left = O.futures_position(v.fut)["qty"]
    if left > 0:
        m = O.market_rest(v.fut, "SELL", left, v.ff, reduce_only=True, tag="A")
        if m:
            fills += m["fills"]; exit_type = "MARKET" if not r["fills"] else "MIXED"
            log_order_event("A", "futures", True, v.fut, {"msg": "market fallback at 23:00", "order_id": m["order"]["order_id"], "side": "SELL",
                            "qty": m["order"]["qty"], "filled": m["order"]["filled"], "price": m["avg_price"]}, False, True)
    log_fills("A", "futures", "SELL", fills, rb0 and rb0["mid"], b0["mid"], v.spot)
    pos2 = O.futures_position(v.fut); fa = O.futures_account(v.fut)
    exit_avg = O.avg_price(fills) if fills else 0.0
    exit_fees = sum(O.fee_usdt(t, v.spot) for t in fills); realized = sum(t["realized_pnl"] for t in fills)
    try:
        funding = O.funding_paid(v.fut, int(at(*A_ENTRY).timestamp() * 1000), int(time.time() * 1000))
    except X.ExchangeError:
        funding = 0.0
    entry_fees = float(row.get("fees_usdt") or 0); entry_avg = float(row.get("entry_avg") or 0); entry_qty = float(row.get("entry_filled") or qty)
    pnl = realized - exit_fees - entry_fees + funding
    notional = entry_qty * entry_avg if entry_avg else qty * exit_avg
    L.append("a_windows", day=day, status="CLOSED" if pos2["qty"] == 0 else "STILL_OPEN", allowed=True, price_2055=row.get("price_2055"), sma200=row.get("sma200"),
             equity_start=row.get("equity_start"), target_qty=row.get("target_qty"), entry_filled=row.get("entry_filled"), fill_rate=row.get("fill_rate"),
             entry_avg=row.get("entry_avg"), entry_slip_real_bp=row.get("entry_slip_real_bp"), entry_slip_demo_bp=row.get("entry_slip_demo_bp"),
             exit_avg=exit_avg, exit_type=exit_type, exit_slip_real_bp=O.slippage_bp("SELL", exit_avg, rb0 and rb0["mid"]), exit_slip_demo_bp=O.slippage_bp("SELL", exit_avg, b0["mid"]),
             fees_usdt=entry_fees + exit_fees, funding_usdt=funding, pnl_usdt=pnl, pnl_bp=(pnl / notional * 1e4) if notional else None,
             real_mid_2100=row.get("real_mid_2100"), real_mid_2300=rb0 and rb0["mid"], demo_mid_2100=row.get("demo_mid_2100"), demo_mid_2300=b0["mid"],
             n_orders=int(row.get("n_orders") or 0) + len(r["orders"]) + (1 if exit_type != "MAKER" else 0),
             note=("EMERGENCY flatten; " if emergency else "") + f"exit {exit_type}; {len(fills)} fill(s)")
    L.append("equity", strategy="A", equity_usdt=fa["equity"], btc=pos2["qty"], usdt=fa["wallet"], price=exit_avg, note="after exit")
    print(f"exit result: sold {sum(t['qty'] for t in fills)} @ {exit_avg:,.2f} ({exit_type}); P&L {pnl:+.2f} USDT ({(pnl / notional * 1e4) if notional else 0:+.1f} bp) "
          f"after fees {entry_fees + exit_fees:.4f}; equity {fa['equity']:,.2f}; position now {pos2['qty']}")
    if pos2["qty"] != 0: L.alert("a-exit", f"POSITION STILL OPEN after exit: {pos2['qty']} BTC. Run: harness.py flatten"); return 1
    run.note = f"closed {exit_type} pnl {pnl:+.2f}"
    return 0


def cmd_flatten(v, a, run):
    """Emergency: cancel every A order and close A's position at market. B is left alone."""
    cancelled = O.cancel_all(v.fut); print(f"A: cancelled {len(cancelled)} open order(s)")
    L.alert("flatten", f"flatten requested: cancelled {len(cancelled)} order(s)", "WARN")
    return cmd_a_exit(v, a, run, emergency=True)


def cmd_a_test(v, a, run):
    """Supervised test of the order plumbing: post-only orders 5% below the market on both venues, checked, cancelled."""
    run.day = today_utc(); ok = True
    for name, c, f, fut in (("A futures", v.fut, v.ff, True), ("B spot", v.spot, v.fs, False)):
        b = O.book(c); px = f.price(b["bid"] * 0.95, "BUY")
        qty = f.qty(max(float(f.min_qty), (float(f.min_notional) * 1.2) / px) + float(f.step))
        print(f"{name}: book {b['bid']:,.2f}/{b['ask']:,.2f}; placing post-only BUY {qty} @ {px:,.2f} (5% below)")
        o = O.place_limit(c, "BUY", px, qty, f, post_only=True, client_id=f"TEST{int(time.time()) % 10 ** 8}")
        log_order_event("TEST", "futures" if fut else "spot", fut, c, {"msg": "test placed", "order_id": o["order_id"], "side": "BUY", "price": px, "qty": qty, "bid": b["bid"], "ask": b["ask"]}, True, False)
        o2 = O.get_order(c, o["order_id"]); print(f"   placed: id {o['order_id']} status {o2['status']} price {o2['price']} qty {o2['qty']}")
        time.sleep(2); oo = [x["order_id"] for x in O.open_orders(c)]
        c2 = O.cancel(c, o["order_id"]); o3 = O.get_order(c, o["order_id"])
        print(f"   open orders listed it: {o['order_id'] in oo}; after cancel: status {o3['status']}, filled {o3['filled']}")
        log_order_event("TEST", "futures" if fut else "spot", fut, c, {"msg": "test cancelled", "order_id": o["order_id"], "side": "BUY", "filled": o3["filled"]}, True, False)
        good = o2["status"] == "NEW" and o["order_id"] in oo and o3["status"] == "CANCELED" and o3["filled"] == 0
        print("   OK" if good else "   PROBLEM"); ok &= good
    print("a-test:", "ALL OK" if ok else "problems found (see above)")
    return 0 if ok else 1


def cmd_relog(v, a, run):
    """Recovery: fetch an order that already happened and write its fills (and for B the day's summary row) to the logs.
    Use after a crash between the fill and the logging: harness.py relog --strategy B --order-id 123"""
    if not a.order_id: L.alert("relog", "--order-id required"); return 1
    c, venue, fut = (v.spot, "spot", False) if a.strategy == "B" else (v.fut, "futures", True)
    o = O.get_order(c, a.order_id); fills = O.fills_for(c, a.order_id)
    print(f"order {a.order_id}: {o['side']} {o['type']} status {o['status']} filled {o['filled']} @ {o['avg_price']:,.2f}; {len(fills)} fill(s)")
    for t in fills: print(f"   fill {t['qty']} @ {t['price']:,.2f} fee {t['fee']} {t['fee_asset']} (= {O.fee_usdt(t, v.spot):.4f} USDT) maker={t['maker']}")
    prev = L.last("orders", order_id=a.order_id, event="placed") or {}
    ref_real = (float(prev["real_bid"]) + float(prev["real_ask"])) / 2 if prev.get("real_bid") and prev.get("real_ask") else None
    ref_demo = (float(prev["demo_bid"]) + float(prev["demo_ask"])) / 2 if prev.get("demo_bid") and prev.get("demo_ask") else None
    log_fills(a.strategy, venue, o["side"], fills, ref_real, ref_demo, v.spot)
    if a.strategy == "B":
        from ..strategy import signals as S
        s = S.current_state(); e = O.spot_equity(v.spot); fee = sum(O.fee_usdt(t, v.spot) for t in fills)
        target = "LONG" if s["b_target"] else "CASH"; held_after = "LONG" if e["btc"] * e["price"] >= LONG_THRESHOLD * e["equity"] else "CASH"
        L.append("b_days", day=prev.get("day") or today_utc(), status="SWITCHED" if held_after == target else "SWITCH_INCOMPLETE", close_prev=s["b_close"], sma50=s["sma50"],
                 target=target, held_before="?", action=o["side"], qty=o["filled"], avg_price=o["avg_price"], fee_usdt=fee,
                 slip_real_bp=O.slippage_bp(o["side"], o["avg_price"], ref_real), slip_demo_bp=O.slippage_bp(o["side"], o["avg_price"], ref_demo),
                 ref_price_0000=s["b_close"], equity_usdt=e["equity"], btc=e["btc"], usdt=e["usdt"], note=f"relogged order {a.order_id} after a logging crash")
        L.append("equity", strategy="B", equity_usdt=e["equity"], btc=e["btc"], usdt=e["usdt"], price=e["price"], note="relog")
        print(f"B day row written: holding {held_after}, equity {e['equity']:,.2f} USDT ({e['usdt']:,.2f} USDT + {e['btc']:.5f} BTC), fee {fee:.4f} USDT")
    run.note = f"relogged {a.order_id}"
    return 0


COMMANDS = {"relog": cmd_relog, "status": cmd_status, "setup": cmd_setup, "b-check": cmd_b_check, "a-precheck": cmd_a_precheck, "a-enter": cmd_a_enter,
            "a-exit": cmd_a_exit, "flatten": cmd_flatten, "a-test": cmd_a_test}


def main(argv=None):
    ap = argparse.ArgumentParser(description="BTC paper-trading harness (STRATEGY_RULES.md v1.1).")
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--dry-run", action="store_true", help="fake exchange (no keys needed); logs go to data/paper/dryrun/")
    ap.add_argument("--deadline-min", type=float, default=0, help="end the order loop N minutes from now (tests) instead of 21:05 / 23:00")
    ap.add_argument("--leverage", type=int, default=A_LEVERAGE)
    ap.add_argument("--poll", type=float, default=2.0, help="seconds between book reads in the order loops")
    ap.add_argument("--order-id", type=int, default=0, help="relog: the Binance order id to re-fetch")
    ap.add_argument("--strategy", choices=("A", "B"), default="B", help="relog: which account the order is on")
    ap.add_argument("--force", action="store_true", help="DRY RUN ONLY: pretend the signal says trade (exercises the order paths)")
    a = ap.parse_args(argv)
    if a.force and not a.dry_run: ap.error("--force is only allowed together with --dry-run")
    L.set_dry_run(a.dry_run)
    print(f"harness {a.command} at {utcnow():%Y-%m-%d %H:%M:%S} UTC" + (" [DRY RUN]" if a.dry_run else "") + f" | logs: {L.paper_dir()}")
    with L.Run(a.command) as run:
        try:
            v = Venues(a.dry_run)
        except (X.SecretsError, X.ExchangeError) as e:
            L.alert(a.command, f"cannot connect: {e}"); run.status = "ERROR"; run.note = str(e); return 1
        fn = COMMANDS[a.command]
        rc = fn(v, a) if a.command in ("status", "setup") else fn(v, a, run)
        if a.dry_run:
            for sim, f in zip((v.spot_sim, v.fut_sim), v.state_files): sim.save(f)
            v.srv.shutdown()
        return rc


if __name__ == "__main__":
    sys.exit(main())
