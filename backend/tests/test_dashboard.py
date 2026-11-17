"""
Offline tests for dashboard.py. Logs are written to a temp folder (ledger.BASE_DIR); data/paper is never touched.
Reads data/btc_1h.csv for the expected curves and the signal checks. Run:  python3 -m unittest tests/test_dashboard.py

 1. Empty logs: compute() and the HTML work; every kill switch reads "no data yet"; nothing counted as missed
 2. Synthetic ten-day paper run (18-27 Oct 2026): fill rate, slippage (real vs demo), avg bp, win rate, exit types,
    quarters, rolling 90 days, missed-run grid (a day with the machine off; today's not-yet-due runs are "pending"),
    "last row per day wins", the 00:01 snapshot counts as the previous day, combined curve = B return + A return
 3. Signal checks: a deliberately wrong B target and a wrong A decision are caught and flagged as TRIGGERED
 4. HTML has every section and is written atomically; dry-run reads its own folder
 5. JSON payload (for frontend/) is JSON-safe (no NaN), carries every section, round-trips through a file
"""
import io, json, sys, tempfile, unittest, contextlib
from pathlib import Path
import numpy as np, pandas as pd
sys.dont_write_bytecode = True
from btc_bot.data.feed import load_hourly, daily_closes
from btc_bot.reporting import dashboard as D
from btc_bot.strategy import signals as S
from btc_bot.trading import ledger as L

H = load_hourly()
DC = daily_closes(H)
NOW = pd.Timestamp("2026-10-27 22:00", tz="UTC")
DAYS = [f"2026-10-{d}" for d in range(18, 28)]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); L.BASE_DIR = Path(self.tmp.name); L.set_dry_run(False)

    def tearDown(self): self.tmp.cleanup()

    def compute(self, **kw): return D.compute(now=NOW, hourly=H, **kw)


class T1_empty(Base):
    def test_empty_logs(self):
        r = self.compute()
        self.assertEqual(r["B"]["days"], 0); self.assertEqual(r["A"]["days"], 0); self.assertIsNone(r["C"]["sum"])
        self.assertTrue(all(s == "na" for *_, s in r["kill"])); self.assertEqual(r["ops"]["missed"], 0)
        self.assertTrue(r["signal"]["ok"]); self.assertIsNone(r["paper_start"])
        out = D.write_html(r); txt = out.read_text(encoding="utf-8")
        for sec in ("1. Signal state", "2. Strategy B", "3. Strategy A", "4. Combined", "5. Kill switches", "6. Operations"): self.assertIn(sec, txt)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): D.print_summary(r)
        self.assertIn("Kill switches", buf.getvalue())
        self.assertTrue(r["A"]["sim_quarters"], "simulated holdout quarters should exist even with no paper data")


