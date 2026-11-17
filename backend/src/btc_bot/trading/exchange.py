"""
Minimal Binance REST client for the paper-trading harness (step 4). Standard library only (urllib, hmac).

Two separate keys, as decided 16 Nov 2026:
  B (trend)  -> spot demo,    https://demo-api.binance.com    key "btc-B-spot"
  A (window) -> futures demo, https://demo-fapi.binance.com   key "btc-A-futures"

The four keys come from two places; a value in the first wins:
  1. environment variables of the same names, which the project's .env file can set (see .env.example)
  2. the secrets file, by default ~/.config/btc-bot/secrets.env inside WSL (outside the project folder, chmod 600)
       B_SPOT_API_KEY=...
       B_SPOT_API_SECRET=...
       A_FUTURES_API_KEY=...
       A_FUTURES_API_SECRET=...
     Override its location with BTC_BOT_SECRETS (Docker Compose mounts it at /run/secrets/btc-bot.env).
Base URLs can be overridden with BTC_BOT_SPOT_URL / BTC_BOT_FUTURES_URL (Binance has moved the demo hosts before).

Signing (Binance docs): HMAC-SHA256 of the full query string with the secret, appended as `signature`;
key sent in the X-MBX-APIKEY header; `timestamp` in ms, corrected for the offset between this
machine's clock and Binance's (a drifting laptop clock otherwise gets requests rejected).
"""
import hashlib, hmac, json, os, stat, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

from ..config import SECRETS_FILE

SPOT_DEMO_URL = os.environ.get("BTC_BOT_SPOT_URL", "https://demo-api.binance.com")
FUTURES_DEMO_URL = os.environ.get("BTC_BOT_FUTURES_URL", "https://demo-fapi.binance.com")
SECRETS_PATH = SECRETS_FILE
NEEDED = ("B_SPOT_API_KEY", "B_SPOT_API_SECRET", "A_FUTURES_API_KEY", "A_FUTURES_API_SECRET")
LAST_SOURCE = None          # where the last load_secrets() found the keys (a description, never a value)


class ExchangeError(Exception):
    """Binance answered with an error (bad key, bad signature, rejected order...)."""
    def __init__(self, msg, status=None, code=None):
        super().__init__(msg); self.status, self.code = status, code


class SecretsError(Exception): pass


def mask(s):
    return "(empty)" if not s else (s[:4] + "..." + s[-2:] if len(s) > 8 else "****")


def _read_keyfile(p):
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_secrets(path=None):
    """The four API keys as a dict, plus warnings. Never prints values.
    path given: read only that file (used by the tests). path None: the secrets file (if it exists) overlaid by any
    non-empty environment variables of the same names (.env lands there via config)."""
    global LAST_SOURCE
    p = Path(path or SECRETS_PATH)
    out, warnings, sources = {}, [], []
    if p.is_file():
        try:
            out = _read_keyfile(p); sources.append(str(p))
        except OSError as e:                  # e.g. a bind-mounted file owned by another user
            if path is not None: raise SecretsError(f"cannot read {p}: {e}") from e
            warnings.append(f"cannot read {p}: {e.strerror}")
        try:
            if os.name == "posix" and p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                warnings.append(f"{p} is readable by other users: run  chmod 600 {p}")
        except OSError:
            pass
    elif path is not None:
        raise SecretsError(f"secrets file not found: {p}")
    if path is None:
        env = {k: os.environ[k].strip() for k in NEEDED if os.environ.get(k, "").strip()}
        if env:
            out.update(env); sources.append("environment (" + ", ".join(sorted(env)) + ")")
    LAST_SOURCE = " + ".join(sources) or None
    missing = [k for k in NEEDED if not out.get(k)]
    if missing:
        where = LAST_SOURCE or f"no secrets file at {p} and no environment variables"
        raise SecretsError(f"empty or missing ({where}): {', '.join(missing)}. Set them in .env or in {p}")
    return out, warnings


class BinanceClient:
    def __init__(self, base_url, api_key=None, api_secret=None, futures=False, recv_window=5000, timeout=15):
        self.base, self.key, self.secret = base_url.rstrip("/"), api_key, api_secret
        self.futures, self.recv_window, self.timeout = futures, recv_window, timeout
        self.prefix = "/fapi" if futures else "/api"
        self.offset_ms = 0

    # ---- low level
    @staticmethod
    def sign(secret, query):
        return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _request(self, method, path, params=None, signed=False):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {"User-Agent": "btc-strategy-bot/1.0"}
        if signed:
            if not (self.key and self.secret): raise ExchangeError("signed request without API key/secret")
            params["recvWindow"] = self.recv_window
            params["timestamp"] = int(time.time() * 1000) + self.offset_ms
            q = urllib.parse.urlencode(params)
            q += "&signature=" + self.sign(self.secret, q)
            headers["X-MBX-APIKEY"] = self.key
        else:
            q = urllib.parse.urlencode(params)
        url = f"{self.base}{path}" + (f"?{q}" if q and method in ("GET", "DELETE") else "")
        data = q.encode() if method in ("POST", "PUT") else None
        if data is not None: headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            try:
                j = json.loads(body); raise ExchangeError(f"{path}: HTTP {e.code} code {j.get('code')}: {j.get('msg')}", e.code, j.get("code"))
            except ValueError:
                raise ExchangeError(f"{path}: HTTP {e.code}: {body[:200]}", e.code)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise ExchangeError(f"{path}: cannot reach {self.base} ({e})")

    def get(self, path, params=None, signed=False): return self._request("GET", path, params, signed)
    def post(self, path, params=None): return self._request("POST", path, params, True)
    def delete(self, path, params=None): return self._request("DELETE", path, params, True)

    # ---- helpers
    def sync_time(self):
        """Measure the offset between this machine's clock and Binance's. Returns offset in ms."""
        t0 = int(time.time() * 1000)
        server = self.get(f"{self.prefix}/{'v1' if self.futures else 'v3'}/time")["serverTime"]
        t1 = int(time.time() * 1000)
        self.offset_ms = int(server - (t0 + t1) / 2)
        return self.offset_ms


def spot_client(secrets):
    return BinanceClient(SPOT_DEMO_URL, secrets["B_SPOT_API_KEY"], secrets["B_SPOT_API_SECRET"], futures=False)


def futures_client(secrets):
    return BinanceClient(FUTURES_DEMO_URL, secrets["A_FUTURES_API_KEY"], secrets["A_FUTURES_API_SECRET"], futures=True)
