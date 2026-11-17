#!/bin/bash
# Run ON THE DROPLET to set or change the dashboard login:  bash /opt/btc-strategy/deploy/digitalocean/set-password.sh
# The password is read from the terminal, hashed with bcrypt by Caddy, and only the hash is stored (auth.caddy).
set -euo pipefail
cd "$(dirname "$0")"

read -rp "Dashboard username: " user
[[ "$user" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || { echo "Use letters, digits, '.', '_' or '-' only." >&2; exit 1; }
read -rsp "Password (12+ characters): " pw; echo
read -rsp "Same password again: " pw2; echo
[ "$pw" = "$pw2" ] || { echo "The two passwords differ; nothing changed." >&2; exit 1; }
[ "${#pw}" -ge 12 ] || { echo "Too short; nothing changed." >&2; exit 1; }

image=$(sed -nE 's/^ *image: *(caddy:[^ ]+).*/\1/p' compose.yml | head -1)
hash=$(printf '%s\n' "$pw" | docker run --rm -i "$image" caddy hash-password)
unset pw pw2
[[ "$hash" == \$2* ]] || { echo "Hashing failed; nothing changed." >&2; exit 1; }

umask 022
# Written in place, not renamed: the container bind-mounts this one file, and a rename would leave it the old copy.
printf 'basic_auth {\n\t%s %s\n}\n' "$user" "$hash" > auth.caddy
docker compose restart caddy >/dev/null
echo "Login set for '$user'. Caddy restarted."
