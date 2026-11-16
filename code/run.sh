#!/bin/bash
# Wrapper the Windows Task Scheduler calls through WSL. Runs one bot command from the project folder and
# appends everything it prints to data/paper/logs/<command>.log (one file per command, newest at the bottom).
#   wsl.exe -e bash -c "'/mnt/c/Users/damia/Documents/BTC Strategy Project/code/run.sh' b-check"
#   wsl.exe -e bash -c "'/mnt/c/Users/damia/Documents/BTC Strategy Project/code/run.sh' dashboard"
# Every command goes to harness.py except `dashboard`, which is the read-only report (code/dashboard.py).
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")/.." || exit 1
mkdir -p data/paper/logs
{
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) start $1"
  if [ "$1" = "dashboard" ]; then
    python3 code/dashboard.py "${@:2}"
  else
    python3 code/harness.py "$@"
  fi
  rc=$?
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) end $1 exit $rc"
} >> "data/paper/logs/$1.log" 2>&1
exit $rc
