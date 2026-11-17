# Dashboard mirror on DigitalOcean

The web app (the same Docker image as `docker compose up` on the laptop) runs on a small Droplet behind Caddy,
which provides HTTPS and a password. **Trading does not move:** the scheduled bot stays on the laptop, and after
every scheduled run `scripts/run.sh` copies the candles and paper logs to the Droplet. The Droplet holds no API keys,
so `/api/accounts` answers 503 there and nothing on it can reach the Binance accounts.

```
laptop (WSL, Task Scheduler)                         Droplet (Ubuntu 24.04, ~$6/month)
  scripts/run.sh <cmd>  -- trades, writes data/  -->  rsync as `btcsync` (upload-only) -> /srv/btc-data
                                                      app (FastAPI + web app, data mounted read-only)
                                                      caddy :443  (Let's Encrypt + basic auth) -> you
```

| File | Role |
|---|---|
| `compose.yml` | app + caddy on the Droplet |
| `Caddyfile` | HTTPS, security headers, login (`auth.caddy`), proxy to the app |
| `cloud-init.tpl.yml` | first-boot setup: Docker, swap, firewall (22/80/443), users `deploy` and `btcsync` |
| `do.sh` | laptop helper: `keys`, `wait`, `push`, `sync`, `status`, `ssh` |
| `set-password.sh` | run on the Droplet to set or change the login |

## First deploy

All laptop commands are in WSL, from the project folder.

1. **Keys and user data:** `bash deploy/digitalocean/do.sh keys`. This makes `~/.ssh/btc_droplet` (admin) and
   `~/.ssh/btc_droplet_sync` (upload-only) and writes `deploy/digitalocean/cloud-init.local.yml`.
2. **Create the Droplet** (cloud.digitalocean.com > Create > Droplets): Ubuntu 24.04 LTS, region London (LON1),
   Basic / Regular, 1 GB / 1 CPU. Authentication: SSH key (any key of yours: it only goes on `root`). Under
   *Advanced options*, tick *Add initialization scripts (free)* and paste the whole of `cloud-init.local.yml`.
3. **Point the laptop at it:** add `DO_HOST=<the Droplet's IPv4>` to `.env`. Optionally add `DO_SITE=<your domain>`
   once its A record points at that IP; otherwise the site is `https://<ip-with-dashes>.sslip.io`.
4. `bash deploy/digitalocean/do.sh wait`, then `bash deploy/digitalocean/do.sh push`. Until a login is set, the site
   answers 503.
5. **Set the login:** `bash deploy/digitalocean/do.sh ssh`, then `bash /opt/btc-strategy/deploy/digitalocean/set-password.sh`.
6. `bash deploy/digitalocean/do.sh status`. The site should answer 401 without the login.

## On an existing Droplet instead (how it actually runs, since 17 Nov 2026)

The mirror shares the btc-options-lab Droplet (`recorder-1`) instead of a new one, at no extra cost. Its own
compose project (`btc-dashboard`) runs next to `optlab` and does not touch it. Differences from the steps above:

- No cloud-init. Root SSH is disabled there (`sshd_config.d/10-hardening.conf`), so the admin key
  (`~/.ssh/btc_droplet.pub`) was appended to the existing `deploy` user (sudo, docker). `btcsync`, its rrsync-only
  key, `/srv/btc-data` and `/opt/btc-strategy` were created by hand exactly as `cloud-init.tpl.yml` does.
- Docker, swap and rsync were already there. ufw is inactive; the DigitalOcean cloud firewall `ssh-only` guards the
  Droplet and needed inbound HTTP (80) and HTTPS (443) rules added before Caddy could get its certificate.
- `.env` holds `DO_HOST` only; the site is `https://<ip-with-dashes>.sslip.io`.

## Bot on the Droplet (since 17 Nov 2026, 21:28 UTC)

The scheduled bot no longer runs on the laptop. On 17 Nov the laptop slept through the 20:55 and 21:00 runs, so the
schedule moved to the always-on Droplet. That makes the Droplet the source of the ledgers; the laptop only reads.