def write_synthetic(wrong_b_day=None, wrong_a_day=None):
    """Ten days of plausible logs. B's targets come from signals.py (so they agree) except `wrong_b_day`."""
    prev = "LONG"; sw = 0
    for d in DAYS:
        sig = S.b_signal(DC, d); tgt = "LONG" if sig["target"] else "CASH"
        logged = tgt if d != wrong_b_day else ("CASH" if tgt == "LONG" else "LONG")
        switched = tgt != prev
        if switched: sw += 1
        L.append("b_days", day=d, status="SWITCHED" if switched else "NO_CHANGE", close_prev=sig["close"], sma50=sig["sma50"], target=logged,
                 held_before=prev, action=("BUY" if tgt == "LONG" else "SELL") if switched else "none", qty=0.1 if switched else None,
                 avg_price=100000.0 if switched else None, fee_usdt=10.0 if switched else None, slip_real_bp=-0.5 if switched else None,
                 slip_demo_bp=1.5 if switched else None, equity_usdt=10000.0, btc=0, usdt=10000.0, delay_min=0.3)
        prev = tgt
        L.append("equity", ts_utc=f"{d}T00:01:30Z", day=d, strategy="B", equity_usdt=10000.0 + 10 * (DAYS.index(d)), btc=0, usdt=10000.0, price=100000.0, note="b-check")
    # A: status per day; price set just above / below SMA200 so the logged decision is right unless `wrong_a_day`
    spec = {"2026-10-18": ("CLOSED", 1.0, 4.6, "MAKER"), "2026-10-19": ("CLOSED", 0.5, -3.0, "MIXED"), "2026-10-20": ("SKIPPED_FILTER",),
            "2026-10-21": ("UNFILLED", 0.0), "2026-10-22": ("MISSED_MACHINE_OFF",), "2026-10-23": ("CLOSED", 1.0, 10.0, "MARKET"),
            "2026-10-24": ("ERROR",), "2026-10-25": ("CLOSED", 1.0, 2.0, "MAKER"), "2026-10-26": ("SKIPPED_FILTER",), "2026-10-27": ("ENTERED", 1.0)}
    eqA = 5000.0
    L.append("equity", ts_utc="2026-10-17T20:55:10Z", day="2026-10-17", strategy="A", equity_usdt=eqA, btc=0, usdt=eqA, note="a-precheck")
    for d, s in spec.items():
        sma = S.a_signal(DC, 1.0, d)["sma200"]; allowed = s[0] not in ("SKIPPED_FILTER",)
        if d == wrong_a_day: allowed = not allowed
        price = sma * (1.001 if s[0] not in ("SKIPPED_FILTER",) else 0.999)
        if s[0] == "MISSED_MACHINE_OFF": L.append("a_windows", day=d, status=s[0], note="machine off"); continue
        if s[0] == "ERROR": L.append("a_windows", day=d, status=s[0], allowed=False, note="signal not ok"); continue
        L.append("a_windows", day=d, status="ALLOWED" if allowed else "SKIPPED_FILTER", allowed=allowed, price_2055=price, sma200=sma, equity_start=eqA)
        if s[0] == "SKIPPED_FILTER": continue
        fill = s[1]; pnl_bp = s[2] if len(s) > 2 else None
        if s[0] == "UNFILLED":
            L.append("a_windows", day=d, status="UNFILLED", allowed=allowed, price_2055=price, sma200=sma, equity_start=eqA, target_qty=0.05, entry_filled=0, fill_rate=0.0, n_orders=3); continue
        L.append("a_windows", day=d, status="ENTERED", allowed=allowed, price_2055=price, sma200=sma, equity_start=eqA, target_qty=0.05, entry_filled=0.05 * fill,
                 fill_rate=fill, entry_avg=100000.0, entry_slip_real_bp=0.5, entry_slip_demo_bp=1.0, fees_usdt=0.2, n_orders=1)
        if s[0] == "ENTERED": continue
        pnl = pnl_bp / 1e4 * 0.05 * fill * 100000.0; eqA += pnl
        L.append("a_windows", day=d, status="CLOSED", allowed=allowed, price_2055=price, sma200=sma, equity_start=eqA - pnl, target_qty=0.05, entry_filled=0.05 * fill,
                 fill_rate=fill, entry_avg=100000.0, entry_slip_real_bp=0.5, entry_slip_demo_bp=1.0, exit_avg=100000.0 * (1 + pnl_bp / 1e4), exit_type=s[3],
                 exit_slip_real_bp=0.3, exit_slip_demo_bp=0.8, fees_usdt=0.4, funding_usdt=0.0, pnl_usdt=pnl, pnl_bp=pnl_bp, n_orders=2)
        L.append("equity", ts_utc=f"{d}T23:00:05Z", day=d, strategy="A", equity_usdt=eqA, btc=0, usdt=eqA, note="after exit")
    # runs: a manual run the day before, then every command daily except 22 Oct (machine off); today a-exit hasn't happened yet
    L.append("runs", ts_utc="2026-10-17T20:55:12Z", day="2026-10-17", command="a-precheck", status="OK", duration_s=3, note="manual")
    for d in DAYS:
        if d == "2026-10-22": continue
        cmds = ["b-check", "a-precheck", "a-enter", "a-exit", "dashboard"] if d != "2026-10-27" else ["b-check", "a-precheck", "a-enter"]
        for cmd in cmds:
            hh, mm = D.RUN_TIMES[cmd]
            L.append("runs", ts_utc=f"{d}T{hh:02d}:{mm:02d}:40Z", day=d, command=cmd, status="ERROR" if (d, cmd) == ("2026-10-24", "a-precheck") else "OK", duration_s=5, note="")
    L.append("alerts", ts_utc="2026-10-24T20:55:50Z", level="ERROR", command="a-precheck", message="signal not ok: test")
    L.append("alerts", ts_utc="2026-10-10T00:01:50Z", level="WARN", command="b-check", message="old warning outside the 7-day window")
    return sw


