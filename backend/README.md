# backend: the `btc_bot` Python package

Everything that is not the web app: candle data, the two strategy signals, the research backtests, the paper-trading
bot for Binance Demo, the daily dashboard, and a read-only FastAPI server for the front end.

```
backend/
  pyproject.toml              package metadata, dependencies, the `btc-bot` command
  src/btc_bot/
    config.py                 paths and settings from env vars / the project .env (no secrets printed)
    cli.py                    `btc-bot <command>` dispatcher (also `python -m btc_bot`)
    data/feed.py              Binance 1h candles -> data/btc_1h.csv, checks, daily file
    data/build_dataset.py     rebuild the research dataset from raw monthly CSVs
    strategy/signals.py       B target (00:00 UTC) and A filter (20:55 UTC): used by the bot AND the backtests
    research/backtest.py      the research backtest (to 31 Jul 2026)
    research/fresh_oos.py     fresh out-of-sample holdout from 1 Aug 2026
    research/analysis.py      original scans (hour of day, autocorrelation, volume)
    trading/exchange.py       Binance REST client (HMAC signing) + API-key loading
    trading/orders.py         post-only order loops, fees, slippage, real vs demo book
    trading/ledger.py         append-only CSV ledgers under data/paper/
    trading/harness.py        the bot: status, setup, b-check, a-precheck, a-enter, a-exit, flatten, ...
    trading/fakebinance.py    offline fake exchange for tests and --dry-run
    trading/connection_check.py  read-only check of both demo accounts
    reporting/dashboard.py    every dashboard number; writes dashboard.html + dashboard.json
    api/app.py                FastAPI: /api/health, /api/dashboard, /api/signals, /api/ledger/{name}, /api/accounts
  tests/                      77 offline tests (unittest style; pytest runs them too)
```

## Commands

```bash
btc-bot --help                      # every command
btc-bot signals --live              # today's B and A decision with the live price
btc-bot harness status              # read-only account status
btc-bot dashboard                   # rebuild data/paper/dashboard.html + .json
btc-bot api --reload                # API on http://127.0.0.1:8000, docs at /docs
btc-bot holdout                     # out-of-sample report from 1 Aug 2026
btc-bot config                      # where data, logs, secrets and the web app are read from
```

Without installing, from the project root: `PYTHONPATH=backend/src python3 -m btc_bot <command>`. That is what
`scripts/run.sh` (the scheduler's entry point) does.

## Install for development (WSL)

Ubuntu's Python is "externally managed", so use a virtual environment that reuses the system pandas/numpy:

```bash
python3 -m venv --system-site-packages ~/.venvs/btc-bot
~/.venvs/btc-bot/bin/pip install -e "backend[api,dev]"     # if the venv has no pip: python3 -m pip --python ~/.venvs/btc-bot/bin/python install ...
source ~/.venvs/btc-bot/bin/activate
cd backend && python -m pytest -q                          # or: python -m unittest discover -s tests
```

Or skip all of that and use Docker from the project root: `docker compose up -d --build`.

## Settings and keys

Read in `config.py` and `trading/exchange.py`; see `.env.example` at the project root. API keys: environment variables
(which `.env` can set) override the secrets file, `~/.config/btc-bot/secrets.env` by default. The API never returns
key values and has no endpoint that places, changes or cancels an order.
