"""
Tests for signals.py (step 3). Reads data/btc_1h.csv and data/btc_1d.csv, writes nothing.
Run:  python3 -m unittest tests/test_signals.py      (should end with OK)

 1. b_targets() == backtest.py's original `pos` for every day, and == a plain-Python loop
 2. a_allowed_series() == the corrected live-feasible filter (plain-Python loop) for every day;
    the days where it differs from the original look-ahead filter are exactly the 11 known ones
 3. hand-checked crossing days (values cross-checked against data/btc_1d.csv)
 4. current_state() as of 16 Nov 2026 02:40 UTC gives B CASH / A OFF with the known numbers
 5. no look-ahead: signals from data truncated at D-1 23:59 (B) / D 20:59 (A) equal the full-data signals,
    and scrambling every candle after a cutoff changes no signal up to the cutoff
    (the original filter FAILS this test, which shows the test can catch look-ahead)
 6. edge cases: too few closes, exact equality, stale data, missing 23:00 candle, bad price, `now` cut-off
"""
import sys, unittest
from pathlib import Path
import numpy as np, pandas as pd

sys.dont_write_bytecode = True
from btc_bot.config import DATA_DIR
from btc_bot.strategy import signals as S

H = S.load_hourly(DATA_DIR / "btc_1h.csv")
DC = S.daily_closes(H)
RESEARCH_END = "2026-07-31"
T = lambda s: pd.Timestamp(s, tz="UTC")
# days where the corrected A filter differs from the original look-ahead one (found 16 Nov 2026, STRATEGY_RULES.md section 5)
KNOWN_DIFF_DAYS = ["2021-09-08", "2021-09-12", "2021-12-28", "2023-01-13", "2023-08-17", "2024-07-13",
                   "2024-08-26", "2024-09-30", "2025-03-12", "2025-03-20", "2026-08-19"]


def synthetic_hourly(daily_prices, start="2025-01-01"):
    """24 identical candles per day at the given daily price (for edge-case tests)."""
    idx = pd.DatetimeIndex(T(start) + pd.to_timedelta(np.arange(24 * len(daily_prices)), unit="h"))
    px = np.repeat(np.asarray(daily_prices, dtype=float), 24)
    return pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "volume": 1.0}, index=idx)


class T1_B_matches_backtest(unittest.TestCase):
    def test_equals_backtest_pos(self):
        ma50 = DC.rolling(50).mean()
        pos = (DC > ma50).astype(int).shift(1)                 # verbatim from backtest.py (original)
        got = S.b_targets(DC)
        self.assertTrue(np.isnan(pos.iloc[0])); self.assertEqual(got.iloc[0], 0)
        pd.testing.assert_series_equal(got.iloc[1:], pos.iloc[1:].astype(int), check_names=False)

    def test_equals_plain_loop(self):
        c = DC.tolist(); got = S.b_targets(DC).tolist()
        ref = [0] + [int(i - 1 >= 49 and c[i - 1] > sum(c[i - 50:i]) / 50) for i in range(1, len(c))]
        bad = [DC.index[i].date() for i in range(len(c)) if got[i] != ref[i]]
        self.assertEqual(bad, [])


class T2_A_corrected_filter(unittest.TestCase):
    def test_equals_plain_loop(self):
        p20 = {t.normalize(): v for t, v in H.close[H.index.hour == 20].items()}
        c = DC.tolist(); got = S.a_allowed_series(H).tolist()
        ref = [bool(i >= 200 and DC.index[i] in p20 and p20[DC.index[i]] > sum(c[i - 200:i]) / 200) for i in range(len(c))]
        bad = [DC.index[i].date() for i in range(len(c)) if got[i] != ref[i]]
        self.assertEqual(bad, [])

    def test_differences_from_original(self):
        new, old = S.a_allowed_series(H), S.a_allowed_series_original(H)
        diff = (new != old)[:"2026-11-15"]
        days = [str(d.date()) for d in diff[diff].index]
        print(f"\n  corrected vs original A filter differ on {len(days)} of {int(S.sma(DC, 200).shift(1)[:'2026-11-15'].notna().sum())} days:")
        for d in days:
            print(f"    {d}: original {'ON ' if old[d] else 'OFF'} -> corrected {'ON' if new[d] else 'OFF'}")
        self.assertEqual(days, KNOWN_DIFF_DAYS)
        self.assertEqual(int(diff[:RESEARCH_END].sum()), 10)


