"""
Offline tests for orders.py, ledger.py and fakebinance.py. No network beyond 127.0.0.1, nothing in data/ touched.
Run:  python3 code/test_harness.py      (should end with OK)

 1. Filters: tick/step rounding, string formatting, min-notional check
 2. A entry (futures, post-only): filled at the bid in one go; maker fee; one order
 3. Re-pricing: bid moves up twice -> cancel + re-post each time, then fills; partial fill kept across re-posts
 4. Partial fill then the 21:05 deadline: remainder cancelled, filled qty and average price right
 5. Nothing filled by the deadline -> filled 0, no fills, order cancelled (A skips the day)
 6. Post-only order that would cross (demo book moved between read and send): EXPIRED on futures / -2010 on spot,
    loop re-reads the book and carries on
 7. A exit: post-only sell at the ask, then market fallback for the rest (reduce-only, taker fee, realised P&L)
 8. Spot (B): LIMIT_MAKER buy fills with the fee in BTC; fee_usdt converts; spot_equity adds up; sell at market
 9. futures_setup: ISOLATED + leverage, idempotent (-4046 handled); exchange error inside the loop propagates
10. ledger: rows round-trip, unknown field raises, Run writes heartbeat + alert on exception, dry-run folder
"""
import os, sys, tempfile, unittest
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import exchange as X          # noqa: E402
import orders as O            # noqa: E402
import ledger as L            # noqa: E402
import fakebinance as F       # noqa: E402


class Clock:
    """Fake clock: sleep() advances time instead of waiting."""
    def __init__(self, t=1_800_000_000.0): self.t = t
    def now(self): return self.t
    def sleep(self, s): self.t += s


def loop(c, side, qty, f, sim_time=300, poll=1.0, **kw):
    cl = Clock()
    r = O.work_order(c, side, qty, cl.now() + sim_time, f, poll=poll, clock=cl.now, sleep=cl.sleep, tag="T", **kw)
    return r, cl


class Base(unittest.TestCase):
    def setUp(self):
        self.spot = F.Sim(futures=False, bid=65000.00, ask=65000.01, usdt=10000.0, btc=0.0)
        self.fut = F.Sim(futures=True, bid=65000.0, ask=65000.1, usdt=5000.0)
        self.srv, base = F.serve(self.spot, self.fut)
        self.cs = X.BinanceClient(base, "k", "s", futures=False)
        self.cf = X.BinanceClient(base, "k", "s", futures=True)
        self.fs, self.ff = O.load_filters(self.cs), O.load_filters(self.cf)

    def tearDown(self): self.srv.shutdown()


class T1_filters(unittest.TestCase):
    def test_rounding_and_format(self):
        f = O.Filters("0.10", "0.001", "0.001", "100")
        self.assertEqual(f.price(65106.44, "BUY"), 65106.4); self.assertEqual(f.price(65106.44, "SELL"), 65106.5)
        self.assertEqual(f.qty(0.0769999), 0.076); self.assertEqual(f.qty(-1), 0.0)
        self.assertEqual(f.fmt_price(65106.4), "65106.40"); self.assertEqual(f.fmt_qty(0.076), "0.076")
        self.assertIsNone(f.too_small(0.01, 65000)); self.assertIn("min qty", f.too_small(0.0005, 65000)); self.assertIn("notional", f.too_small(0.001, 50000))
        s = O.Filters("0.01", "0.00001", "0.00001", "5")
        self.assertEqual(s.fmt_qty(0.07692), "0.07692"); self.assertEqual(s.fmt_price(65000.5), "65000.50")


