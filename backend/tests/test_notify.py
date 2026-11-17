"""
Offline tests for reporting/notify.py (Telegram messages after each scheduled run, added 17 Nov 2026).
No network: the Telegram API is replaced by a recorder; ledgers in a temp folder.
Run:  cd backend && PYTHONPATH=src python3 -m unittest tests/test_notify.py

 1. settings: read from the secrets file, other keys ignored; store() keeps other lines and mode 600
 2. send: refuses without settings, retries once, cuts long text; the token never appears in an error
 3. problem message: none for a clean run; ERROR/WARN alerts listed; exit != 0 without alert shows the log tail
 4. trade messages: B switch, A entered, A unfilled, A closed; nothing for "no change", "flat" or an old row
 5. daily summary: all OK; missing run, open A day, kill switch and stale dashboard.json flagged; distance to signals
 6. after-run end to end: only this run's alerts, messages in order problem -> trade, exit 3 when Telegram fails
 7. the schedule matches the dashboard's
"""
import io, json, os, stat, sys, tempfile, unittest, urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
sys.dont_write_bytecode = True
from btc_bot.reporting import notify as N
from btc_bot.trading import ledger as L

S = {"TELEGRAM_BOT_TOKEN": "123456:SECRET-token-value", "TELEGRAM_CHAT_ID": "42"}


class Recorder:
    def __init__(self, fail=0):
        self.calls, self.fail = [], fail

    def __call__(self, token, method, params=None, timeout=15):
        self.calls.append((token, method, dict(params or {})))
        if self.fail > 0:
            self.fail -= 1; raise N.NotifyError("Telegram sendMessage: HTTP 502 Bad Gateway")
        return {"message_id": len(self.calls)}

    @property
    def texts(self): return [p["text"] for _, m, p in self.calls if m == "sendMessage"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.old_base = L.BASE_DIR; L.BASE_DIR = self.tmp; L.set_dry_run(False)

    def tearDown(self):
        L.BASE_DIR = self.old_base; L.set_dry_run(False)


class T1_settings(Base):
    def test_load_and_store(self):
        p = self.tmp / "secrets.env"
        p.write_text("B_SPOT_API_KEY=abc\n# comment\nTELEGRAM_BOT_TOKEN=old\n", encoding="utf-8")
        self.assertEqual(N.load_settings(p), {"TELEGRAM_BOT_TOKEN": "old"})
        N.store(p, {"TELEGRAM_BOT_TOKEN": "new", "TELEGRAM_CHAT_ID": "42"})
        lines = p.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, ["B_SPOT_API_KEY=abc", "# comment", "TELEGRAM_BOT_TOKEN=new", "TELEGRAM_CHAT_ID=42"])
        self.assertEqual(N.load_settings(p), {"TELEGRAM_BOT_TOKEN": "new", "TELEGRAM_CHAT_ID": "42"})
        if os.name == "posix": self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)


class T1b_parse_token(unittest.TestCase):
    def test_token_found_in_pastes(self):
        tok = "1234567890:AAF" + "x" * 32
        for raw in (tok, f"  {tok}\n", f"'{tok}'", f"bot{tok}", f"https://api.telegram.org/bot{tok}/getMe", f"1234567890: AAF{'x' * 32}"):
            self.assertEqual(N.parse_token(raw), tok, raw)
        for raw in ("", "@my_btc_bot", "https://t.me/my_btc_bot", "Done! Congratulations on your new bot."):
            self.assertIsNone(N.parse_token(raw), raw)


class T2_send(unittest.TestCase):
    def test_not_configured(self):
        with self.assertRaises(N.NotifyError): N.send("x", {}, Recorder())

    def test_retry_then_ok(self):
        rec = Recorder(fail=1)
        self.assertTrue(N.send("hello", S, rec, pause=0))
        self.assertEqual(len(rec.calls), 2); self.assertEqual(rec.calls[-1][2]["chat_id"], "42")

    def test_gives_up(self):
        with self.assertRaises(N.NotifyError): N.send("hello", S, Recorder(fail=5), tries=2, pause=0)

    def test_long_text_cut(self):
        rec = Recorder(); N.send("x" * 9000, S, rec, pause=0)
        self.assertLessEqual(len(rec.texts[0]), N.MAX_LEN); self.assertTrue(rec.texts[0].endswith("(cut)"))

    def test_token_not_in_errors(self):
        def boom(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"ok":false,"description":"Unauthorized"}'))
        with mock.patch("urllib.request.urlopen", boom):
            with self.assertRaises(N.NotifyError) as cm: N._api(S["TELEGRAM_BOT_TOKEN"], "getMe")
        self.assertIn("401", str(cm.exception)); self.assertNotIn("SECRET", str(cm.exception))
        def down(req, timeout=0): raise urllib.error.URLError("Name or service not known")
        with mock.patch("urllib.request.urlopen", down):
            with self.assertRaises(N.NotifyError) as cm: N._api(S["TELEGRAM_BOT_TOKEN"], "sendMessage", {"text": "x"})
        self.assertNotIn("SECRET", str(cm.exception))