class T2_synthetic(Base):
    def test_numbers(self):
        sw = write_synthetic(); r = self.compute(); a, b, c, ops = r["A"], r["B"], r["C"], r["ops"]
        # B
        self.assertEqual(b["days"], 10); self.assertEqual(b["switches"], sw); self.assertEqual(b["mismatches"], [])
        self.assertEqual(len(b["checks"]), 10); self.assertEqual(b["fees"], 10.0 * sw)
        self.assertAlmostEqual(b["span"]["paper"], 10090 / 10000 - 1, places=9)
        self.assertEqual(b["span"]["start"], pd.Timestamp("2026-10-17", tz="UTC"), "00:01 snapshot belongs to the previous day")
        self.assertEqual(b["span"]["days"], 9); self.assertIsNotNone(b["span"]["expected"])
        # A
        self.assertEqual(a["days"], 10); self.assertEqual(a["attempted"], 6); self.assertEqual(a["closed"], 4)
        self.assertAlmostEqual(a["fill_rate"], (1 + 0.5 + 0 + 1 + 1 + 1) / 6); self.assertEqual(a["filled_days"], 5)
        self.assertAlmostEqual(a["avg_bp"], (4.6 - 3 + 10 + 2) / 4); self.assertAlmostEqual(a["win_rate"], 0.75)
        self.assertAlmostEqual(a["slip_real"], 0.4); self.assertAlmostEqual(a["slip_demo"], 0.9)
        self.assertEqual(a["exit_types"], {"MAKER": 2, "MIXED": 1, "MARKET": 1}); self.assertEqual(a["market_exits"], 2)
        self.assertEqual((a["missed"], a["errors"], a["unfilled"], a["still_open"]), (1, 1, 1, 0))
        self.assertEqual(a["allowed"], 6)                       # 18,19,21,23,25,27 (22 has no decision, 24 ERROR = False)
        self.assertEqual(len(a["quarters"]), 1); self.assertEqual(a["quarters"][0]["q"], "2026Q4"); self.assertFalse(a["quarters"][0]["done"])
        self.assertEqual(a["roll90_n"], 4); self.assertEqual(len(a["trades"]), 4)
        self.assertEqual(a["mismatches"], []); self.assertEqual(len(a["checks"]), 8)   # 18,19,20,21,23,25,26,27 (ERROR and MISSED skipped)
        self.assertEqual(a["recent_rows"].loc["2026-10-18", "status"], "CLOSED", "last row per day wins")
        self.assertAlmostEqual(a["pnl_usdt"], sum(bp_ / 1e4 * 0.05 * f * 100000 for bp_, f in ((4.6, 1), (-3, .5), (10, 1), (2, 1))))
        # combined = B return + A return per day
        self.assertAlmostEqual(c["span"]["paper"], np.exp(np.log(10090 / 10000) + np.log(a["equity"] / 5000)) - 1, places=9)
        self.assertIsNotNone(c["span"]["expected"]); self.assertIsNotNone(c["bh"])
        # kill switches
        ks = {t[:12]: s for t, _, _, s in r["kill"]}
        self.assertEqual(ks["A: 90-day av"], "ok"); self.assertEqual(ks["A: limit-ord"], "warn")     # 75% but only 6 attempts
        self.assertEqual(ks["A: average s"], "ok"); self.assertEqual(ks["A: realised "], "ok")
        self.assertEqual(ks["B: more than"], "na"); self.assertEqual(ks["B: drawdown "], "ok"); self.assertEqual(ks["Either: logg"], "ok")
        # operations grid
        self.assertEqual(ops["first_day"], pd.Timestamp("2026-10-17", tz="UTC"))
        g = dict(ops["grid"]); cells = lambda d: [s for s, _ in g[d]]
        self.assertEqual(cells("2026-10-22"), ["MISSING"] * 5); self.assertEqual(ops["missed"], 5)
        self.assertEqual(cells("2026-10-27"), ["OK", "OK", "OK", "pending", "now"])
        self.assertEqual(cells("2026-10-17"), ["-", "OK", "-", "-", "-"]); self.assertEqual(cells("2026-10-24")[1], "ERROR")
        self.assertEqual(ops["alerts_7d"], {"ERROR": 1}); self.assertEqual(ops["errors_7d"], 1)
        self.assertEqual(r["paper_start"], pd.Timestamp("2026-10-17", tz="UTC")); self.assertEqual(r["paper_days"], 11)

    def test_wrong_signals_are_caught(self):
        write_synthetic(wrong_b_day="2026-10-25", wrong_a_day="2026-10-23"); r = self.compute()
        self.assertEqual([m[0] for m in r["B"]["mismatches"]], ["2026-10-25"]); self.assertEqual([m[0] for m in r["A"]["mismatches"]], ["2026-10-23"])
        self.assertEqual([s for t, _, _, s in r["kill"] if t.startswith("Either")], ["bad"])
        txt = D.render_html(r); self.assertIn("TRIGGERED", txt); self.assertIn("signals.py says", txt)

    def test_html_and_dry_run_folder(self):
        write_synthetic(); r = self.compute(); out = D.write_html(r)
        self.assertEqual(out, L.BASE_DIR / "dashboard.html"); self.assertFalse(out.with_suffix(".html.tmp").exists())
        txt = out.read_text(encoding="utf-8")
        self.assertIn("<svg", txt); self.assertIn("2026-10-22", txt); self.assertIn("MISSING", txt); self.assertIn("MARKET", txt)
        self.assertIn("B paper", txt); self.assertIn("A expected (same days)", txt); self.assertIn("buy &amp; hold", txt)
        L.set_dry_run(True)
        try:
            r2 = self.compute(); self.assertEqual(r2["B"]["days"], 0); self.assertEqual(D.write_html(r2), L.BASE_DIR / "dryrun" / "dashboard.html")
        finally:
            L.set_dry_run(False)

    def test_main_writes_heartbeat(self):
        write_synthetic(); buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = D.main(["--now", "2026-10-27 22:00", "--days", "7"])
        self.assertEqual(rc, 0); self.assertIn("written:", buf.getvalue())
        self.assertEqual(L.rows("runs")[-1]["command"], "dashboard"); self.assertEqual(L.rows("runs")[-1]["status"], "OK")


