#!/bin/bash
# What the Windows Task Scheduler runs, through WSL (scheduler/install_tasks.ps1):
#   wsl.exe -e bash "/mnt/c/Users/<you>/Documents/BTC Strategy Project/scripts/run.sh" b-check
# Runs one bot command from the project folder with the backend package on the path, and appends everything it
# prints to data/paper/logs/<command>.log. `dashboard` rebuilds the report; every other word is a harness command.
export PYTHONDONTWRITEBYTECODE=1
# Write each line to the log as it is printed, so a run that gets killed (e.g. by sleep or wake) still shows how far
# it got. Python holds back output sent to a file until the end otherwise (17 Nov 2026: two runs left only "start").
export PYTHONUNBUFFERED=1
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD/backend/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p data/paper/logs
{
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) start $1"
  if [ "$1" = "dashboard" ]; then
    python3 -m btc_bot dashboard "${@:2}"
  else
    python3 -m btc_bot harness "$@"
  fi
  rc=$?
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) end $1 exit $rc"
} >> "data/paper/logs/$1.log" 2>&1
# Mirror the candles and logs to the DigitalOcean dashboard (deploy/digitalocean/do.sh). Runs after the command, so it
# cannot delay a trade; does nothing while DO_HOST is unset in .env; never changes this run's exit code.
if [ -f deploy/digitalocean/do.sh ]; then
  timeout 120 bash deploy/digitalocean/do.sh sync >> data/paper/logs/sync.log 2>&1 || true
fi
exit $rc