class T3_problem(unittest.TestCase):
    def test_clean_run(self):
        self.assertIsNone(N.problem_message("a-exit", 0, [{"level": "INFO", "message": "fine"}]))

    def test_alerts_listed(self):
        m = N.problem_message("a-exit", 1, [{"ts_utc": "2026-11-20T22:59:58Z", "level": "ERROR", "command": "a-exit",
                                             "message": "POSITION STILL OPEN after exit: 0.05 BTC"}])
        self.assertIn("a-exit (exit 1)", m); self.assertIn("22:59 UTC: POSITION STILL OPEN", m); self.assertNotIn("Last log lines", m)

    def test_crash_without_alert_shows_log(self):
        m = N.problem_message("b-check", 137, [], ["Killed", "===== end b-check exit 137"])
        self.assertIn("no alert", m); self.assertIn("Killed", m)


class T4_trade(unittest.TestCase):
    B = dict(status="SWITCHED", held_before="CASH", target="LONG", action="BUY", qty="0.1", avg_price="80000",
             fee_usdt="8", slip_real_bp="0.5", close_prev="80100", sma50="79000", equity_usdt="8300")
    A_IN = dict(status="ENTERED", entry_filled="0.077", target_qty="0.077", fill_rate="1", entry_avg="65000",
                price_2055="65100", sma200="64000", entry_slip_real_bp="-0.4", fees_usdt="0")
    A_OUT = dict(A_IN, status="CLOSED", exit_avg="65200", exit_type="MAKER", pnl_usdt="15.4", pnl_bp="30.8", funding_usdt="0",
                 exit_slip_real_bp="0.2")

    def test_b_switch(self):
        m = N.trade_message("b-check", {"note": "switched CASH->LONG @ 80,000.00"}, b_row=self.B)
        self.assertIn("B switched: CASH -> LONG (close 80,100 > SMA50 79,000)", m); self.assertIn("BUY 0.10000 BTC @ 80,000.00", m)

    def test_b_no_change(self):
        self.assertIsNone(N.trade_message("b-check", {"note": "no change (CASH)"}, b_row=dict(self.B, status="NO_CHANGE", action="none")))

    def test_a_entered_and_unfilled(self):
        m = N.trade_message("a-enter", {"note": "ENTERED 0.077/0.077 @ 65,000.00"}, a_row=self.A_IN)
        self.assertIn("A entered", m); self.assertIn("fill 100%", m)
        m = N.trade_message("a-enter", {"note": "UNFILLED 0/0.077 @ 0.00"}, a_row=dict(self.A_IN, status="UNFILLED"))
        self.assertIn("not filled", m)
        self.assertIsNone(N.trade_message("a-enter", {"note": "SKIPPED_FILTER"}, a_row=dict(self.A_IN, status="SKIPPED_FILTER")))

    def test_a_closed(self):
        m = N.trade_message("a-exit", {"note": "closed MAKER pnl +15.40"}, a_row=self.A_OUT, equity_row={"equity_usdt": "5015.4"})
        self.assertIn("A closed: SELL @ 65,200.00 (MAKER) | P&L +15.40 USDT (+30.8 bp)", m); self.assertIn("Equity 5,015.40", m)
        # a later a-exit the same evening finds the day CLOSED but was itself flat: no second message
        self.assertIsNone(N.trade_message("a-exit", {"note": "flat"}, a_row=self.A_OUT))
        self.assertIsNone(N.trade_message("a-exit", None, a_row=self.A_OUT))


class T5_daily(unittest.TestCase):
    NOW = datetime(2026, 11, 20, 23, 10, 30, tzinfo=timezone.utc)
    DASH = {"generated_utc": "2026-11-20T23:10:20+00:00", "paper_days": 5, "ops": {"missed": 0},
            "kill": [{"trigger": "A: fill rate < 80%", "status": "na", "reading": "no entries"}]}
    B = {"status": "NO_CHANGE", "target": "CASH", "close_prev": "64883", "sma50": "79452"}
    A = {"status": "SKIPPED_FILTER", "price_2055": "66000", "sma200": "72921"}

    def runs(self, skip=()):
        return [{"command": c, "day": "2026-11-20", "status": "OK"} for c in N.SCHEDULED if c not in skip]

    def test_all_ok(self):
        m = N.daily_message(self.NOW, self.runs(), [], self.B, self.A, {"equity_usdt": "8264.72"}, {"equity_usdt": "5000"}, self.DASH)
        first = m.splitlines()[0]
        self.assertIn("all OK", first); self.assertIn("paper day 5", first); self.assertNotIn("Problems", m)
        self.assertIn("B: CASH, no change (close 64,883 < SMA50 79,452)", m)
        self.assertIn("A: off tonight (20:55 price 66,000 < SMA200 72,921)", m)
        self.assertIn("B 8,264.72 + A 5,000.00 = 13,264.72 USDT", m)
        self.assertIn("A needs +10.5%", m); self.assertIn("B needs +22.5%", m)
        self.assertIn("Kill switches: none hit", m)

    def test_problems_flagged(self):
        kill = dict(self.DASH, kill=[{"trigger": "A: fill rate < 80%", "status": "bad", "reading": "60% over 25 day(s)"}])
        alerts = [{"ts_utc": "2026-11-20T22:59:00Z", "level": "ERROR", "command": "a-exit", "message": "POSITION STILL OPEN"},
                  {"ts_utc": "2026-11-19T22:59:00Z", "level": "ERROR", "command": "a-exit", "message": "yesterday's"}]
        m = N.daily_message(self.NOW, self.runs(skip=("a-precheck",)), alerts, self.B, dict(self.A, status="ENTERED"), None, None, kill)
        self.assertIn("problem(s)", m.splitlines()[0])
        for part in ("a-precheck MISSING", "entered, no a-exit", "1 ERROR/WARN", "kill switch hit", "[bad] A: fill rate"):
            self.assertIn(part, m)
        self.assertNotIn("yesterday's", m)

    def test_stale_or_missing_dashboard(self):
        old = dict(self.DASH, generated_utc="2026-11-19T23:10:20+00:00")
        self.assertIn("not refreshed", N.daily_message(self.NOW, self.runs(), [], self.B, self.A, None, None, old))
        self.assertIn("dashboard.json missing", N.daily_message(self.NOW, self.runs(), [], self.B, self.A, None, None, None))

    def test_pending_is_not_missing(self):
        m = N.daily_message(self.NOW.replace(hour=20, minute=0), self.runs(skip=("a-precheck", "a-enter", "a-exit", "dashboard")),
                            [], self.B, None, None, None, None)
        self.assertIn("a-precheck pending", m); self.assertNotIn("a-precheck MISSING", m)


