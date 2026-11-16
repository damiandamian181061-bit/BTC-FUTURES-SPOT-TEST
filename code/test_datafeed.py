"""
Offline tests for datafeed.py against a local fake Binance API built from data/btc_1h.csv.
Nothing in data/ is touched: each test works on a copy in a temp folder.
Run:  python code/test_datafeed.py
"""
import json, os, shutil, socket, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pandas as pd

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
FULL = pd.read_csv(ROOT / "data" / "btc_1h.csv", index_col=0, parse_dates=True)["2026-01-01":"2026-07-31"]   # fixed slice: the live file keeps growing
DAILY = FULL.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
FAULT = {"mode": ""}


class FakeBinance(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/api/v3/ticker/price":
            body = {"symbol": "BTCUSDT", "price": f"{FULL.close.iloc[-1]:.8f}"}
        else:
            df, step = (FULL, 3600000) if q["interval"] == "1h" else (DAILY, 86400000)
            s, e = (pd.Timestamp(int(q[k]), unit="ms", tz="UTC") for k in ("startTime", "endTime"))
            sub = df[(df.index >= s) & (df.index <= e)].iloc[: int(q["limit"])]
            if q["interval"] == "1h" and FAULT["mode"] == "shift": sub = sub.assign(close=sub.close * 1.001)
            if q["interval"] == "1h" and FAULT["mode"] == "hole": sub = sub[(sub.index < "2026-07-10") | (sub.index >= "2026-07-12")]
            body = [[int(t.timestamp() * 1000), *(f"{v:.8f}" for v in r[["open", "high", "low", "close", "volume"]]),
                     int(t.timestamp() * 1000) + step - 1, "0", 0, "0", "0", "0"] for t, r in sub.iterrows()]
        b = json.dumps(body).encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)


class TestDataFeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", port), FakeBinance)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        os.environ["BTC_FEED_BASE_URL"] = f"http://127.0.0.1:{port}"
        sys.path.insert(0, str(ROOT / "code"))
        import datafeed; cls.f = datafeed
        datafeed.BASE_URLS = [os.environ["BTC_FEED_BASE_URL"]]

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def setUp(self):
        FAULT["mode"] = ""
        self.tmp = Path(tempfile.mkdtemp())
        self.f.HOURLY_CSV, self.f.DAILY_CSV, self.f.LOG_CSV = (self.tmp / n for n in ("btc_1h.csv", "btc_1d.csv", "log.csv"))
        FULL.to_csv(self.tmp / "full.csv")

    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def stored(self, until): FULL[:until].to_csv(self.f.HOURLY_CSV)
    def now(self, ts): return int(pd.Timestamp(ts, tz="UTC").timestamp() * 1000)

    def test_update_is_byte_identical_and_paginates(self):
        self.stored("2026-05-31 23:00")                       # 1,464 new hours -> 2 pages of 1000
        self.assertEqual(self.f.update(now_ms=self.now("2026-08-01 00:30")), 0)
        self.assertEqual(self.f.HOURLY_CSV.read_bytes(), (self.tmp / "full.csv").read_bytes())
        self.assertTrue(self.f.daily_closes(self.f.load_hourly()).equals(FULL.close.resample("1D").last()))

    def test_second_run_is_noop(self):
        self.stored("2026-07-31 23:00")
        self.assertEqual(self.f.update(now_ms=self.now("2026-08-01 00:30")), 0)
        self.assertEqual(len(self.f.load_hourly()), len(FULL))

    def test_forming_candle_not_stored_then_resumes(self):
        self.stored("2026-06-30 23:00")
        self.f.update(now_ms=self.now("2026-07-15 10:30"))
        self.assertEqual(self.f.load_hourly().index[-1], pd.Timestamp("2026-07-15 09:00", tz="UTC"))
        self.f.update(now_ms=self.now("2026-08-01 00:30"))
        self.assertEqual(self.f.HOURLY_CSV.read_bytes(), (self.tmp / "full.csv").read_bytes())

    def test_overlap_mismatch_writes_nothing(self):
        self.stored("2026-06-30 23:00"); before = self.f.HOURLY_CSV.read_bytes(); FAULT["mode"] = "shift"
        self.assertEqual(self.f.update(now_ms=self.now("2026-08-01 00:30")), 1)
        self.assertEqual(self.f.HOURLY_CSV.read_bytes(), before)

    def test_long_gap_writes_nothing(self):
        self.stored("2026-06-30 23:00"); before = self.f.HOURLY_CSV.read_bytes(); FAULT["mode"] = "hole"
        self.assertEqual(self.f.update(now_ms=self.now("2026-08-01 00:30")), 1)
        self.assertEqual(self.f.HOURLY_CSV.read_bytes(), before)

    def test_dry_run_writes_nothing(self):
        self.stored("2026-06-30 23:00"); before = self.f.HOURLY_CSV.read_bytes()
        self.assertEqual(self.f.update(dry_run=True, now_ms=self.now("2026-08-01 00:30")), 0)
        self.assertEqual(self.f.HOURLY_CSV.read_bytes(), before); self.assertFalse(self.f.LOG_CSV.exists())

    def test_latest_price(self):
        self.assertAlmostEqual(self.f.latest_price(), FULL.close.iloc[-1], places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
