# Deploying DART

Gets the tool onto a public HTTPS URL you can share with anyone.

## What you need first

- **A server.** Ubuntu 22.04 or 24.04, 2 GB RAM, 20 GB disk.
  Hetzner CX22 (~€4/mo) or a DigitalOcean $6 droplet both work.
  The RAM matters: DuckDB queries a 107 MB parquet in memory.
- **A domain**, with an `A` record pointing at the server's IP.
  A subdomain is fine (`dart.yourdomain.com`). Without one you get
  no HTTPS — see *No domain yet* below.

## Deploy

From your machine, copy the project up and run the installer:

```bash
scp -r "Claude Code VSC" root@YOUR_SERVER_IP:/root/dart-src
ssh root@YOUR_SERVER_IP
cd /root/dart-src
sudo bash deploy/setup.sh dart.yourdomain.com
```

That takes about ten minutes, most of it rebuilding the place data. It:

1. installs Python and Caddy
2. creates a `dart` service account and `/opt/dart`
3. builds `places-ca.parquet` from Overture (~4 min), the FSA boundary layer,
   and the city/province index
4. registers a systemd service that restarts on failure and on boot
5. points Caddy at it and fetches a certificate

The data is **rebuilt on the server**, not uploaded — the parquet is 107 MB and
`fetch_overture.py` recreates it in four minutes.

## First sign-in

The first start generates a manager password into the journal:

```bash
journalctl -u dart | grep -A3 'Manager account'
```

Sign in at `https://dart.yourdomain.com/manager.html`, then **change that
password** and add your team from the Team screen.

Two portals:

| URL | Who |
|---|---|
| `/manager.html` | Managers — every campaign, every client, team management |
| `/login.html` | Media Account Consultants and Direct Mail Experts — their own and assigned campaigns |

## Running it

```bash
systemctl status dart        # is it up
journalctl -u dart -f        # live logs
systemctl restart dart       # after a code change
```

## Updating

```bash
scp -r serve.py crm.py yp-site root@YOUR_SERVER_IP:/opt/dart/
ssh root@YOUR_SERVER_IP 'chown -R dart:dart /opt/dart && systemctl restart dart'
```

`data/app.db` holds campaigns, clients and users, and is never overwritten by
an update.

## Refreshing the business data

Overture publishes roughly monthly. To pick up a new release, edit `RELEASE`
in `fetch_overture.py`, then:

```bash
cd /opt/dart
sudo -u dart venv/bin/python fetch_overture.py
sudo -u dart venv/bin/python build_fsa.py
sudo -u dart venv/bin/python build_places_index.py
systemctl restart dart
```

## Back it up

Everything that can't be rebuilt is in one SQLite file:

```bash
sqlite3 /opt/dart/data/app.db ".backup '/root/dart-$(date +%F).db'"
```

Worth a nightly cron. The parquet and geojson are reproducible from the
scripts, so they don't need backing up.

## No domain yet

Caddy needs a real domain to issue a certificate. Two ways around it:

- **A free subdomain** from DuckDNS or similar, pointed at the server IP, then
  use that as the domain argument.
- **A Cloudflare quick tunnel**, no domain and no server needed, but the URL
  changes each run and it dies when you close the terminal:

  ```bash
  cloudflared tunnel --url http://localhost:8787
  ```

## Security notes

The installer covers these; worth knowing what they are.

- `serve.py` binds to `127.0.0.1` only. Caddy is the sole public entrance.
- Session cookies get `Secure` in production via `DART_SECURE_COOKIES=1`
  in the unit file, alongside `HttpOnly` and `SameSite=Lax`.
- Failed sign-ins are capped at 10 per IP per 5 minutes, then 429.
- Passwords are scrypt with per-user salts.
- systemd runs the service unprivileged with `ProtectSystem=strict`; the only
  writable path is `data/`.

Two things the installer does **not** do, worth doing yourself:

- **A firewall.** `ufw allow 22,80,443/tcp && ufw enable`.
- **Unattended upgrades.** `apt install unattended-upgrades`.
