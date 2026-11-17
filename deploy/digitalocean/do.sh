#!/bin/bash
# Laptop-side helper for the DigitalOcean dashboard mirror. Run from WSL; see deploy/digitalocean/README.md.
#   bash deploy/digitalocean/do.sh keys     make the two SSH keys (once) and cloud-init.local.yml for the Droplet
#   bash deploy/digitalocean/do.sh wait     wait until the Droplet's first-boot setup has finished
#   bash deploy/digitalocean/do.sh push     copy the code to the Droplet, (re)build and start app + caddy, then sync
#   bash deploy/digitalocean/do.sh sync     copy candles + paper logs to the Droplet (scripts/run.sh runs this after
#                                           every scheduled command; does nothing while DO_HOST is unset)
#   bash deploy/digitalocean/do.sh status   containers, health inside the Droplet, and what the public URL answers
#   bash deploy/digitalocean/do.sh ssh      a shell on the Droplet as `deploy`
# The bot on the Droplet (README "Bot on the Droplet"):
#   bash deploy/digitalocean/do.sh bot-keys copy ~/.config/btc-bot/secrets.env to the Droplet (600, never printed)
#   bash deploy/digitalocean/do.sh bot-on   Droplet takes over: ledgers writable by the bot, sync user off, schedule on
#   bash deploy/digitalocean/do.sh bot-off  undo bot-on (schedule off, sync user back); then re-enable the laptop tasks
#   bash deploy/digitalocean/do.sh bot CMD  run one bot command on the Droplet now (e.g. `status`) and show its log
#   bash deploy/digitalocean/do.sh pull     copy the Droplet's candles, ledgers and logs into the laptop's data/
# Settings in the project .env: DO_HOST=<droplet IPv4>, DO_SITE=<domain, or <ip-with-dashes>.sslip.io>,
# DO_BOT_ON_SERVER=1 once the Droplet runs the bot (then `sync` never uploads, so the laptop cannot overwrite it).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

ADMIN_KEY="$HOME/.ssh/btc_droplet"
SYNC_KEY="$HOME/.ssh/btc_droplet_sync"
REMOTE_DIR=/opt/btc-strategy
HERE=deploy/digitalocean

env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/'; }
HOST="${DO_HOST:-$(env_get DO_HOST)}"
SITE="${DO_SITE:-$(env_get DO_SITE)}"
[ -z "$SITE" ] && [ -n "$HOST" ] && SITE="${HOST//./-}.sslip.io"
BOT_ON_SERVER="${DO_BOT_ON_SERVER:-$(env_get DO_BOT_ON_SERVER)}"
SECRETS="$HOME/.config/btc-bot/secrets.env"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

