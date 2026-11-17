"""
One entry point for every tool:  btc-bot <command> [options]   (or: python -m btc_bot <command> ...)

  feed               update data/btc_1h.csv from Binance (--dry-run, --price)
  signals            today's B target and A filter (--live, --at, --days)
  harness            the paper-trading bot: status, setup, b-check, a-precheck, a-enter, a-exit, a-test, flatten, relog
  connection-check   read-only check of both Binance Demo accounts
  dashboard          rebuild data/paper/dashboard.html + dashboard.json from the paper logs
  notify             Telegram messages: setup (once), test, after-run (called by the server's bot-run.sh)
  api             run the FastAPI server (--host, --port, --reload)
  backtest           research backtest, 2020 - Jul 2026 (--original-filter, --end)
  holdout            fresh out-of-sample report from 1 Aug 2026 (--start, --end)
  analysis           the original research scans (hour of day, autocorrelation, volume)
  build-dataset      rebuild data/btc_1h.csv from raw monthly Binance CSVs in the current folder
  config             print where data, logs, secrets and the web app are read from (no secret values)
Each command's own --help lists its options.
"""
import json
import runpy
import sys
import warnings

MODULES = {
    "feed": "btc_bot.data.feed",
    "signals": "btc_bot.strategy.signals",
    "harness": "btc_bot.trading.harness",
    "connection-check": "btc_bot.trading.connection_check",
    "dashboard": "btc_bot.reporting.dashboard",
    "notify": "btc_bot.reporting.notify",
    "backtest": "btc_bot.research.backtest",
    "holdout": "btc_bot.research.fresh_oos",
    "analysis": "btc_bot.research.analysis",
    "build-dataset": "btc_bot.data.build_dataset",
}


def run_api(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="btc-bot api", description="Serve the read-only dashboard API (and the built web app).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="restart on code changes (development)")
    a = ap.parse_args(argv)
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed: pip install -e 'backend[api]'  (or use docker compose up)", file=sys.stderr)
        return 1
    uvicorn.run("btc_bot.api.app:app", host=a.host, port=a.port, reload=a.reload)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "api":
        return run_api(rest)
    if cmd == "config":
        from . import config
        print(json.dumps(config.summary(), indent=2))
        return 0
    module = MODULES.get(cmd)
    if module is None:
        print(f"unknown command {cmd!r}. Commands: {', '.join([*MODULES, 'api', 'config'])}", file=sys.stderr)
        return 2
    saved, sys.argv = sys.argv, [f"btc-bot {cmd}", *rest]      # the module's own argparse reads these
    try:
        with warnings.catch_warnings():                      # "found in sys.modules": harmless when tests imported it
            warnings.filterwarnings("ignore", message=".*found in sys.modules.*", category=RuntimeWarning)
            runpy.run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit as e:                                  # modules end with sys.exit(main()): pass the code on
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.argv = saved
    return 0
