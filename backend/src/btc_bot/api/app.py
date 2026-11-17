"""
Read-only HTTP API for the dashboard app (frontend/). Run: `btc-bot api` (or `docker compose up`), docs at /docs.

  GET  /api/health                 liveness + where data is read from + data freshness
  GET  /api/dashboard?days=14      every dashboard number, computed live from the paper logs (schema 1; cached 30 s)
  POST /api/dashboard/render       rewrite data/paper/dashboard.html + dashboard.json (what the 23:10 task does)
  GET  /api/signals?live=false     today's B target and A filter (live=true fetches the Binance price)
  GET  /api/ledger/{name}?limit=N  the last N rows of one paper-trading ledger (runs, alerts, orders, fills, ...)
  GET  /api/accounts               demo account balances and A's position (needs the API keys; read-only calls)
  GET  /data/dashboard.json        the file the 23:10 task last wrote (fallback for the web app)
  GET  /                           the built web app, when frontend/dist (or BTC_BOT_FRONTEND_DIST) exists

Nothing here places, changes or cancels an order: trading stays with the scheduled harness commands.
"""
import threading
import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, config
from ..reporting import dashboard as D
from ..trading import ledger as L

app = FastAPI(
    title="BTC strategy paper-trading API",
    version=__version__,
    description="Read-only access to the paper-trading logs, signals and dashboard numbers. Places no orders.",
)

_CACHE_TTL_S = 30.0
_cache: dict = {}
_lock = threading.Lock()


def _dashboard_result(days):
    """compute() is ~0.5 s (it reads 60k candles): cache per grid size. Not dry-run: the API shows the real logs."""
    key = ("dashboard", days)
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL_S:
            return hit[1]
        L.set_dry_run(False)
        try:
            r = D.compute(grid_days=days)
        except FileNotFoundError as e:
            raise HTTPException(503, f"data not available: {e}") from e
        _cache[key] = (time.monotonic(), r)
        return r


@app.get("/api/health", tags=["meta"])
def health():
    from ..data.feed import load_hourly
    out = {"status": "ok", "version": __version__, "paths": config.summary()}
    try:
        h = load_hourly()
        out["last_candle"] = h.index[-1].isoformat() if len(h) else None
    except FileNotFoundError:
        out["last_candle"] = None
        out["status"] = "degraded: no candle file"
    return out


@app.get("/api/dashboard", tags=["dashboard"])
def dashboard(days: int = Query(14, ge=1, le=120, description="days shown in the operations grid")):
    return D.payload(_dashboard_result(days))


@app.post("/api/dashboard/render", tags=["dashboard"])
def render_dashboard():
    with _lock:
        _cache.clear()
    r = _dashboard_result(14)
    try:
        html, js = D.write_html(r), D.write_json(r)
    except OSError as e:                          # e.g. the DigitalOcean mirror mounts data/ read-only
        raise HTTPException(503, f"cannot write the dashboard files here: {e.strerror or e}") from e
    return {"html": str(html), "json": str(js), "generated_utc": r["now"].isoformat()}


@app.get("/api/signals", tags=["signals"])
def signals(live: bool = Query(False, description="fetch the live Binance price for A's check (needs network)")):
    from ..data import feed
    from ..strategy import signals as S
    price = None
    if live:
        try:
            price = feed.latest_price()
        except feed.NetworkError as e:
            raise HTTPException(502, f"Binance unreachable: {e}") from e
    return D.clean(S.current_state(price_now=price))


@app.get("/api/ledger/{name}", tags=["ledger"])
def ledger(name: str, limit: int = Query(200, ge=1, le=5000)):
    if name not in L.COLUMNS:
        raise HTTPException(404, f"unknown ledger {name!r}; known: {', '.join(L.COLUMNS)}")
    L.set_dry_run(False)
    rows = L.rows(name)
    return {"name": name, "columns": L.COLUMNS[name], "total": len(rows), "rows": rows[-limit:]}


@app.get("/api/accounts", tags=["accounts"])
def accounts():
    """Balances of both Binance Demo accounts and A's position. Read-only signed GET requests."""
    from ..trading import exchange as X, orders as O
    try:
        sec, warnings = X.load_secrets()
    except X.SecretsError as e:
        raise HTTPException(503, f"API keys not configured: {e}") from e
    try:
        spot, fut = X.spot_client(sec), X.futures_client(sec)
        spot.sync_time(); fut.sync_time()
        e = O.spot_equity(spot); fa = O.futures_account(fut); p = O.futures_position(fut)
    except X.ExchangeError as err:
        raise HTTPException(502, f"Binance error: {err}") from err
    return D.clean({
        "keys_from": X.LAST_SOURCE, "warnings": warnings,
        "B": {"equity_usdt": e["equity"], "usdt": e["usdt"], "btc": e["btc"], "price": e["price"]},
        "A": {"equity_usdt": fa["equity"], "wallet_usdt": fa["wallet"], "unrealized_usdt": fa["unrealized"],
              "position_btc": p["qty"], "entry": p["entry"], "margin_type": p["margin_type"], "leverage": p["leverage"]},
    })


@app.get("/data/dashboard.json", include_in_schema=False)
def dashboard_file():
    f = config.PAPER_DIR / "dashboard.json"
    if not f.is_file():
        raise HTTPException(404, "no dashboard.json yet: run `btc-bot dashboard` or POST /api/dashboard/render")
    return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-store"})


if config.FRONTEND_DIST.is_dir():                 # mounted last so /api and /data win
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="web")
