"""
Offline tests for config (.env loading), the secrets precedence in exchange.load_secrets, the CLI dispatcher and
the FastAPI app. The API tests are skipped when fastapi/httpx are not installed (pip install -e 'backend[api,dev]').
"""
import contextlib, io, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from btc_bot import cli, config
from btc_bot.trading import exchange as X
from btc_bot.trading import ledger as L

KEYS = {k: f"value-{i}-abcdefgh" for i, k in enumerate(X.NEEDED)}

try:
    from fastapi.testclient import TestClient
    from btc_bot.api import app as api
    HAVE_API = True
except ImportError:                                        # fastapi or httpx missing
    HAVE_API = False


class T1_dotenv(unittest.TestCase):
    def test_parse_rules(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"KEEP": "from-shell"}, clear=False):
            p = Path(d) / ".env"
            p.write_text("# comment\nexport A_ONE=1\nB_TWO = 'two'\nC_EMPTY=\nKEEP=from-file\nD_HASH=val # note\nnot a line\n", encoding="utf-8")
            for k in ("A_ONE", "B_TWO", "C_EMPTY", "D_HASH"): os.environ.pop(k, None)
            applied = config.load_dotenv(p)
            self.assertEqual(sorted(applied), ["A_ONE", "B_TWO", "D_HASH"])
            self.assertEqual((os.environ["A_ONE"], os.environ["B_TWO"], os.environ["D_HASH"]), ("1", "two", "val"))
            self.assertNotIn("C_EMPTY", os.environ, "empty values must not be set (so the secrets file still applies)")
            self.assertEqual(os.environ["KEEP"], "from-shell", "a real environment variable wins over .env")
            for k in ("A_ONE", "B_TWO", "D_HASH"): os.environ.pop(k, None)
        self.assertEqual(config.load_dotenv(Path(tempfile.gettempdir()) / "does-not-exist.env"), [])

    def test_paths_default_to_the_checkout(self):
        self.assertTrue((config.ROOT / "STRATEGY_RULES.md").is_file(), config.ROOT)
        self.assertEqual(config.PAPER_DIR, config.DATA_DIR / "paper")
        self.assertNotIn("B_SPOT_API_SECRET", str(config.summary()))