class T6_after_run(Base):
    def test_end_to_end(self):
        L.append("alerts", ts_utc="2026-11-20T21:00:00Z", level="ERROR", command="a-enter", message="old alert, before this run")
        since = "2026-11-20T22:54:01Z"
        L.append("a_windows", **T4_trade.A_IN, day="2026-11-20")
        L.append("a_windows", **T4_trade.A_OUT, day="2026-11-20")
        L.append("equity", ts_utc="2026-11-20T22:59:59Z", day="2026-11-20", strategy="A", equity_usdt=5015.4)
        L.append("alerts", ts_utc="2026-11-20T22:59:58Z", level="WARN", command="a-exit", message="exit started late")
        L.append("runs", ts_utc="2026-11-20T23:00:00Z", day="2026-11-20", command="a-exit", status="OK", note="closed MAKER pnl +15.40")
        rec = Recorder()
        rc = N.after_run("a-exit", 0, since, now=datetime(2026, 11, 20, 23, 0, 5, tzinfo=timezone.utc), settings=S, api=rec)
        self.assertEqual(rc, 0); self.assertEqual(len(rec.texts), 2)
        self.assertIn("warning: a-exit", rec.texts[0]); self.assertIn("exit started late", rec.texts[0]); self.assertNotIn("old alert", rec.texts[0])
        self.assertIn("A closed", rec.texts[1])

    def test_quiet_run_sends_nothing(self):
        L.append("runs", ts_utc="2026-11-20T20:55:05Z", day="2026-11-20", command="a-precheck", status="OK", note="SKIPPED_FILTER")
        rec = Recorder()
        self.assertEqual(N.after_run("a-precheck", 0, "2026-11-20T20:55:00Z", settings=S, api=rec), 0)
        self.assertEqual(rec.calls, [])

    def test_crash_and_telegram_down(self):
        logs = self.tmp / "logs"; logs.mkdir()
        (logs / "b-check.log").write_text(" Container x Creating\nTraceback...\nMemoryError\n===== end b-check exit 137\n", encoding="utf-8")
        msgs = N.build_after_run("b-check", 137, "2026-11-20T00:01:00Z")
        self.assertEqual(len(msgs), 1); self.assertIn("MemoryError", msgs[0]); self.assertNotIn("Container", msgs[0])
        with mock.patch.object(N.time, "sleep"):
            self.assertEqual(N.after_run("b-check", 137, "2026-11-20T00:01:00Z", settings=S, api=Recorder(fail=9)), 3)

    def test_daily_reads_dashboard_json(self):
        (self.tmp / "dashboard.json").write_text(json.dumps(T5_daily.DASH), encoding="utf-8")
        for c in N.SCHEDULED: L.append("runs", ts_utc="2026-11-20T23:10:25Z", day="2026-11-20", command=c, status="OK")
        L.append("b_days", **T5_daily.B, day="2026-11-20"); L.append("a_windows", **T5_daily.A, day="2026-11-20")
        msgs = N.build_after_run("dashboard", 0, "2026-11-20T23:10:00Z", now=T5_daily.NOW)
        self.assertEqual(len(msgs), 1); self.assertIn("all OK", msgs[0].splitlines()[0])


class T7_schedule(unittest.TestCase):
    def test_same_as_dashboard(self):
        from btc_bot.reporting import dashboard as D
        self.assertEqual(N.SCHEDULED, D.RUN_TIMES); self.assertEqual(N.GRACE_MIN, D.GRACE_MIN)


if __name__ == "__main__":
    unittest.main()
