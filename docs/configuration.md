# Configuration

Mealtally reads all its configuration from environment variables, normally from the `.env` file next to
`compose.yaml`. `.env.example` lists the common ones with comments; `make init` copies it to `.env` and fills in
the secrets that are still empty, never overwriting a value you set.

After changing `.env`, restart: `make up` (or `docker compose -f compose.prod.yml up -d` in production).

## Address and HTTPS

| Variable | Default | What it does |
|---|---|---|
| `MEALTALLY_BASE_URL` | `http://localhost:8000` | The address people type. It sets the allowed host name, the trusted origin for forms, and the links in emails, PDFs and QR codes. `https://` turns on secure cookies, the HTTPS redirect and HSTS; `http://` leaves them off. |
| `MEALTALLY_PORT` | `8000` | The port on the host. |
| `MEALTALLY_BIND` | `0.0.0.0` | The host address the port listens on. `127.0.0.1` when a proxy on the same machine is the only way in. |
| `MEALTALLY_TRUST_PROXY` | `false` | `true` only behind a reverse proxy that sets `X-Forwarded-Proto` and `X-Forwarded-For`. Mealtally then trusts those headers (for HTTPS detection and client IPs). Never turn it on without a proxy: anyone could fake the headers. |
| `MEALTALLY_EXTRA_HOSTS` | empty | More host names to accept, comma-separated (for example a second domain). |
| `MEALTALLY_EXTRA_ORIGINS` | empty | More trusted origins for forms, comma-separated, with scheme. |
| `MEALTALLY_HSTS_SECONDS` | `31536000` | HSTS lifetime on `https://`. |
| `MEALTALLY_HSTS_INCLUDE_SUBDOMAINS` | `false` | Add `includeSubDomains` to HSTS. |
| `MEALTALLY_HSTS_PRELOAD` | `false` | Add `preload`. Hard to undo; only if you mean to submit the domain to the preload list. |