class T3_hand_checked(unittest.TestCase):
    D1 = pd.read_csv(DATA_DIR / "btc_1d.csv", index_col=0, parse_dates=True).close   # built by datafeed, separate path

    def indep(self, day, n):
        past = self.D1[self.D1.index < T(day)]
        return float(past.iloc[-1]), float(np.mean(past.iloc[-n:].values))

    def check_b(self, day, close, sma50, target):
        b = S.b_signal(DC, day)
        self.assertAlmostEqual(b["close"], close, places=2); self.assertAlmostEqual(b["sma50"], sma50, places=2)
        self.assertEqual(b["target"], target); self.assertEqual(S.b_targets(DC)[day], target)
        c, m = self.indep(day, 50); self.assertAlmostEqual(c, close, places=2); self.assertAlmostEqual(m, sma50, places=2)

    def check_a(self, day, price, sma200, allowed):
        a = S.a_signal(DC, price, day)
        self.assertAlmostEqual(a["sma200"], sma200, places=2); self.assertEqual(a["allowed"], allowed)
        self.assertEqual(bool(S.a_allowed_series(H)[day]), allowed)
        self.assertAlmostEqual(float(H.close[T(day) + pd.Timedelta(hours=20)]), price, places=2)
        self.assertAlmostEqual(self.indep(day, 200)[1], sma200, places=2)

    def test_b_crossings(self):
        self.check_b("2026-08-01", 62887.88, 63439.78, 0)   # research data's last state (31 Jul 2026): CASH
        self.check_b("2026-08-03", 63570.00, 63406.89, 1)   # crosses up: LONG
        self.check_b("2026-10-23", 81416.09, 81824.18, 0)   # crosses down after the Aug-Oct run: CASH
        self.check_b("2026-11-16", 65351.05, 79843.77, 0)   # today (handover: SMA50 79,844)

    def test_a_crossings(self):
        # 19 Aug 2026: 21:00 price 69,048 < SMA200 69,082 -> OFF. The original filter said ON because the
        # 00:00 close on 20 Aug (69,335, after the window) was above SMA200[19 Aug] (69,035): the look-ahead.
        self.check_a("2026-08-19", 69048.06, 69081.97, False)
        self.assertTrue(bool(S.a_allowed_series_original(H)["2026-08-19"]))
        self.check_a("2026-08-20", 72671.75, 69034.94, True)     # first ON day of the holdout
        self.check_a("2026-11-12", 71442.02, 73172.86, False)    # switched off in the November fall


class T4_current_state(unittest.TestCase):
    def test_16_nov_2026(self):
        s = S.current_state(H, now="2026-11-16 02:40")
        self.assertTrue(s["ok"], s["errors"])
        self.assertEqual(s["b_target"], 0); self.assertFalse(s["a_allowed"])
        self.assertEqual(round(s["b_close"]), 65351); self.assertEqual(round(s["sma50"]), 79844)
        self.assertEqual(round(s["sma200"]), 72978); self.assertEqual(s["state"], "bear (B cash, A off)")
        self.assertEqual(s["last_candle"], T("2026-11-16 01:00"))

    def test_live_price_used(self):
        s = S.current_state(H, now="2026-11-16 20:55", price_now=80000.0)
        self.assertTrue(s["a_allowed"]); self.assertEqual(s["a_price_source"], "live")
        self.assertEqual(s["state"], "pullback (B cash, A trades)")


