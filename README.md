# BTC Strategy Project

A rule-based Bitcoin trading system: researched on seven years of Binance hourly data, tested out of sample, and now
paper-traded automatically on Binance Demo from a Windows laptop, with a dashboard to judge it against the backtest.

It has two independent parts. **B** holds Bitcoin while the daily close is above its 50-day average and holds cash
otherwise. **A** buys at 21:00 UTC and sells at 23:00 UTC with limit orders, only on days when the price is above its
200-day average. No stops, no targets, no shorting, no doubling; size is always a fixed fraction of the current account.
The rules are written down once, in [STRATEGY_RULES.md](STRATEGY_RULES.md), and the code follows them.

## Get started

You need WSL (Ubuntu) with `python3`, `python3-pandas` and `python3-matplotlib`, and Node 24 on Windows for the app.

```bash
# in WSL, from the project folder
for t in test_datafeed test_signals test_exchange test_harness test_dashboard; do python3 code/$t.py 2>&1 | tail -1; done
python3 code/dashboard.py          # builds data/paper/dashboard.html and dashboard.json from the paper logs
```

```powershell
# on Windows: the dashboard app
cd frontend
npm install
npm run dev                        # then open http://127.0.0.1:5173
```

Paper trading itself runs on five scheduled Windows tasks (UTC) that call `code/run.sh` through WSL, and needs
Binance Demo API keys in `~/.config/btc-bot/secrets.env` inside WSL. The handover below says exactly where that stands.

## Guides

| Guide | Read it for |
|---|---|
| [Current state and handover](HANDOVER_STEP5_START.md) | where everything stands, what runs when, what to do next |
| [Strategy rules](STRATEGY_RULES.md) | the exact rules, expected numbers, kill switches, change log |
| [Project context](PROJECT_CONTEXT.md) | how the project got here: the martingale that was rejected, the research, the decisions |
| [Research write-up](docs/STRATEGY_WRITEUP.md) | the data, every test and every table (original, pre-correction numbers) |
| [Front end](frontend/README.md) | the Vite + React dashboard app: how it gets its data, how to run and build it |
| [Scheduler](scheduler/install_tasks.ps1) | the five scheduled tasks, explained in the comments at the top |
| Earlier sessions: [step 2](HANDOVER_STEP2.md), [step 3](HANDOVER_STEP3.md), [step 4](HANDOVER_STEP4_START.md) | the data feed, the signal engine, the Binance Demo set-up |

## Layout

| Folder | Contents |
|---|---|
| `code/` | Python: data feed, signals, backtests, exchange client, paper-trading bot, dashboard, tests |
| `data/` | hourly and daily candles; `data/paper/` holds the append-only paper-trading logs |
| `frontend/` | the dashboard app |
| `scheduler/` | install, uninstall and laptop power scripts for the scheduled tasks |
| `charts/` | research charts |
