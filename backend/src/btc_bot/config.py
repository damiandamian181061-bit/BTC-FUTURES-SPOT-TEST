"""
Settings for every btc_bot module: paths and secrets, read from environment variables, which the project's
`.env` file can supply. Nothing here is a strategy parameter (those live in STRATEGY_RULES.md and the modules).

Order of precedence (highest first):
  1. a real environment variable (e.g. set by Docker Compose or the shell)
  2. a line in <project root>/.env (loaded once, here, at import; it never overrides 1)
  3. the defaults below
Relative paths are resolved against the project root.

  BTC_BOT_ROOT         project root            default: three levels above this file (the git checkout)
  BTC_BOT_DATA_DIR     candles + logs          default: <root>/data
  BTC_BOT_PAPER_DIR    paper-trading ledgers   default: <data>/paper
  BTC_BOT_CHARTS_DIR   research charts         default: <root>/charts
  BTC_BOT_SECRETS      Binance keys file       default: ~/.config/btc-bot/secrets.env
  BTC_BOT_FRONTEND_DIST built web app the API serves at /   default: <root>/frontend/dist
API keys themselves are read in trading/exchange.py: env vars (B_SPOT_API_KEY ...) win over the secrets file.
"""
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def load_dotenv(path, override=False):
    """Minimal .env reader (no dependency): KEY=VALUE lines, optional `export `, quotes stripped, # comments and
    blank values ignored. Returns the names it set. Values are never printed."""
    p = Path(path)
    if not p.is_file():
        return []
    applied = []
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if " #" in val and not val.startswith(("'", '"')):
            val = val.split(" #", 1)[0].rstrip()
        val = val.strip('"').strip("'")
        if not key or not val:
            continue
        if override or key not in os.environ:
            os.environ[key] = val
            applied.append(key)
    return applied


ROOT = Path(os.environ.get("BTC_BOT_ROOT") or PACKAGE_DIR.parents[2]).resolve()
DOTENV_FILE = ROOT / ".env"
DOTENV_APPLIED = load_dotenv(DOTENV_FILE)


def _path(name, default):
    v = os.environ.get(name, "").strip()
    p = Path(v).expanduser() if v else Path(default)
    return p if p.is_absolute() else ROOT / p


DATA_DIR = _path("BTC_BOT_DATA_DIR", ROOT / "data")
PAPER_DIR = _path("BTC_BOT_PAPER_DIR", DATA_DIR / "paper")
CHARTS_DIR = _path("BTC_BOT_CHARTS_DIR", ROOT / "charts")
SECRETS_FILE = _path("BTC_BOT_SECRETS", Path.home() / ".config" / "btc-bot" / "secrets.env")
FRONTEND_DIST = _path("BTC_BOT_FRONTEND_DIST", ROOT / "frontend" / "dist")


def summary():
    """Where everything points (for `btc-bot config` and the API health check). No secret values."""
    return {"root": str(ROOT), "data_dir": str(DATA_DIR), "paper_dir": str(PAPER_DIR), "charts_dir": str(CHARTS_DIR),
            "secrets_file": str(SECRETS_FILE), "frontend_dist": str(FRONTEND_DIST),
            "dotenv": str(DOTENV_FILE) if DOTENV_FILE.is_file() else None, "dotenv_keys_applied": sorted(DOTENV_APPLIED)}
