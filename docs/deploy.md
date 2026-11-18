# Deploying Mealtally

This page covers running Mealtally for real: on a small server or a computer at the restaurant, with HTTPS if people
reach it from their phones, and with backups.

## What you need

- A Linux machine (amd64 or arm64) with 2 GB of memory and Docker with Compose v2.
- For HTTPS: a domain name pointing at the machine, or a local certificate authority on a private network.

Mealtally runs PostgreSQL 18 and Valkey 8 in containers. To use your own database instead, see `DATABASE_URL` in
[configuration.md](configuration.md): it needs PostgreSQL 16 or newer and two roles set up as in
`docker/postgres/initdb/10-roles.sh`.

## Install

Production uses the released images and `compose.prod.yml`. You need the repository files for the Compose file,
the backup script and `.env.example`:

```bash
git clone --branch v0.1.1 https://github.com/<owner>/mealtally.git
```

```bash
cd mealtally && cp .env.example .env && chmod 600 .env
```

Edit `.env`:

- `MEALTALLY_BASE_URL`: the address people will type, for example `https://meals.example.com` or
  `http://192.168.1.20:8000`.
- `MEALTALLY_ADMIN_EMAIL`: your login.
- `MEALTALLY_RESTAURANT_NAME`, and `MEALTALLY_DEFAULT_COUNTRY`, `MEALTALLY_DEFAULT_CURRENCY`, `MEALTALLY_DEFAULT_TIMEZONE`
  (required; without them `make init` asks, or stops when it has no terminal).
- `MEALTALLY_IMAGE=ghcr.io/<owner>/mealtally:0.1.1` and `MEALTALLY_POSTGRES_IMAGE=ghcr.io/<owner>/mealtally-postgres:0.1.1`
  (both required: production runs the published images and never builds them).

Then:

```bash
COMPOSE_FILE=compose.prod.yml make init
```

`make init` generates the secrets, starts the stack and creates your admin login. It prints the password once; you
change it at the first sign-in. In single-restaurant mode it also creates the restaurant, with you as its owner.

Everyday production commands use `compose.prod.yml` too:

```bash
docker compose -f compose.prod.yml ps
```

```bash
docker compose -f compose.prod.yml logs -f web
```

## Plain HTTP and its limits

Out of the box Mealtally serves plain HTTP on port 8000 of every network interface. On a private network that may be
all you need, with one important limit: **browsers only allow the camera and app installation on HTTPS or on
`localhost`.** On `http://192.168.1.20:8000`:

- the counter can't scan QR codes with the phone camera. Staff can still type the 12-character code shown under the
  customer's QR, or search by name or phone;
- customers can't install the app to their home screen. The website still works in the browser.

While the address is plain HTTP and not `localhost`, Mealtally shows owners, managers and the platform admin a
banner that explains this. Any of the
three set-ups below removes the limit.

In every set-up, Mealtally itself stays on plain HTTP behind the proxy and never handles certificates. Set:

```dotenv
MEALTALLY_BASE_URL=https://meals.example.com
MEALTALLY_TRUST_PROXY=true
MEALTALLY_BIND=127.0.0.1
```

`MEALTALLY_TRUST_PROXY=true` makes Mealtally believe the proxy's `X-Forwarded-Proto` and `X-Forwarded-For` headers.
`MEALTALLY_BIND=127.0.0.1` keeps port 8000 off the network, so the proxy is the only way in. If the proxy runs in
another container, leave `MEALTALLY_BIND` at `0.0.0.0` and block port 8000 in the firewall instead.

### Caddy (simplest)

Caddy gets and renews a Let's Encrypt certificate on its own. Install Caddy on the host, then
`/etc/caddy/Caddyfile`:

