# BTC Strategy Project

A rule-based Bitcoin trading system: researched on seven years of Binance hourly data, tested out of sample, and now
paper-traded automatically on Binance Demo, with a web dashboard to judge it against the backtest.

It has two independent parts. **B** holds Bitcoin while the daily close is above its 50-day average and holds cash
otherwise. **A** buys at 21:00 UTC and sells at 23:00 UTC with limit orders, only on days when the price is above its
200-day average. No stops, no targets, no shorting, no doubling; size is always a fixed fraction of the current account.
The rules are written down once, in [STRATEGY_RULES.md](STRATEGY_RULES.md), and the code follows them.

## Get started

You need Docker. From the project folder (in WSL on Windows):

```bash
cp .env.example .env              # optional: local settings, see the comments inside
docker compose up -d --build      # web app + API on http://127.0.0.1:8000, API docs at /docs
```

Run the tests or any command inside the same image:

```bash
docker compose --profile test run --rm tests
docker compose run --rm app btc-bot signals
```

The dashboard works without API keys. The live account view and the paper-trading bot need Binance Demo keys in
`~/.config/btc-bot/secrets.env` (outside the project; never in `.env` or in git).

## How it runs

The bot runs on a small DigitalOcean Droplet: five scheduled commands a day (UTC), each a short-lived container from
the same image, writing append-only ledgers. The same server hosts the dashboard behind HTTPS and a login; it reads
those ledgers read-only and has no access to the keys. The bot only ever trades the Binance Demo accounts.

| UTC | Command | What it does |
|---|---|---|
| 00:01 | `b-check` | update candles, compute B's target, switch the spot holding if needed |
| 20:55 | `a-precheck` | live price vs the 200-day average: is A allowed today? |
| 21:00 | `a-enter` | post-only buy at the bid until 21:05 (never a market buy) |
| 22:55 | `a-exit` | post-only sell until 23:00, then market for any rest |
| 23:10 | `dashboard` | rebuild the report from the ledgers |

After each run, `btc-bot notify` sends a Telegram message for problems (alerts, failed runs) and trades, plus a daily
summary after the 23:10 run that also works as a heartbeat.

## Guides

| Guide | Read it for |
|---|---|
| [Strategy rules](STRATEGY_RULES.md) | the exact rules, expected numbers, kill switches, change log |
| [Research write-up](docs/STRATEGY_WRITEUP.md) | the data, every test and every table (original, pre-correction numbers; the rules file has the corrected ones) |
| [Backend](backend/README.md) | the `btc_bot` Python package, the `btc-bot` commands, the API, local development |
| [Front end](frontend/README.md) | the Vite + React dashboard app and how it gets its data |
| [Deployment](deploy/digitalocean/README.md) | the Droplet: bot schedule, dashboard, HTTPS and login, keys, rollback |
| [Settings](.env.example) | every setting the code and Docker read, with explanations |

## Layout

| Folder | Contents |
|---|---|
| `backend/` | the `btc_bot` Python package (data, strategy, research, trading, reporting, API) and its tests |
| `frontend/` | the dashboard web app |
| `deploy/digitalocean/` | the server setup: compose file, Caddy, schedule, helper scripts |
| `data/` | candles; `data/paper/` holds the append-only paper-trading ledgers |
| `charts/`, `docs/` | research charts and the research write-up |
| `scheduler/`, `scripts/` | the earlier laptop setup (Windows Task Scheduler -> WSL), kept for switching back |