class T3_helpers(unittest.TestCase):
    def test_daily_equity_attribution(self):
        eq = pd.DataFrame({"ts_utc": ["2026-11-16T21:47:19Z", "2026-11-17T00:01:30Z", "2026-11-17T20:55:00Z", "2026-11-17T00:29:00Z"],
                           "strategy": ["B", "B", "B", "A"], "equity_usdt": [1.0, 2.0, 3.0, 9.0]})
        s = D.daily_equity(eq, "B")
        self.assertEqual(list(s.index), [pd.Timestamp("2026-11-16", tz="UTC"), pd.Timestamp("2026-11-17", tz="UTC")]); self.assertEqual(list(s), [2.0, 3.0])
        self.assertEqual(list(D.daily_equity(eq, "A").index), [pd.Timestamp("2026-11-16", tz="UTC")])
        self.assertTrue(D.daily_equity(eq, "C").empty)

    def test_chart_and_quarters(self):
        self.assertIn("no equity history", D.line_chart([dict(name="x", pts=[], color="#000")], "t"))
        one = D.line_chart([dict(name="x", pts=[(pd.Timestamp("2026-11-16", tz="UTC"), 1.0)], color="#000")], "t"); self.assertIn("<circle", one)
        two = D.line_chart([dict(name="x", pts=[(pd.Timestamp("2026-11-16", tz="UTC"), 1.0), (pd.Timestamp("2026-11-20", tz="UTC"), 1.02)], color="#000", dash=True)], "t")
        self.assertIn("<polyline", two); self.assertIn("stroke-dasharray", two)
        self.assertEqual(D.quarter("2026-11-16"), "2026Q4")
        qe = D.quarter_end("2026Q3")                                # pandas 2 ends at ns, pandas 3 at us precision
        self.assertTrue(pd.Timestamp("2026-09-30 23:59:59", tz="UTC") <= qe < pd.Timestamp("2026-10-01", tz="UTC"), qe)
        self.assertEqual(D.nice_step(0.01), 0.002); self.assertEqual(D.nice_step(1.0), 0.2)

    def test_combined_equity(self):
        i = pd.DatetimeIndex([pd.Timestamp("2026-10-17", tz="UTC"), pd.Timestamp("2026-10-18", tz="UTC"), pd.Timestamp("2026-10-19", tz="UTC")])
        sB = pd.Series([100.0, 110.0, 110.0], index=i); sA = pd.Series([50.0, 55.0], index=i[1:])
        c = D.combined_equity(sB, sA)
        self.assertAlmostEqual(c.iloc[-1], 1.1 * 1.1); self.assertEqual(len(c), 3); self.assertAlmostEqual(c.iloc[0], 1.0)


