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
cp .env.example .env              # optional: settings and API keys, see the comments inside
docker compose up -d --build      # web app + API on http://127.0.0.1:8000, API docs at /docs
```

Run the tests or any command inside the same image:

```bash
docker compose --profile test run --rm tests
docker compose run --rm app btc-bot signals
```

The dashboard works without API keys. The live account view and the paper-trading bot need Binance Demo keys, either
in `.env` or in `~/.config/btc-bot/secrets.env`. The bot itself runs on a schedule on the host
(`scheduler/install_tasks.ps1`), never inside the container.

## Guides

| Guide | Read it for |
|---|---|
| [Current state and handover](HANDOVER_STEP5_START.md) | where everything stands, what runs when, what to do next |
| [Strategy rules](STRATEGY_RULES.md) | the exact rules, expected numbers, kill switches, change log |
| [Backend](backend/README.md) | the `btc_bot` Python package, the `btc-bot` commands, the API, local development |
| [Front end](frontend/README.md) | the Vite + React dashboard app and how it gets its data |
| [Settings and keys](.env.example) | every setting the code and Docker read, with explanations |
| [Scheduler](scheduler/install_tasks.ps1) | the five scheduled tasks, explained in the comments at the top |
| [Project context](PROJECT_CONTEXT.md) | how the project got here: the martingale that was rejected, the research, the decisions |
| [Research write-up](docs/STRATEGY_WRITEUP.md) | the data, every test and every table (original, pre-correction numbers) |

## Layout

| Folder | Contents |
|---|---|
| `backend/` | the `btc_bot` Python package (data, strategy, research, trading, reporting, API) and its tests |
| `frontend/` | the dashboard web app |
| `data/` | candles; `data/paper/` holds the append-only paper-trading ledgers |
| `scripts/` | `run.sh`, the entry point the scheduled tasks call |
| `scheduler/` | install, uninstall and laptop power scripts for the scheduled tasks |
| `charts/`, `docs/` | research charts and the research write-up |
