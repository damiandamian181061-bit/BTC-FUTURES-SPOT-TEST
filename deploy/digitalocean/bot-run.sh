#!/bin/bash
# Runs one bot command on the Droplet: the server-side twin of scripts/run.sh. Called by the deploy user's crontab
# (bot.crontab) and by `do.sh bot <cmd>`. Appends everything to <data>/paper/logs/<command>.log, like the laptop did.
#   bash bot-run.sh b-check | a-precheck | a-enter | a-exit | dashboard | status [--dry-run] ...
# DATA_DIR (default /srv/btc-data) and BOT_SECRETS_FILE (default ~/.config/btc-bot/secrets.env) can be overridden
# for tests, e.g. DATA_DIR=/tmp/btc-test BOT_SECRETS_FILE=/dev/null bash bot-run.sh status --dry-run
set -u
cd "$(dirname "$0")" || exit 1
export DATA_DIR="${DATA_DIR:-/srv/btc-data}"
export BOT_SECRETS_FILE="${BOT_SECRETS_FILE:-$HOME/.config/btc-bot/secrets.env}"
cmd="${1:?usage: bot-run.sh <command> [args]}"; shift
mkdir -p "$DATA_DIR/paper/logs"
{
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) start $cmd (droplet)"
  if [ ! -e "$BOT_SECRETS_FILE" ]; then
    # never let docker create a directory in place of a missing key file
    echo "secrets file missing: $BOT_SECRETS_FILE (copy it with do.sh bot-keys)"; rc=2
  else
    case "$cmd" in
      dashboard|connection-check) run=(btc-bot "$cmd" "$@") ;;     # top-level commands (read-only)
      *) run=(btc-bot harness "$cmd" "$@") ;;                       # b-check, a-precheck, a-enter, a-exit, status, ...
    esac
    docker compose --profile bot run --rm -T --no-deps bot "${run[@]}" < /dev/null
    rc=$?
  fi
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) end $cmd exit $rc"
} >> "$DATA_DIR/paper/logs/$cmd.log" 2>&1
exit $rc