class T2_secrets_precedence(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.f = Path(self.d.name) / "secrets.env"
        self.env = mock.patch.dict(os.environ, {}, clear=False); self.env.start()
        for k in X.NEEDED: os.environ.pop(k, None)
        self.path = mock.patch.object(X, "SECRETS_PATH", self.f); self.path.start()

    def tearDown(self): self.path.stop(); self.env.stop(); self.d.cleanup()

    def test_file_only(self):
        self.f.write_text("".join(f"{k}={v}\n" for k, v in KEYS.items())); os.chmod(self.f, 0o600)
        s, _ = X.load_secrets(); self.assertEqual(s, KEYS); self.assertEqual(X.LAST_SOURCE, str(self.f))

    def test_env_only_no_file(self):
        os.environ.update(KEYS)
        s, w = X.load_secrets(); self.assertEqual(s, KEYS); self.assertTrue(X.LAST_SOURCE.startswith("environment")); self.assertEqual(w, [])

    def test_env_overrides_file_per_key(self):
        self.f.write_text("".join(f"{k}=file-{k}\n" for k in X.NEEDED)); os.chmod(self.f, 0o600)
        os.environ["A_FUTURES_API_KEY"] = "from-env"
        s, _ = X.load_secrets()
        self.assertEqual(s["A_FUTURES_API_KEY"], "from-env"); self.assertEqual(s["B_SPOT_API_KEY"], "file-B_SPOT_API_KEY")
        self.assertIn(" + environment (A_FUTURES_API_KEY)", X.LAST_SOURCE)

    def test_missing_everywhere_names_keys_not_values(self):
        os.environ["B_SPOT_API_KEY"] = "only-one-key-123"
        with self.assertRaises(X.SecretsError) as cm: X.load_secrets()
        msg = str(cm.exception)
        self.assertIn("A_FUTURES_API_SECRET", msg); self.assertNotIn("only-one-key-123", msg)

    def test_directory_instead_of_file_falls_back_to_env(self):
        self.f.mkdir(); os.environ.update(KEYS)            # docker creates a dir when a bind-mounted file is missing
        self.assertEqual(X.load_secrets()[0], KEYS)


class T3_cli(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out): rc = cli.main(list(argv))
        return rc, out.getvalue()

    def test_help_config_and_unknown(self):
        rc, out = self.run_cli(); self.assertEqual(rc, 0); self.assertIn("harness", out)
        rc, out = self.run_cli("config"); self.assertEqual(rc, 0); self.assertIn('"data_dir"', out)
        with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(cli.main(["nope"]), 2)

    def test_dispatches_to_module_and_passes_exit_code(self):
        with mock.patch.object(L, "BASE_DIR", Path(tempfile.mkdtemp())):
            rc, out = self.run_cli("signals", "--at", "2026-11-16 02:40")
        self.assertEqual(rc, 0); self.assertIn("CASH", out); self.assertIn("OK", out)
        rc, _ = self.run_cli("signals", "--at", "2030-01-01 00:01")       # stale data -> not ok -> exit 1
        self.assertEqual(rc, 1)


@unittest.skipUnless(HAVE_API, "fastapi/httpx not installed")
class T4_api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.old = L.BASE_DIR; L.BASE_DIR = Path(cls.tmp.name)
        L.append("alerts", level="INFO", command="setup", message="hello")
        L.append("runs", command="status", status="OK", duration_s=1)
        api._cache.clear(); cls.c = TestClient(api.app)

    @classmethod
    def tearDownClass(cls): L.BASE_DIR = cls.old; api._cache.clear(); cls.tmp.cleanup()

    def test_health(self):
        r = self.c.get("/api/health"); self.assertEqual(r.status_code, 200)
        j = r.json(); self.assertEqual(j["status"], "ok"); self.assertTrue(j["last_candle"].startswith("20"))

    def test_dashboard_payload_and_cache(self):
        r = self.c.get("/api/dashboard"); self.assertEqual(r.status_code, 200)
        j = r.json(); self.assertEqual(j["schema"], 1)
        for k in ("signal", "B", "A", "C", "kill", "ops"): self.assertIn(k, j)
        self.assertEqual(self.c.get("/api/dashboard").json()["generated_utc"], j["generated_utc"], "second call served from cache")
        self.assertEqual(self.c.get("/api/dashboard?days=0").status_code, 422)

    def test_render_writes_files(self):
        r = self.c.post("/api/dashboard/render"); self.assertEqual(r.status_code, 200)
        self.assertTrue((L.BASE_DIR / "dashboard.json").is_file()); self.assertTrue((L.BASE_DIR / "dashboard.html").is_file())
        with mock.patch.object(api.config, "PAPER_DIR", L.BASE_DIR):
            f = self.c.get("/data/dashboard.json"); self.assertEqual(f.status_code, 200); self.assertEqual(f.json()["schema"], 1)

    def test_ledger(self):
        r = self.c.get("/api/ledger/alerts?limit=5"); self.assertEqual(r.status_code, 200)
        j = r.json(); self.assertEqual(j["total"], 1); self.assertEqual(j["rows"][0]["message"], "hello")
        self.assertEqual(self.c.get("/api/ledger/secrets").status_code, 404)

    def test_signals(self):
        j = self.c.get("/api/signals").json()
        self.assertIn(j["b_target"], (0, 1)); self.assertIn("ok", j)

    def test_accounts_without_keys_is_503(self):
        with mock.patch.object(X, "load_secrets", side_effect=X.SecretsError("empty or missing: B_SPOT_API_KEY")):
            r = self.c.get("/api/accounts")
        self.assertEqual(r.status_code, 503); self.assertIn("not configured", r.json()["detail"])

    def test_no_route_can_trade(self):
        posts = sorted(r.path for r in api.app.routes if "POST" in getattr(r, "methods", set()))
        self.assertEqual(posts, ["/api/dashboard/render"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