class T4_json(Base):
    def test_payload_is_json_safe_and_complete(self):
        sw = write_synthetic(); r = self.compute(); p = D.payload(r)
        back = json.loads(json.dumps(p, allow_nan=False))          # allow_nan=False raises on any NaN / Inf left behind
        for k in ("schema", "generated_utc", "signal", "B", "A", "C", "kill", "ops", "thresholds", "paper_start", "paper_days"): self.assertIn(k, back)
        self.assertEqual(back["schema"], 1); self.assertEqual(back["paper_days"], 11); self.assertEqual(back["paper_start"][:10], "2026-10-17")
        self.assertEqual(back["A"]["closed"], 4); self.assertEqual(len(back["A"]["trades"]), 4); self.assertAlmostEqual(back["A"]["fill_rate"], 0.75)
        self.assertEqual(back["A"]["exit_types"], {"MAKER": 2, "MIXED": 1, "MARKET": 1}); self.assertEqual(len(back["A"]["recent_rows"]), 10)
        self.assertEqual(back["A"]["recent_rows"][0]["day"], "2026-10-18"); self.assertEqual(back["A"]["recent_rows"][0]["status"], "CLOSED")
        self.assertEqual(len(back["kill"]), 7); self.assertEqual({k["status"] for k in back["kill"]} - {"ok", "warn", "bad", "na"}, set())
        self.assertEqual(back["ops"]["missed"], 5); self.assertEqual(back["ops"]["grid"][-1]["cells"][4]["status"], "now")
        self.assertEqual(back["ops"]["cmds"], ["b-check", "a-precheck", "a-enter", "a-exit", "dashboard"]); self.assertEqual(back["ops"]["alerts_7d"], {"ERROR": 1})
        self.assertEqual(back["B"]["switches"], sw); self.assertEqual(len(back["B"]["switch_rows"]), sw)
        if sw: self.assertEqual(back["B"]["switch_rows"][0]["day"][:4], "2026")
        self.assertEqual(len(back["C"]["curve"]["paper"]), len(r["C"]["span"]["paper_pts"])); self.assertTrue(back["C"]["curve"]["bh"])
        self.assertIsInstance(back["C"]["curve"]["paper"][0][0], str); self.assertIsInstance(back["C"]["curve"]["paper"][0][1], float)
        self.assertEqual(back["thresholds"]["fill_min"], 0.8); self.assertIn(back["signal"]["b"], ("LONG", "CASH"))
        out = D.write_json(r); self.assertEqual(out, L.BASE_DIR / "dashboard.json"); self.assertFalse(out.with_suffix(".json.tmp").exists())
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["A"]["avg_bp"], back["A"]["avg_bp"])

    def test_empty_payload(self):
        back = json.loads(json.dumps(D.payload(self.compute()), allow_nan=False))
        self.assertIsNone(back["C"]["sum"]); self.assertEqual(back["A"]["trades"], []); self.assertEqual(back["ops"]["grid"], [])
        self.assertIsNone(back["paper_start"]); self.assertEqual(back["B"]["switch_rows"], []); self.assertTrue(back["A"]["sim_quarters"])

    def test_clean(self):
        v = D.clean({"a": np.float64("nan"), "b": np.int64(3), "c": pd.Timestamp("2026-11-16", tz="UTC"), "d": (np.bool_(True), float("inf")), "e": pd.NaT,
                     "f": pd.DataFrame({"x": [1.0, float("nan")]}, index=pd.Index(["r1", "r2"], name="day"))})
        self.assertEqual(v, {"a": None, "b": 3, "c": "2026-11-16T00:00:00+00:00", "d": [True, None], "e": None, "f": [{"day": "r1", "x": 1.0}, {"day": "r2", "x": None}]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
