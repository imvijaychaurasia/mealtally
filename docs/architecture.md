# Architecture

This page explains how Mealtally is built and why. It replaces the decision records kept while the code was private.
Read it before changing models, money, tenancy or the counter.

## The shape of the code

Mealtally is one Django project with one app per area, under `mealtally/`:

| App | What it owns |
|---|---|
| `tenancy` | Restaurants (tenants), their settings, row-level security, first-run commands |
| `accounts` | Users, staff memberships and roles, sign-in |
| `plans` | Meal plans, meal times and the meal rules |
| `customers` | Customers, PINs, QR codes |
| `billing` | Payments, receipts, platform fees |
| `passes` | Meal passes: validity, queueing, expiry |
| `ledger` | The meal ledger: every meal issued, redeemed, reversed or expired |
| `audit` | The audit log |
| `api` | The JSON API (`/api/v1/`) |
| `web` | Server-rendered screens |
| `preview` | The Preview modules: screens filled from a sample dataset |
| `common` | Shared code: errors, money, countries, time (not a Django app) |

**Business rules live in each app's `services.py`.** Views, the API, management commands and Celery tasks all call
the same service functions. A view validates input, finds the restaurant and the person acting, and calls a service.
An app writes to another app's tables only through that app's services; reading another app's models directly is
fine.

## Restaurants and isolation

Every restaurant's URLs live under `/t/<code>/`. Opening a page looks up the restaurant and the visitor's membership
there; someone who isn't a member gets a 404, so restaurant codes can't be probed.

Isolation is enforced by **PostgreSQL row-level security** on every restaurant-owned table, with both `ENABLE` and
`FORCE`:

- Each request runs in a transaction that sets `app.tenant_id` (or `app.platform` for platform screens) with
  `SET LOCAL`. The policies compare each row's `tenant_id` with that setting. With no setting, a query sees no rows.
- The application connects as `mealtally_app`, a role that owns nothing and cannot bypass the policies.
  Migrations run as `mealtally_owner`, which owns the tables and is itself subject to `FORCE`. The bootstrap superuser
  is only used for setup, backups and tests.
- A model manager adds `WHERE tenant_id = ...` on top, so queries use the indexes.
- `manage.py check_rls` runs on every start and in the tests, and fails if any restaurant table lacks a policy.
- The test suite runs as a non-superuser role, so isolation is tested against the database, not only the ORM.

Users are global (one person can be a customer at several restaurants); memberships and customers belong to one
restaurant. Platform screens use an explicit platform context, which is easy to find in the code.

In single-restaurant mode (the default) the same machinery runs with one tenant, and `/` goes straight to it.

## The ledger

Meals are never counted in a mutable field alone. Every change is a row in the **meal ledger**: `ISSUE` when a pass
starts, `REDEEM` at the counter, `REVERSAL` for an undo, `ADJUST` for a correction by the owner, `EXPIRE` when a pass
ends. A pass's balance is the sum of its entries, and the cached `meals_remaining` is checked against it nightly.

The ledger, the audit log and the platform-fee entries are **append-only**. A database trigger rejects `UPDATE`,
`DELETE` and `TRUNCATE`, and the application role isn't granted those rights either. Mistakes are corrected with
new rows that point at the old ones, and corrections need a reason.

## Redeeming a meal

1. The customer's app shows a QR code holding a random 12-character code that the server keeps in Valkey for 90
   seconds. The app fetches a new one before it runs out. (API clients can use a signed token instead.)
2. The counter scans it with the phone camera (zxing), or staff search by name, phone or code, or type the code
   printed under the QR.
3. The server checks the code (known, not expired, not used), the pass (active, meals left), the restaurant (not
   paused) and the meal rules (meal time, one meal per meal time, daily limit), then writes a `REDEEM` entry.

A code works once: the first scan claims it in Valkey with `SET NX`, so two counters scanning the same code at the
same moment give one meal. Each customer card on the counter also carries an idempotency key, so a double tap or a
network retry is replayed, not counted twice. A cooldown asks before serving the same customer again within a few
seconds. Valkey is used fail-closed: if it is down, redemption stops rather than skipping these checks.

