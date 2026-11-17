"""
Offline tests for the A time guard in harness.py (added 17 Nov 2026 after a laptop woke at 21:13 and the scheduler
started a-precheck and a-enter late). A run that starts after midnight must never open the NEW day's A window.
No network: fake exchange on 127.0.0.1, the real-book lookup stubbed out, ledgers in a temp folder.
Run:  cd backend && PYTHONPATH=src python3 -m unittest tests/test_a_window_guard.py

 1. a_too_early: 20:49 is too early, 20:50 is not, --deadline-min (tests) is always allowed
 2. a-precheck at 00:30 UTC: refuses, writes no a_windows row (so the evening run still works), raises a WARN
 3. a-enter at 00:30 UTC: refuses before touching the exchange or the ledger
 4. a-exit at 00:30 UTC with a position left from yesterday: market close at once (no post-only order),
    booked to yesterday's window with yesterday's entry details, OVERDUE in the note
 5. a-exit at 00:30 UTC and flat: nothing done, nothing written
"""
import sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
sys.dont_write_bytecode = True
from btc_bot.trading import exchange as X, fakebinance as F, harness as H, ledger as L, orders as O


def args(**kw):
    return SimpleNamespace(**{"deadline_min": 0, "dry_run": False, "force": False, "poll": 0.01, **kw})


def run_ctx():
    return SimpleNamespace(day=None, status="OK", note="")


class GuardBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.old_base = L.BASE_DIR; L.BASE_DIR = self.tmp; L.set_dry_run(False)
        # 00:30 UTC yesterday: always in the past, so the exit's "close by now" deadline is already over
        self.now = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=0, minute=30, second=0, microsecond=0)
        self.day = self.now.strftime("%Y-%m-%d"); self.prev = (self.now - timedelta(days=1)).strftime("%Y-%m-%d")
        self.old_now, self.old_rb = H.utcnow, O.real_book
        H.utcnow = lambda: self.now
        O.real_book = lambda futures, symbol=O.SYMBOL: None

    def tearDown(self):
        H.utcnow, O.real_book = self.old_now, self.old_rb
        L.BASE_DIR = self.old_base; L.set_dry_run(False)

    def at_time(self, h, m): return self.now.replace(hour=h, minute=m)


class T1_helper(GuardBase):
    def test_boundaries(self):
        self.assertTrue(H.a_too_early("x", self.at_time(20, 49), args()))
        self.assertFalse(H.a_too_early("x", self.at_time(20, 50), args()))
        self.assertFalse(H.a_too_early("x", self.at_time(22, 54), args()))
        self.assertFalse(H.a_too_early("x", self.at_time(0, 30), args(deadline_min=1)))
        self.assertEqual(len(L.rows("alerts")), 1)          # only the refused call raised an alert


class T2_precheck(GuardBase):
    def test_refuses_after_midnight(self):
        run = run_ctx()
        rc = H.cmd_a_precheck(SimpleNamespace(dry=False), args(), run)
        self.assertEqual(rc, 1); self.assertEqual(run.note, "too early"); self.assertEqual(run.day, self.day)
        self.assertEqual(L.rows("a_windows"), [])
        al = L.rows("alerts"); self.assertEqual((al[-1]["command"], al[-1]["level"]), ("a-precheck", "WARN"))


class T3_enter(GuardBase):
    def test_refuses_before_touching_anything(self):
        run = run_ctx()
        rc = H.cmd_a_enter(None, args(), run)                 # v=None: any exchange call would raise
        self.assertEqual(rc, 1); self.assertEqual(run.status, "NO_TRADE")
        self.assertEqual(L.rows("a_windows"), []); self.assertEqual(L.rows("orders"), [])
        self.assertIn("before the 20:55-21:05 window", L.rows("alerts")[-1]["message"])


class ExitBase(GuardBase):
    def setUp(self):
        super().setUp()
        self.spot = F.Sim(futures=False, bid=65000.00, ask=65000.01, usdt=10000.0, btc=0.0)
        self.fut = F.Sim(futures=True, bid=65000.0, ask=65000.1, usdt=5000.0)
        self.srv, base = F.serve(self.spot, self.fut)
        cs = X.BinanceClient(base, "k", "s", futures=False); cf = X.BinanceClient(base, "k", "s", futures=True)
        self.v = SimpleNamespace(spot=cs, fut=cf, fs=O.load_filters(cs), ff=O.load_filters(cf), dry=False)

    def tearDown(self):
        self.srv.shutdown(); super().tearDown()


class T4_exit_overdue(ExitBase):
    def test_leftover_position_closed_at_market_and_booked_to_yesterday(self):
        L.append("a_windows", day=self.prev, status="ENTERED", allowed=True, target_qty=0.05, entry_filled=0.05,
                 entry_avg=64900.0, fees_usdt=0.649, n_orders=1, note="entry")
        self.fut.pos, self.fut.entry = 0.05, 64900.0
        run = run_ctx()
        rc = H.cmd_a_exit(self.v, args(), run)
        self.assertEqual(rc, 0); self.assertEqual(self.fut.pos, 0.0); self.assertEqual(run.day, self.prev)
        rows = L.rows("a_windows"); last = rows[-1]
        self.assertEqual([r["day"] for r in rows], [self.prev, self.prev])        # nothing booked to the new day
        self.assertEqual((last["status"], last["exit_type"]), ("CLOSED", "MARKET"))
        self.assertEqual(last["n_orders"], "2")                                   # entry order + one market order, no post-only
        self.assertEqual(float(last["entry_avg"]), 64900.0)                        # yesterday's entry details carried over
        self.assertIn("OVERDUE", last["note"])
        self.assertTrue(any("held past 23:00" in a["message"] for a in L.rows("alerts")))


class T5_exit_flat(ExitBase):
    def test_nothing_to_do(self):
        run = run_ctx()
        rc = H.cmd_a_exit(self.v, args(), run)
        self.assertEqual(rc, 0); self.assertEqual(run.note, "flat")
        self.assertEqual(L.rows("a_windows"), []); self.assertEqual(L.rows("orders"), [])


if __name__ == "__main__":
    unittest.main()