```caddyfile
meals.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

On a private network without a public domain, Caddy can use its own local certificate authority instead: replace
the site address with `meals.internal` and add `tls internal`, then install Caddy's root certificate on the phones.

### Traefik with Let's Encrypt

Add Traefik to the Compose project with an override file, `compose.traefik.yml`:

```yaml
services:
  traefik:
    image: docker.io/traefik:v3.5
    restart: unless-stopped
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=:80
      - --entrypoints.web.http.redirections.entrypoint.to=websecure
      - --entrypoints.websecure.address=:443
      - --certificatesresolvers.le.acme.email=you@example.com
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.le.acme.httpchallenge.entrypoint=web
    ports: ["80:80", "443:443"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - letsencrypt:/letsencrypt
  web:
    labels:
      - traefik.enable=true
      - traefik.http.routers.mealtally.rule=Host(`meals.example.com`)
      - traefik.http.routers.mealtally.entrypoints=websecure
      - traefik.http.routers.mealtally.tls.certresolver=le
      - traefik.http.services.mealtally.loadbalancer.server.port=8000
volumes:
  letsencrypt: {}
```

```bash
docker compose -f compose.prod.yml -f compose.traefik.yml up -d
```

Here Traefik reaches `web` over the Compose network, so keep `MEALTALLY_BIND=0.0.0.0` and close port 8000 in the
firewall. For a server that isn't reachable from the internet, use the DNS challenge instead of the HTTP challenge:
replace the `httpchallenge` line with `--certificatesresolvers.le.acme.dnschallenge.provider=<your DNS provider>` and
pass the provider's API token as an environment variable (see Traefik's ACME documentation for the variable names).

### nginx with certbot

```nginx
server {
    listen 80;
    server_name meals.example.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 10m;
    }
}
```

```bash
sudo certbot --nginx -d meals.example.com
```

certbot adds the `listen 443 ssl` block and the certificate paths to this file and renews the certificate on a
timer.

### A local certificate authority on a private network

With no domain at all, create a certificate with [mkcert](https://github.com/FiloSottile/mkcert) for the server's
address, use it in Caddy or nginx above, and install mkcert's root certificate on each phone and tablet that uses
Mealtally. That is more work per device than a domain with Let's Encrypt, but nothing leaves the network.

## Backups

`compose.prod.yml` includes a `backup` service. Every night at `MEALTALLY_BACKUP_AT_UTC` it writes a compressed
PostgreSQL dump to `./backups/` and deletes dumps older than `MEALTALLY_BACKUP_RETENTION_DAYS` (14 by default). If
the server was off at the scheduled time, it makes the dump as soon as it starts again.

Make one by hand at any time:

```bash
COMPOSE_FILE=compose.prod.yml make backup
```

**Copy `./backups/` and `.env` off the machine.** A backup on the same disk doesn't survive that disk. Any tool that
copies files works: `rsync` to another machine, `rclone` to cloud storage, or a USB disk. Without `.env`, a dump can
still be restored, but everyone has to sign in again.

### Restoring

```bash
COMPOSE_FILE=compose.prod.yml make restore FILE=backups/mealtally-20261117T203000Z.dump
```

This stops the application, replaces **all** data in the database with the dump, and starts it again. It asks you to
type `restore` first.

To restore onto a new machine: install as above with the same `.env`, run `make init`, then `make restore`.

**Test a restore** now and then on a second machine or a copy, so you know the dumps work before you need one.

## Updating

See [upgrading.md](upgrading.md).

## Checking it is healthy

- `GET /healthz` answers `200` when the application, the database and Valkey respond. The `web` container uses it as its
  health check.
- `docker compose -f compose.prod.yml ps` should show every service as running, and `web` and `postgres` as healthy.
- Errors are in `docker compose -f compose.prod.yml logs web worker`. Set `SENTRY_DSN` to collect them in Sentry.

## Security checklist

- `.env` is mode 600 and not in any repository.
- Port 8000 is reachable only from where it should be (the proxy, or the restaurant's network).
- `MEALTALLY_TRUST_PROXY` is `true` only behind a proxy.
- Backups are copied off the machine.
- The platform admin password was changed at first sign-in, and staff passwords are personal.