class T2_entry_fills(Base):
    def test_post_only_buy_filled_at_bid(self):
        self.fut.script = [{}, {"fill": 1.0}]                       # 1st poll: place; 2nd: filled
        r, cl = loop(self.cf, "BUY", 0.05, self.ff)
        self.assertEqual(r["filled"], 0.05); self.assertEqual(r["avg_price"], 65000.0); self.assertTrue(r["complete"])
        self.assertEqual(len(r["orders"]), 1); self.assertEqual(r["orders"][0]["status"], "FILLED")
        self.assertEqual(len(r["fills"]), 1); self.assertTrue(r["fills"][0]["maker"])
        self.assertAlmostEqual(r["fills"][0]["fee"], 0.05 * 65000 * 0.0002, places=6)
        self.assertEqual(self.fut.pos, 0.05); self.assertEqual([e["msg"] for e in r["events"]], ["placed", "filled"])
        self.assertLess(cl.now() - 1_800_000_000.0, 10)


class T3_repricing(Base):
    def test_bid_moves_up_twice_then_fills(self):
        self.fut.script = [{}, {"bid": 65010.0, "ask": 65010.1}, {}, {"bid": 65020.0, "ask": 65020.1}, {}, {"fill": 1.0}]  # {} = the re-read after a cancel
        r, _ = loop(self.cf, "BUY", 0.05, self.ff)
        self.assertEqual(r["filled"], 0.05); self.assertEqual(r["avg_price"], 65020.0)
        self.assertEqual([o["status"] for o in r["orders"]], ["CANCELED", "CANCELED", "FILLED"])
        self.assertEqual([o["price"] for o in r["orders"]], [65000.0, 65010.0, 65020.0])
        self.assertEqual(sum(e["msg"].startswith("touch moved") for e in r["events"]), 2)

    def test_partial_fill_kept_across_reprice(self):
        self.fut.script = [{}, {"fill": 0.02}, {"bid": 65010.0, "ask": 65010.1}, {}, {"fill": 1.0}]
        r, _ = loop(self.cf, "BUY", 0.05, self.ff)
        self.assertAlmostEqual(r["filled"], 0.05); self.assertEqual(len(r["fills"]), 2)
        self.assertAlmostEqual(r["avg_price"], (0.02 * 65000 + 0.03 * 65010) / 0.05, places=6)
        self.assertEqual(r["orders"][0]["filled"], 0.02); self.assertEqual(r["orders"][1]["qty"], 0.03)

    def test_bid_moving_down_keeps_order(self):
        self.fut.script = [{}, {"bid": 64990.0, "ask": 64990.1}, {"bid": 64990.0}, {"fill": 1.0}]
        r, _ = loop(self.cf, "BUY", 0.05, self.ff)
        self.assertEqual(len(r["orders"]), 1); self.assertEqual(r["avg_price"], 65000.0)  # our order was still the best bid


class T4_deadline(Base):
    def test_partial_then_deadline(self):
        self.fut.script = [{}, {"fill": 0.02}]
        r, cl = loop(self.cf, "BUY", 0.05, self.ff, sim_time=20)
        self.assertAlmostEqual(r["filled"], 0.02); self.assertFalse(r["complete"]); self.assertEqual(r["avg_price"], 65000.0)
        self.assertEqual(r["orders"][-1]["status"], "CANCELED"); self.assertEqual(r["events"][-1]["msg"], "deadline: cancelled the remainder")
        self.assertAlmostEqual(r["events"][-1]["unfilled"], 0.03); self.assertGreaterEqual(cl.now(), 1_800_000_000.0 + 20)
        self.assertEqual(O.open_orders(self.cf), [])

    def test_nothing_filled(self):
        r, _ = loop(self.cf, "BUY", 0.05, self.ff, sim_time=10)
        self.assertEqual(r["filled"], 0.0); self.assertEqual(r["fills"], []); self.assertEqual(r["avg_price"], 0.0)
        self.assertEqual([o["status"] for o in r["orders"]], ["CANCELED"]); self.assertEqual(self.fut.pos, 0.0)


