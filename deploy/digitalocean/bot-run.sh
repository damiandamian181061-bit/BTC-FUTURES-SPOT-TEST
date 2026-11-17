#!/bin/bash
# Runs one bot command on the Droplet: the server-side twin of scripts/run.sh. Called by the deploy user's crontab
# (bot.crontab) and by `do.sh bot <cmd>`. Appends everything to <data>/paper/logs/<command>.log, like the laptop did.
#   bash bot-run.sh b-check | a-precheck | a-enter | a-exit | dashboard | status [--dry-run] | notify test ...
# DATA_DIR (default /srv/btc-data) and BOT_SECRETS_FILE (default ~/.config/btc-bot/secrets.env) can be overridden
# for tests, e.g. DATA_DIR=/tmp/btc-test BOT_SECRETS_FILE=/dev/null bash bot-run.sh status --dry-run
#
# Telegram (added 17 Nov 2026): after each of the five scheduled commands a second one-off container runs
# `btc-bot notify after-run` (backend/src/btc_bot/reporting/notify.py): problems and trades at once, a daily summary
# after the 23:10 dashboard run. Skipped while the secrets file has no TELEGRAM_BOT_TOKEN. If that container fails
# too (e.g. Docker itself is broken), a short message goes out with curl from the host instead.
set -u
cd "$(dirname "$0")" || exit 1
export DATA_DIR="${DATA_DIR:-/srv/btc-data}"
export BOT_SECRETS_FILE="${BOT_SECRETS_FILE:-$HOME/.config/btc-bot/secrets.env}"
cmd="${1:?usage: bot-run.sh <command> [args]}"; shift
mkdir -p "$DATA_DIR/paper/logs"

# one value from the secrets file (never echoed)
secret() { grep -E "^$1=" "$BOT_SECRETS_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d "\r\"' "; }

# last resort, from the host: the token reaches curl on stdin (printf is a shell builtin), never on a command line
host_notify() {
  local token chat
  token=$(secret TELEGRAM_BOT_TOKEN); chat=$(secret TELEGRAM_CHAT_ID)
  [ -n "$token" ] && [ -n "$chat" ] && command -v curl >/dev/null || return 1
  printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token" \
    | curl -sS -f -m 20 -o /dev/null -K - --data-urlencode "chat_id=$chat" --data-urlencode "text=$1"
}

{
  start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "===== $start start $cmd (droplet)"
  if [ ! -e "$BOT_SECRETS_FILE" ]; then
    # never let docker create a directory in place of a missing key file
    echo "secrets file missing: $BOT_SECRETS_FILE (copy it with do.sh bot-keys)"; rc=2
  else
    case "$cmd" in
      dashboard|connection-check|notify) run=(btc-bot "$cmd" "$@") ;;   # top-level commands (no orders)
      *) run=(btc-bot harness "$cmd" "$@") ;;                       # b-check, a-precheck, a-enter, a-exit, status, ...
    esac
    docker compose --profile bot run --rm -T --no-deps bot "${run[@]}" < /dev/null
    rc=$?
  fi
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) end $cmd exit $rc"
  case "$cmd" in
    b-check|a-precheck|a-enter|a-exit|dashboard)
      if [ -n "$(secret TELEGRAM_BOT_TOKEN)" ]; then
        docker compose --profile bot run --rm -T --no-deps bot btc-bot notify after-run --command "$cmd" --rc "$rc" --since "$start" < /dev/null
        nrc=$?
        if [ "$nrc" -ne 0 ]; then
          if host_notify "BTC bot: $cmd ended with exit $rc at $(date -u +%H:%M) UTC, and the notifier failed (exit $nrc). Check /srv/btc-data/paper/logs/$cmd.log"; then
            echo "notify: notifier exit $nrc; fallback message sent from the host"
          else
            echo "notify: notifier exit $nrc; the host fallback failed too"
          fi
        fi
      fi ;;
  esac
} >> "$DATA_DIR/paper/logs/$cmd.log" 2>&1
exit $rc