On plain `http://`, phones only allow the camera and app installation on `localhost`. See
[deploy.md](deploy.md#plain-http-and-its-limits).

## Mode and features

| Variable | Default | What it does |
|---|---|---|
| `MEALTALLY_MODE` | `single` | `single`: one restaurant; `/` opens it. `multi`: many restaurants (a hosting provider); `/` shows a "find your restaurant" page and the platform admin can onboard restaurants. |
| `MEALTALLY_ENV` | `production` | `development` allows `make demo`. |
| `MEALTALLY_PLATFORM_FEES` | `off` | Platform fees on payments and monthly fee statements (multi mode). |
| `MEALTALLY_MARKETING_SITE` | `off` | A product landing page at `/` with a demo-request form. |
| `MEALTALLY_DEMO_DATASET` | `off` | New restaurants show the Preview modules with sample data. |
| `MEALTALLY_LEGAL_PAGES` | `off` | Privacy notice and terms pages, built from the templates in `mealtally/templates/legal/` and the operator details in the platform settings. They stay hidden until the required details are filled in. |

Switches accept `on`/`off`, `true`/`false`, `yes`/`no` or `1`/`0`.

## First restaurant and defaults

| Variable | Default | What it does |
|---|---|---|
| `MEALTALLY_ADMIN_EMAIL` | (required) | `make init` creates the platform admin with this email. |
| `MEALTALLY_RESTAURANT_NAME` | `My Restaurant` | Single mode: the restaurant `make init` creates. Change the name later in Settings. |
| `MEALTALLY_DEFAULT_COUNTRY` | `IN` | ISO 3166 country of new restaurants: phone format, tax-ID label, payment methods. |
| `MEALTALLY_DEFAULT_CURRENCY` | `INR` | ISO 4217 currency of new restaurants. Set it before selling: amounts are not converted later. |
| `MEALTALLY_DEFAULT_TIMEZONE` | `Asia/Kolkata` | Time zone of new restaurants (meal times, pass validity, reports). |
| `MEALTALLY_DEFAULT_LANGUAGE` | `en` | Language for people who haven't picked one, until the restaurant sets its own default. |
| `MEALTALLY_MEAL_SLOTS_FILE` | built-in | A JSON file with the default meal times for new restaurants (see `mealtally/plans/seed/meal_slots.json`). |

Each restaurant can change its country, currency, time zone and default language later in Settings.

## Secrets

`make init` generates these if they are empty. Keep `.env` private (`chmod 600`) and in your backups.

| Variable | What it is |
|---|---|
| `DJANGO_SECRET_KEY` | Signs sessions and tokens. Changing it signs everyone out. |
| `POSTGRES_PASSWORD` | The database superuser, used for setup and backups. |
| `MEALTALLY_DB_OWNER_PASSWORD` | `mealtally_owner`, which owns the tables and runs migrations. |
| `MEALTALLY_DB_APP_PASSWORD` | `mealtally_app`, which the application uses. |

The database passwords are written into the database when its volume is first created. Changing them in `.env`
afterwards needs the matching `ALTER ROLE ... PASSWORD` in PostgreSQL.

## Database and cache

| Variable | Default | What it does |
|---|---|---|
| `POSTGRES_DB` | `mealtally` | Database name. |
| `POSTGRES_USER` | `mealtally_admin` | The bootstrap superuser. |
| `POSTGRES_HOST` | `postgres` | Database host (the Compose service). |
| `POSTGRES_PORT` | `5432` | Database port. |
| `CONN_MAX_AGE` | `60` | Seconds a database connection is reused. |
| `DATABASE_URL`, `DATABASE_OWNER_URL` | empty | Alternatively, full URLs for the app and owner connections (an external PostgreSQL). |
| `REDIS_URL` | `redis://valkey:6379/0` | Valkey or Redis 7+, for the cache, QR codes, sign-in lockouts and Celery. |

## Email

Without email, new PINs and passwords are shown on screen once, and password reset by email doesn't work.

| Variable | Default | What it does |
|---|---|---|
| `DJANGO_EMAIL_BACKEND` | SMTP | Django email backend. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | port 587, TLS on | SMTP server. |
| `MEALTALLY_FROM_EMAIL` | `Mealtally <noreply@` + your host `>` | Sender address. |
| `MEALTALLY_EMAIL_SUBJECT_PREFIX` | `[Mealtally] ` | Prefix of admin emails. |

## Backups

| Variable | Default | What it does |
|---|---|---|
| `MEALTALLY_BACKUP_AT_UTC` | `20:30` | When the nightly dump runs, in UTC (`compose.prod.yml`). If the server was off at that time, a dump runs as soon as it is back. |
| `MEALTALLY_BACKUP_RETENTION_DAYS` | `14` | How many days of dumps to keep in `./backups`. |

## Limits

| Variable | Default | What it does |
|---|---|---|
| `MEALTALLY_THROTTLE_LOGIN` | `30/10min` | API sign-in attempts per client IP. |
| `MEALTALLY_THROTTLE_REDEEM_USER` | `60/min` | Redemptions per counter user. |
| `MEALTALLY_THROTTLE_REDEEM_TENANT` | `300/min` | Redemptions per restaurant. |
| `AXES_ENABLED` | `true` | Lock an identity for 15 minutes after 5 failed sign-ins. |

## Production image

| Variable | Default | What it does |
|---|---|---|
| `MEALTALLY_IMAGE` | (required in `compose.prod.yml`) | The application image, for example `ghcr.io/<owner>/mealtally:0.1.0`. |
| `MEALTALLY_POSTGRES_IMAGE` | built locally | The database image with the role setup, for example `ghcr.io/<owner>/mealtally-postgres:0.1.0`. |
| `WEB_CONCURRENCY` | `3` | gunicorn worker processes. |

## Optional

| Variable | Default | What it does |
|---|---|---|
| `MEALTALLY_WHATSAPP_SUPPORT_NUMBER` | empty | Shows a "Chat with us on WhatsApp" link in the help drawer. |
| `SENTRY_DSN` | empty | Send errors to Sentry. |
| `SENTRY_ENVIRONMENT` | `production` | Sentry environment name. |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.0` | Sentry performance sampling. |
| `DJANGO_CORS_ALLOWED_ORIGINS` | empty | Origins allowed to call the API from a browser on another domain. |