The counter needs a connection; there is no offline redemption.

## Passes

- A plan has a price, a number of meals and a validity: a number of days (ending at the end of the last day, in the
  restaurant's time zone) or a calendar month (ending on the month's last day, with all meals and no proration).
- Selling a pass while one is active queues the new one; it starts when the current one ends. A queued pass has no
  meals until it starts, so the ledger and the balance always agree.
- A job every five minutes starts due passes and expires ended ones. Expiry writes an `EXPIRE` entry for the meals
  left.
- Voiding a payment is allowed only while its pass has no redemptions.

## Sign-in

- Staff and platform admins sign in with email or phone and a password (Argon2; at least 10 characters).
  Passwords set by someone else must be changed at first sign-in.
- Customers sign in with the restaurant, their phone number and a PIN. The PIN is generated by the server, shown once,
  stored hashed, and changed by the customer at first sign-in.
- Failed sign-ins lock that identity (not the IP address) for 15 minutes after 5 attempts. The API also has rate
  limits for sign-in and redemption.
- Roles are owner, manager, counter, and the Preview roles chef and driver. Permissions are one table in
  `accounts/policy.py`; `is_platform_admin` is the only platform flag the code checks.

## Money, countries and languages

- Amounts are **integers in the currency's minor unit** (paise, cents; none for yen) with the restaurant's ISO 4217
  currency. They are formatted only by `mealtally.common.money`, which uses CLDR data through Babel: the active
  language plus the restaurant's country picks the format (`₹1,24,325.00` in India, `$124,325.00` in the US).
- Phone numbers are stored in E.164 and shown in the restaurant country's own format.
- The restaurant's country decides the tax-ID label (GSTIN, VAT number or tax ID), the food-licence label and
  whether UPI is offered.
- All visible text is translatable. Layout uses logical CSS properties, and every page sets `dir="rtl"` for
  right-to-left languages. See [TRANSLATING.md](../TRANSLATING.md).

## Screens

- Server-rendered Django templates, **HTMX** for partial updates and **Alpine.js** (CSP build) for small bits of state.
  CSS is **Tailwind 4**, compiled in a Docker build stage with the standalone CLI, so no image contains Node.
- All JavaScript is vendored under `mealtally/static/vendor/` and served by WhiteNoise. No CDN.
- The **Content-Security-Policy** is strict: scripts and styles only from the site itself, no inline code. Two paths
  relax it, both for platform admins only: the Django admin (inline styles) and the API docs (Swagger UI).
- **Themes**: every colour is a CSS variable in `static/css/themes.css` under `[data-theme=...]`. Templates use
  semantic classes (`bg-card`, `text-muted`), and a test fails on raw colours. Another test checks that every text and
  background pair meets WCAG AA contrast in every theme.
- PDFs (receipts, reports) are rendered by WeasyPrint from the same templates as the screens.
- The customer app is an installable PWA. The service worker caches only the offline page.

## Preview modules

Wallets, orders, kitchen, delivery, invoices, expenses, notifications, cloud kitchen and the restaurant website are
**Preview** modules: real screens in the real layout, filled from a deterministic sample dataset built in memory
(`mealtally.preview.data`). They never write to the database. They appear only for restaurants with
`has_demo_dataset` (off unless `MEALTALLY_DEMO_DATASET=on` or the restaurant came from `make demo`) and carry a
"Preview" badge. Other restaurants see "Coming soon". `mealtally.preview.registry` lists them; when one becomes real,
its status changes there.

## Background jobs

Celery with Valkey as the broker. The schedule is fixed in settings (`CELERY_BEAT_SCHEDULE`), not stored in the
database: pass activation and expiry every five minutes, and a nightly ledger reconciliation. Jobs are idempotent and
lock rows with `SKIP LOCKED`, so a duplicate run does no harm. Run exactly one `beat` container.

## Deployment

One image runs the web server (gunicorn), the worker and beat. On start, the web container migrates as the owner
role, sets up the database roles and grants, and checks row-level security before serving. Mealtally doesn't
terminate TLS; put a reverse proxy in front for HTTPS ([deploy.md](deploy.md)).