class T5_no_lookahead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b, a = S.b_targets(DC), S.a_allowed_series(H)
        first = S.sma(DC, 200).first_valid_index() + pd.Timedelta(days=1)
        cross = set(b.index[b.diff().fillna(0) != 0]) | set(a.index[a.astype(int).diff().fillna(0) != 0])
        cls.days = sorted(d for d in cross | set(DC.index[DC.index >= first][::7]) if first <= d <= DC.index[-2])
        cls.b, cls.a = b, a

    def test_truncated_data(self):
        bad = []
        for d in self.days:
            hb = H[H.index < d]                                   # everything up to D-1 23:59
            if S.b_target(S.daily_closes(hb), d) != self.b[d]: bad.append(("B", d.date()))
            ha = H[H.index <= d + pd.Timedelta(hours=20)]         # everything up to D 20:59
            px = float(ha.close.iloc[-1])                         # = the 20:00 candle close
            if S.a_allowed(S.daily_closes(ha), px, d) != self.a[d]: bad.append(("A scalar", d.date()))
            if bool(S.a_allowed_series(ha)[d]) != bool(self.a[d]): bad.append(("A series", d.date()))
        print(f"\n  no-look-ahead check on {len(self.days)} days (every signal change + every 7th day): {len(bad)} mismatches")
        self.assertEqual(bad, [])

    def scrambled_after(self, cutoff, seed=0):
        h = H.copy(); m = h.index > cutoff
        f = np.random.default_rng(seed).uniform(0.3, 3.0, int(m.sum()))
        h.loc[m, ["open", "high", "low", "close"]] = h.loc[m, ["open", "high", "low", "close"]].values * f[:, None]
        return h

    def test_future_scrambled(self):
        for i, cut in enumerate(["2021-06-15 20:00", "2023-03-01 20:00", "2025-01-10 20:00", "2026-08-19 20:00"]):
            cut = T(cut); h2 = self.scrambled_after(cut, i); dc2 = S.daily_closes(h2)
            day = cut.normalize()                  # A for `day` may use data up to 20:59; B for `day` only to D-1
            pd.testing.assert_series_equal(S.a_allowed_series(h2)[:day], self.a[:day], check_names=False)
            pd.testing.assert_series_equal(S.b_targets(dc2)[:day], self.b[:day], check_names=False)

    def test_original_filter_fails(self):
        """Proves the scramble test has teeth: the old filter's decision for 19 Aug changes with post-window data."""
        cut = T("2026-08-19 20:00"); changed = 0
        for seed in range(20):
            h2 = self.scrambled_after(cut, seed)
            changed += bool(S.a_allowed_series_original(h2)["2026-08-19"]) != bool(S.a_allowed_series_original(H)["2026-08-19"])
        self.assertGreater(changed, 0)


class T6_edge_cases(unittest.TestCase):
    def test_too_few_closes(self):
        h = synthetic_hourly(np.linspace(100, 300, 120))          # rising, 120 days
        dc = S.daily_closes(h)
        self.assertEqual(int(S.b_targets(dc).iloc[:50].sum()), 0)  # days 1-50: fewer than 50 closes before them
        self.assertEqual(S.b_targets(dc).iloc[50], 1)               # day 51: first signal
        self.assertEqual(S.b_target(dc, dc.index[49]), 0); self.assertEqual(S.b_target(dc, dc.index[50]), 1)
        self.assertFalse(S.a_allowed_series(h).any())
        a = S.a_signal(dc, 1e9, dc.index[-1]); self.assertFalse(a["allowed"]); self.assertIsNone(a["sma200"])

    def test_equal_is_cash(self):
        h = synthetic_hourly([100.0] * 260); dc = S.daily_closes(h)   # close == SMA exactly
        self.assertEqual(int(S.b_targets(dc).sum()), 0)
        self.assertFalse(S.a_allowed_series(h).any())
        self.assertFalse(S.a_allowed(dc, 100.0, dc.index[-1])); self.assertTrue(S.a_allowed(dc, 100.01, dc.index[-1]))

    def test_stale_data_raises(self):
        with self.assertRaises(S.SignalError): S.b_target(DC[:"2026-11-13"], "2026-11-15")
        with self.assertRaises(S.SignalError): S.a_allowed(DC[:"2026-11-13"], 70000, "2026-11-15")

    def test_bad_price_raises(self):
        for p in (None, 0, -1, float("nan")):
            with self.assertRaises(S.SignalError): S.a_allowed(DC, p, "2026-11-16")

    def test_missing_2300_candle_blocks_trading(self):
        h = H.drop(T("2026-11-15 23:00"))
        s = S.current_state(h, now="2026-11-16 02:40")
        self.assertFalse(s["ok"]); self.assertTrue(any("23:00 candle" in e for e in s["errors"]))

    def test_feed_not_run_yet(self):
        s = S.current_state(H[H.index <= "2026-11-15 22:00"], now="2026-11-16 00:01")
        self.assertFalse(s["ok"])

    def test_missing_intraday_hour_is_warning_only(self):
        s = S.current_state(H.drop(T("2026-11-15 13:00")), now="2026-11-16 02:40")
        self.assertTrue(s["ok"]); self.assertTrue(any("missing hourly" in w for w in s["warnings"]))

    def test_now_ignores_later_candles(self):
        s = S.current_state(H, now="2026-08-19 20:55")
        self.assertEqual(s["last_candle"], T("2026-08-19 19:00"))    # the 20:00 candle hasn't closed at 20:55
        self.assertEqual(round(s["sma200"], 2), 69081.97)


if __name__ == "__main__":
    unittest.main(verbosity=2)
