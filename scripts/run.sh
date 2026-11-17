#!/bin/bash
# What the Windows Task Scheduler runs, through WSL (scheduler/install_tasks.ps1):
#   wsl.exe -e bash "/mnt/c/Users/<you>/Documents/BTC Strategy Project/scripts/run.sh" b-check
# Runs one bot command from the project folder with the backend package on the path, and appends everything it
# prints to data/paper/logs/<command>.log. `dashboard` rebuilds the report; every other word is a harness command.
export PYTHONDONTWRITEBYTECODE=1
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
exit $rc