class T6_would_cross(Base):
    def test_futures_expired_then_ok(self):
        self.fut.script = [{"ask": 65000.0}, {"ask": 65000.1}, {"fill": 1.0}]   # ask == bid -> our bid at 65000 would cross
        r, _ = loop(self.cf, "BUY", 0.05, self.ff)
        self.assertEqual(r["filled"], 0.05); self.assertTrue(any("would have crossed" in e["msg"] for e in r["events"]))
        self.assertEqual(len(r["orders"]), 1)

    def test_spot_rejected_then_ok(self):
        self.spot.script = [{"ask": 65000.00}, {"ask": 65000.01}, {"fill": 1.0}]
        r, _ = loop(self.cs, "BUY", 0.05, self.fs)
        self.assertEqual(r["filled"], 0.05); self.assertTrue(any("would have crossed" in e["msg"] for e in r["events"]))


class T7_exit(Base):
    def test_post_only_sell_then_market_rest(self):
        self.fut.pos, self.fut.entry = 0.05, 65000.0
        self.fut.script = [{}, {"fill": 0.03}]
        r, _ = loop(self.cf, "SELL", 0.05, self.ff, sim_time=15, reduce_only=True)
        self.assertAlmostEqual(r["filled"], 0.03); self.assertEqual(r["avg_price"], 65000.1); self.assertFalse(r["complete"])
        m = O.market_rest(self.cf, "SELL", 0.05 - r["filled"], self.ff, reduce_only=True, tag="T", sleep=lambda s: None)
        self.assertEqual(m["order"]["status"], "FILLED"); self.assertAlmostEqual(m["order"]["filled"], 0.02)
        self.assertEqual(m["avg_price"], 65000.0); self.assertFalse(m["fills"][0]["maker"])
        self.assertAlmostEqual(m["fills"][0]["fee"], 0.02 * 65000 * 0.0004, places=6)
        self.assertAlmostEqual(self.fut.pos, 0.0)
        self.assertAlmostEqual(sum(t["realized_pnl"] for t in r["fills"] + m["fills"]), 0.03 * 0.1, places=6)
        self.assertEqual(O.futures_position(self.cf)["qty"], 0.0)

    def test_reduce_only_clipped_and_too_small(self):
        self.fut.pos, self.fut.entry = 0.05, 65000.0
        self.assertIsNone(O.market_rest(self.cf, "SELL", 0.0004, self.ff, reduce_only=True))
        m = O.market_rest(self.cf, "SELL", 0.09, self.ff, reduce_only=True, sleep=lambda s: None)
        self.assertAlmostEqual(m["order"]["filled"], 0.05); self.assertEqual(self.fut.pos, 0.0)


class T8_spot(Base):
    def test_limit_maker_buy_fee_in_btc_and_equity(self):
        self.spot.script = [{}, {"fill": 1.0}]
        r, _ = loop(self.cs, "BUY", 0.1, self.fs)
        self.assertEqual(r["filled"], 0.1); t = r["fills"][0]
        self.assertEqual(t["fee_asset"], "BTC"); self.assertAlmostEqual(O.fee_usdt(t), 0.1 * 0.001 * 65000, places=6)
        e = O.spot_equity(self.cs, price=65000.0)
        self.assertAlmostEqual(e["btc"], 0.1 - 0.0001); self.assertAlmostEqual(e["usdt"], 10000 - 6500)
        self.assertAlmostEqual(e["equity"], 10000 - 6.5, places=6)
        m = O.market_rest(self.cs, "SELL", e["btc_free"], self.fs, tag="T", sleep=lambda s: None)
        self.assertEqual(m["fills"][0]["fee_asset"], "USDT"); self.assertAlmostEqual(O.spot_equity(self.cs, 65000.0)["btc"], 0.0)
        self.assertEqual(O.slippage_bp("SELL", m["avg_price"], 65000.005), (65000.005 - 65000.0) / 65000.005 * 1e4)

    def test_bnb_fee_converted(self):
        self.spot.bnb_fees = True; self.spot.script = [{}, {"fill": 1.0}]
        r, _ = loop(self.cs, "SELL", 0.0, self.fs) if False else (None, None)
        self.spot.btc = 0.05; r, _ = loop(self.cs, "SELL", 0.05, self.fs)
        t = r["fills"][0]; self.assertEqual(t["fee_asset"], "BNB")
        self.assertAlmostEqual(O.fee_usdt(t, self.cs), 0.05 * 65000.01 * 0.001 * 0.75, places=4)   # 600 USDT/BNB cancels out
        self.assertAlmostEqual(O.fee_usdt(t, self.cs), O.fee_usdt(t), places=4)                    # cached price

    def test_insufficient_balance_raises(self):
        with self.assertRaises(X.ExchangeError) as cm: O.place_limit(self.cs, "BUY", 65000.0, 1.0, self.fs)
        self.assertEqual(cm.exception.code, -2010)


