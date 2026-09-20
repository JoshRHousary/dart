#!/usr/bin/env bash
# One-shot provisioning for a fresh Ubuntu 22.04/24.04 server.
#
#   sudo bash deploy/setup.sh dart.example.com
#
# Installs Python + Caddy, builds the place data, registers the systemd
# service and gets an HTTPS certificate for the domain.
set -euo pipefail

DOMAIN="${1:-}"
APP_USER="dart"
APP_DIR="/opt/dart"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "$DOMAIN" ]]; then
  echo "Usage: sudo bash deploy/setup.sh <domain>" >&2
  echo "  e.g. sudo bash deploy/setup.sh dart.example.com" >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo." >&2
  exit 1
fi

say() { printf "\n\033[1;33m==> %s\033[0m\n" "$1"; }

say "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl debian-keyring \
                      debian-archive-keyring apt-transport-https ca-certificates

if ! command -v caddy >/dev/null; then
  say "Installing Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
fi

say "Creating the service account and app directory"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"
cp -r "$REPO_DIR"/{serve.py,crm.py,fetch_overture.py,build_fsa.py,build_places_index.py,yp-site} "$APP_DIR"/
mkdir -p "$APP_DIR/data"

say "Creating the virtualenv"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet duckdb openpyxl

if [[ ! -f "$APP_DIR/data/places-ca.parquet" ]]; then
  say "Building the place data (about 4 minutes)"
  (cd "$APP_DIR" && sudo -u "$APP_USER" "$APP_DIR/venv/bin/python" fetch_overture.py)
fi

if [[ ! -f "$APP_DIR/yp-site/fsa.geojson" ]]; then
  say "Fetching Statistics Canada FSA boundaries"
  mkdir -p "$APP_DIR/data/fsa"
  curl -sL -o "$APP_DIR/data/fsa/fsa2021.zip" \
    "https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/files-fichiers/lfsa000b21a_e.zip"
  (cd "$APP_DIR/data/fsa" && python3 -c "import zipfile;zipfile.ZipFile('fsa2021.zip').extractall('.')")
  say "Building the postal-area layer"
  (cd "$APP_DIR" && "$APP_DIR/venv/bin/python" build_fsa.py)
fi

if [[ ! -f "$APP_DIR/yp-site/places-index.js" ]]; then
  say "Building the city and province index"
  (cd "$APP_DIR" && "$APP_DIR/venv/bin/python" build_places_index.py)
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

say "Registering the service"
sed "s|__APP_DIR__|$APP_DIR|g; s|__APP_USER__|$APP_USER|g" \
  "$REPO_DIR/deploy/dart.service" > /etc/systemd/system/dart.service
systemctl daemon-reload
systemctl enable --now dart

say "Configuring Caddy for $DOMAIN"
sed "s|__DOMAIN__|$DOMAIN|g" "$REPO_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

sleep 3
say "Status"
systemctl --no-pager --lines=5 status dart || true
echo
echo "  Site:  https://$DOMAIN"
echo "  Logs:  journalctl -u dart -f"
echo
echo "  The first start prints a generated manager password to the log."
echo "  Read it with:  journalctl -u dart | grep -A3 'Manager account'"
echo "  Sign in at https://$DOMAIN/manager.html and change it from the Team screen."