die() { echo "do.sh: $*" >&2; exit 1; }
need_host() {
  [ -n "$HOST" ] || die "set DO_HOST=<droplet IPv4> in .env first"
  [[ "$HOST" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "DO_HOST must be an IPv4 address, got '$HOST'"
  [[ "$SITE" =~ ^[A-Za-z0-9.-]+$ ]] || die "DO_SITE must be a plain host name, got '$SITE'"
}
admin() { ssh -i "$ADMIN_KEY" "${SSH_OPTS[@]}" "deploy@$HOST" "$@"; }

cmd_keys() {
  for k in "$ADMIN_KEY:btc-droplet-admin" "$SYNC_KEY:btc-droplet-sync"; do
    f=${k%%:*}; c=${k##*:}
    if [ -f "$f" ]; then echo "exists: $f"; else ssh-keygen -q -t ed25519 -N "" -C "$c" -f "$f" && echo "created: $f"; fi
  done
  sed -e "s|__ADMIN_KEY__|$(cat "$ADMIN_KEY.pub")|" -e "s|__SYNC_KEY__|$(cat "$SYNC_KEY.pub")|" \
    "$HERE/cloud-init.tpl.yml" > "$HERE/cloud-init.local.yml" || die "could not write $HERE/cloud-init.local.yml"
  echo "wrote $HERE/cloud-init.local.yml (paste it into the Droplet's User data box)"
}

cmd_wait() {
  need_host
  for i in $(seq 1 40); do
    if admin true 2>/dev/null; then break; fi
    echo "waiting for SSH on $HOST ($i)"; sleep 10
  done
  admin 'cloud-init status --wait >/dev/null; cloud-init status --long | head -3; docker --version; docker compose version; free -h | head -3'
}

cmd_push() {
  need_host
  echo "--- copying code to $HOST:$REMOTE_DIR"
  git ls-files -z --cached --others --exclude-standard -- . ':(exclude)data' ':(exclude)charts' ':(exclude)_to_delete' \
    | rsync -rtz --from0 --files-from=- --chmod=D755,F644 -e "ssh -i $ADMIN_KEY ${SSH_OPTS[*]}" ./ "deploy@$HOST:$REMOTE_DIR/" \
    || die "rsync of the code failed"
  echo "--- building and starting on the Droplet (first build takes a few minutes)"
  admin bash -s -- "$REMOTE_DIR/$HERE" "$SITE" <<'REMOTE' || die "remote build/start failed"
set -euo pipefail
cd "$1"
printf 'SITE_ADDRESS=%s\n' "$2" > .env
if [ ! -s auth.caddy ]; then
  rm -rf auth.caddy   # a directory if docker ever created it for a missing mount
  printf 'respond "No login set yet: run deploy/digitalocean/set-password.sh on the Droplet." 503\n' > auth.caddy
  echo "no login yet: the site answers 503 until set-password.sh is run"
fi
docker compose up -d --build --remove-orphans
docker image prune -f --filter label=com.docker.compose.project=btc-dashboard >/dev/null   # ours only: never other projects'
docker compose ps
REMOTE
  cmd_sync
}

cmd_sync() {
  [ -n "$HOST" ] || exit 0                       # mirror not configured: nothing to do
  [ "$BOT_ON_SERVER" = 1 ] && exit 0             # the Droplet writes the ledgers now: never overwrite them from here
  need_host
  [ -f "$SYNC_KEY" ] || die "no sync key ($SYNC_KEY): run do.sh keys"
  cd data || die "no data folder"
  files=()
  for f in btc_1h.csv btc_1d.csv update_log.csv paper/*.csv paper/dashboard.json paper/logs/*.log; do
    [ -f "$f" ] && files+=("$f")
  done
  rsync -rtzR --chmod=D755,F644 --timeout=60 -e "ssh -i $SYNC_KEY ${SSH_OPTS[*]}" "${files[@]}" "btcsync@$HOST:./" \
    || die "$(date -u +%FT%TZ) sync to $HOST failed"
  echo "$(date -u +%FT%TZ) synced ${#files[@]} files to $HOST"
}

cmd_status() {
  need_host
  admin "cd $REMOTE_DIR/$HERE && docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}' && \
    docker compose exec -T app python -c \"import json,urllib.request as u; d=json.load(u.urlopen('http://127.0.0.1:8000/api/health')); print('health:', d['status'], '| last candle:', d['last_candle'])\""
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$SITE/")
  echo "https://$SITE/ answers $code (401 = login required, as intended; 503 = no login set yet)"
}

cmd_bot_keys() {
  need_host
  [ -f "$SECRETS" ] || die "no $SECRETS on this machine"
  # streamed over SSH into a 600 file; the values are never printed, only the key names are shown back
  admin 'umask 077; mkdir -p ~/.config/btc-bot && cat > ~/.config/btc-bot/secrets.env.new \
    && mv ~/.config/btc-bot/secrets.env.new ~/.config/btc-bot/secrets.env && chmod 600 ~/.config/btc-bot/secrets.env \
    && echo "keys on the Droplet (names only):" && sed -E "s/=.*/=<set>/" ~/.config/btc-bot/secrets.env | grep -v "^#" | grep .' \
    < "$SECRETS" || die "copying the keys failed"
}

cmd_bot_on() {
  need_host
  admin bash -s -- "$REMOTE_DIR/$HERE" <<'REMOTE' || die "bot-on failed"
set -euo pipefail
cd "$1"
[ -f ~/.config/btc-bot/secrets.env ] || { echo "no keys on the Droplet: run do.sh bot-keys first"; exit 1; }
sudo chown -R deploy:deploy /srv/btc-data            # the bot container runs as uid 1000 (= deploy) and writes here now
if sudo test -f /home/btcsync/.ssh/authorized_keys; then  # the laptop no longer uploads: switch its login off
  sudo mv /home/btcsync/.ssh/authorized_keys /home/btcsync/.ssh/authorized_keys.disabled
fi
{ (crontab -l 2>/dev/null || true) | sed '/>>> btc-bot schedule/,/<<< btc-bot schedule/d'; cat bot.crontab; } | crontab -
echo "--- crontab of deploy now:"; crontab -l
REMOTE
}

cmd_bot_off() {
  need_host
  admin bash -s <<'REMOTE' || die "bot-off failed"
set -euo pipefail
(crontab -l 2>/dev/null || true) | sed '/>>> btc-bot schedule/,/<<< btc-bot schedule/d' | crontab -
echo "--- crontab of deploy now:"; crontab -l 2>/dev/null || echo "(empty)"
if sudo test -f /home/btcsync/.ssh/authorized_keys.disabled; then
  sudo mv /home/btcsync/.ssh/authorized_keys.disabled /home/btcsync/.ssh/authorized_keys
fi
sudo chown -R btcsync:btcsync /srv/btc-data
REMOTE
  echo "Schedule off on the Droplet. To hand back to the laptop: do.sh pull, remove DO_BOT_ON_SERVER from .env, then"
  echo "PowerShell: Get-ScheduledTask -TaskName 'BTC bot*' | Enable-ScheduledTask"
}

cmd_bot() {
  need_host
  [ $# -ge 1 ] || die "usage: do.sh bot <command> [args]"
  admin "bash $REMOTE_DIR/$HERE/bot-run.sh $(printf '%q ' "$@"); rc=\$?; tail -n 40 /srv/btc-data/paper/logs/$1.log; exit \$rc"
}

cmd_pull() {
  need_host
  [ "$BOT_ON_SERVER" = 1 ] || die "the laptop is still the source (DO_BOT_ON_SERVER is not 1 in .env): pulling would overwrite newer laptop files"
  rsync -rtz --exclude 'paper/dryrun/' -e "ssh -i $ADMIN_KEY ${SSH_OPTS[*]}" "deploy@$HOST:/srv/btc-data/" data/ \
    || die "pull from $HOST failed"
  echo "$(date -u +%FT%TZ) pulled candles, ledgers and logs from $HOST into data/"
}

case "${1:-}" in
  keys) cmd_keys ;;
  wait) cmd_wait ;;
  push) cmd_push ;;
  sync) cmd_sync ;;
  status) cmd_status ;;
  ssh) need_host; ssh -i "$ADMIN_KEY" -o StrictHostKeyChecking=accept-new "deploy@$HOST" ;;
  bot-keys) cmd_bot_keys ;;
  bot-on) cmd_bot_on ;;
  bot-off) cmd_bot_off ;;
  bot) shift; cmd_bot "$@" ;;
  pull) cmd_pull ;;
  *) sed -n '2,18p' "$0"; exit 2 ;;
esac
