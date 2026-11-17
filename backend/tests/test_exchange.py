"""Offline tests for exchange.py: signing, secrets file, signed round trip against a fake server. No network.
Run: python3 -m unittest tests/test_exchange.py"""
import hashlib, hmac, json, os, socket, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse
sys.dont_write_bytecode = True
from btc_bot.trading import exchange as X

KEY, SECRET = "testkey123456", "testsecret987654"


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _reply(self, code, body):
        b = json.dumps(body).encode(); self.send_response(code); self.end_headers(); self.wfile.write(b)
    def _handle(self):
        u = urlparse(self.path)
        raw = u.query if self.command == "GET" else self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        if u.path.endswith("/time"): return self._reply(200, {"serverTime": 1_700_000_000_000})
        q, sig = raw.rsplit("&signature=", 1)
        good = hmac.new(SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
        if self.headers.get("X-MBX-APIKEY") != KEY or sig != good:
            return self._reply(401, {"code": -1022, "msg": "Signature for this request is not valid."})
        self._reply(200, {"ok": True, "params": dict(parse_qsl(q))})
    do_GET = do_POST = do_DELETE = _handle


class TestExchange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); cls.port = s.getsockname()[1]; s.close()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", cls.port), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def test_signature_matches_binance_docs_example(self):
        secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
        q = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
        self.assertEqual(X.BinanceClient.sign(secret, q), "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71")

    def test_signed_get_and_post_round_trip(self):
        c = X.BinanceClient(f"http://127.0.0.1:{self.port}", KEY, SECRET, futures=True)
        c.sync_time()
        r = c.get("/fapi/v2/balance", signed=True); self.assertTrue(r["ok"])
        self.assertIn("timestamp", r["params"]); self.assertEqual(r["params"]["recvWindow"], "5000")
        self.assertTrue(c.post("/fapi/v1/order", {"symbol": "BTCUSDT", "side": "BUY"})["ok"])

    def test_wrong_secret_raises_with_code(self):
        c = X.BinanceClient(f"http://127.0.0.1:{self.port}", KEY, "wrong", futures=True)
        with self.assertRaises(X.ExchangeError) as cm: c.get("/fapi/v2/balance", signed=True)
        self.assertEqual(cm.exception.code, -1022)

    def test_time_offset_applied(self):
        c = X.BinanceClient(f"http://127.0.0.1:{self.port}", KEY, SECRET)
        off = c.sync_time()
        r = c.get("/api/v3/account", signed=True)
        self.assertAlmostEqual(int(r["params"]["timestamp"]), 1_700_000_000_000, delta=5000)
        self.assertNotEqual(off, 0)

    def test_secrets_file(self):
        d = Path(tempfile.mkdtemp()); p = d / "secrets.env"
        p.write_text("# comment\nB_SPOT_API_KEY = 'abc12345xyz'\nB_SPOT_API_SECRET=s1\nA_FUTURES_API_KEY=\"k2\"\nA_FUTURES_API_SECRET=s2 \n")
        os.chmod(p, 0o600)
        s, w = X.load_secrets(p)
        self.assertEqual(s["B_SPOT_API_KEY"], "abc12345xyz"); self.assertEqual(s["A_FUTURES_API_KEY"], "k2"); self.assertEqual(w, [])
        os.chmod(p, 0o644); self.assertTrue(X.load_secrets(p)[1])
        p.write_text("B_SPOT_API_KEY=\n")
        with self.assertRaises(X.SecretsError): X.load_secrets(p)
        with self.assertRaises(X.SecretsError): X.load_secrets(d / "nope.env")
        self.assertEqual(X.mask("fsGrm4Zmabcdefgh"), "fsGr...gh")


if __name__ == "__main__":
    unittest.main(verbosity=2)