class T9_setup_and_errors(Base):
    def test_futures_setup_idempotent(self):
        r = O.futures_setup(self.cf, 3)
        self.assertEqual(r["leverage"], 3); self.assertIn("margin type set to ISOLATED", r["events"])
        r2 = O.futures_setup(self.cf, 3); self.assertIn("margin type already ISOLATED", r2["events"])
        p = O.futures_position(self.cf); self.assertEqual((p["margin_type"], p["leverage"], p["qty"]), ("ISOLATED", 3, 0.0))
        self.assertEqual(O.futures_account(self.cf)["equity"], 5000.0)

    def test_exchange_error_propagates(self):
        self.fut.script = [{"error": (-1001, "Internal error; unable to process your request.")}]
        with self.assertRaises(X.ExchangeError) as cm: loop(self.cf, "BUY", 0.05, self.ff)
        self.assertEqual(cm.exception.code, -1001)

    def test_cancel_unknown_returns_final_state(self):
        self.fut.script = [{}, {"fill": 1.0}]
        r, _ = loop(self.cf, "BUY", 0.05, self.ff)
        o = O.cancel(self.cf, r["orders"][0]["order_id"]); self.assertEqual(o["status"], "FILLED")
        self.assertEqual(O.cancel_all(self.cf), [])


class T10_ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.old = L.BASE_DIR; L.BASE_DIR = self.tmp; L.set_dry_run(False)

    def tearDown(self): L.BASE_DIR = self.old; L.set_dry_run(False)

    def test_round_trip_and_fields(self):
        L.append("orders", strategy="A", venue="futures", event="placed", order_id=1, side="BUY", price=65000.0, qty=0.05, note="a, b")
        L.append("orders", strategy="A", venue="futures", event="filled", order_id=1, side="BUY", price=65000.0, qty=0.05, filled=0.05)
        rows = L.rows("orders"); self.assertEqual(len(rows), 2); self.assertEqual(rows[0]["note"], "a, b"); self.assertEqual(rows[1]["filled"], "0.05")
        self.assertEqual(L.last("orders", event="placed")["order_id"], "1"); self.assertIsNone(L.last("orders", event="nope"))
        df = L.read("orders"); self.assertEqual(list(df.columns), L.COLUMNS["orders"]); self.assertEqual(len(df), 2)
        self.assertEqual(len(L.read("fills")), 0)
        with self.assertRaises(KeyError): L.append("orders", strategy="A", prize=1)
        with self.assertRaises(KeyError): L.append("nope", x=1)

    def test_run_heartbeat_and_alert(self):
        with L.Run("b-check", day="2026-11-16") as run: run.note = "no change"
        try:
            with L.Run("a-enter"): raise RuntimeError("boom")
        except RuntimeError: pass
        runs = L.rows("runs"); self.assertEqual([r["status"] for r in runs], ["OK", "ERROR"]); self.assertEqual(runs[0]["day"], "2026-11-16")
        self.assertIn("boom", runs[1]["note"]); self.assertEqual(L.rows("alerts")[0]["command"], "a-enter")
        L.set_dry_run(True); L.append("alerts", level="INFO", command="x", message="dry")
        self.assertTrue((self.tmp / "dryrun" / "alerts.csv").exists()); self.assertEqual(len(L.rows("alerts")), 1)
        L.set_dry_run(False); self.assertEqual(len(L.rows("alerts")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