- **Schedule:** `bot.crontab` in the `deploy` user's crontab (UTC), same commands and times as
  `scheduler/install_tasks.ps1`. Each line runs `bot-run.sh <cmd>`. That script starts a one-off `bot` container from
  the same image as the app (`docker compose --profile bot run`, capped at 768 MB and 1 CPU) and appends the output to
  `/srv/btc-data/paper/logs/<cmd>.log`.
- **Ledgers:** `/srv/btc-data` (owned by `deploy`; the bot writes there, the web app reads it read-only, so the
  website is always current). The upload-only `btcsync` login is switched off (`authorized_keys.disabled`).
- **Keys:** the four Binance Demo keys are in `~/.config/btc-bot/secrets.env` of `deploy` on the Droplet (mode 600,
  copied with `do.sh bot-keys`, never printed, never in git), mounted read-only into the bot container only. The web
  app still has no keys.
- **Laptop:** the five Windows tasks are disabled, not deleted, and `.env` has `DO_BOT_ON_SERVER=1`, so `do.sh sync`
  and the hook in `scripts/run.sh` never upload. `bash deploy/digitalocean/do.sh pull` copies the Droplet's candles,
  ledgers and logs into `data/`; run it before committing the ledgers to git. Don't run harness commands on the
  laptop any more (even `status` writes rows): use `bash deploy/digitalocean/do.sh bot status`.
- **Checks:** `do.sh status` (site), `do.sh bot status` (accounts and last runs, read-only),
  `do.sh bot connection-check`.
- **Telegram messages** (since 17 Nov 2026): after each of the five scheduled commands, `bot-run.sh` starts a second
  one-off container with `btc-bot notify after-run` (`backend/src/btc_bot/reporting/notify.py`). It sends problems
  (every ERROR/WARN alert, or a non-zero exit with the last log lines) and trades (B switch, A entry or unfilled, A
  close) at once, plus a daily summary after the 23:10 dashboard run. **No daily message by ~23:15 UTC means the
  server or its schedule is down.** If the notifier container fails too, `bot-run.sh` sends a short message with
  `curl` from the host. Settings: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the same secrets file as the keys.
  Without a token the step is skipped.
  - Set up once on the laptop (WSL, interactive: hidden token prompt, then press Start on the bot in Telegram):
    `PYTHONPATH=backend/src python3 -m btc_bot notify setup`, then `bash deploy/digitalocean/do.sh bot-keys`.
  - Test from the server: `bash deploy/digitalocean/do.sh bot notify test`.
  - Preview without sending: on the Droplet, in this folder,
    `docker compose --profile bot run --rm -T --no-deps bot btc-bot notify after-run --command dashboard --rc 0 --since 2026-11-17T23:10:00Z --print-only`.
  - Turn off: remove the two lines from the secrets file (laptop) and run `do.sh bot-keys` again.

**Rollback to the laptop** (do it at **23:20-23:50 UTC**, after the evening runs and before b-check). The Windows
tasks have StartWhenAvailable on, so re-enabling them can start a missed run at once. A late a-precheck/a-enter
started between 00:00 and 20:55 UTC is treated by the harness as the new day's window (it has no "too early" guard),
so never re-enable the tasks during the day:
1. `bash deploy/digitalocean/do.sh bot-off` (schedule off, sync login back).
2. `bash deploy/digitalocean/do.sh pull`.
3. Remove `DO_BOT_ON_SERVER` from `.env`.
4. In PowerShell: `Get-ScheduledTask -TaskName 'BTC bot*' | Enable-ScheduledTask`.

Never have both machines' schedules on at the same time.

## Day to day

- **Data** is written on the Droplet itself since the bot moved there (see above). Before that, the laptop synced it
  after every scheduled run (`do.sh sync`, logged in `data/paper/logs/sync.log`).
- **Code changes:** `bash deploy/digitalocean/do.sh push` copies the working tree (tracked and new files, without
  `data/`) and rebuilds.
- **Turn the mirror off:** remove `DO_HOST` from `.env` (syncing stops) and destroy the Droplet in the control panel.
- Ubuntu installs security updates by itself (unattended-upgrades). Docker images update only on `push`.
