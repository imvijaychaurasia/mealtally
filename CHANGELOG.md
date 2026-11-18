# Changelog

All notable changes to Mealtally are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until 1.0, a minor version may include changes that need
a step from you; [docs/upgrading.md](docs/upgrading.md) lists them.

## [Unreleased]

## [0.1.1] - 2026-11-18

### Security

- Fixed a redirect target check that accepted `/\host` (low severity; the form is CSRF-protected). Users of 0.1.0
  should upgrade.

### Fixed

- Every redirect that takes its target from the request now uses Django's `url_has_allowed_host_and_scheme` (found by
  CodeQL, `py/url-redirection`).
- `compose.prod.yml` no longer builds the database image on the server; it runs the published
  `mealtally-postgres` image (`MEALTALLY_POSTGRES_IMAGE` is now required, see docs/upgrading.md). `make upgrade` pulls
  it too.
- Sign-in redirects keep the full address of the page (including its query) and encode it.

## [0.1.0] - 2026-11-17

The first open-source release.

### Added

- **Meal passes:** plans with a price, a number of meals, a validity (fixed days or a calendar month), meal times and a
  daily limit. Selling a pass while one is active queues the renewal.
- **Redemption at the counter:** QR scan with the phone camera, or search by name, phone or customer code; one tap to
  redeem; double-scan protection; undo and manager override, each with a reason.
- **Customer app** (installable web app): meals left, a QR code that refreshes and works once, history, receipts,
  sign-in with phone and PIN.
- **Receipts:** numbered, on screen and as PDF.
- **Customers, staff and roles:** owner, manager, counter; temporary passwords and PINs that must be changed at first
  sign-in.
- **Audit log** of every change, append-only.
- **Reports:** daily consumption, monthly sales, expired passes, refused redemptions and customer statements, as CSV
  and PDF.
- **One restaurant or many:** single mode (default) and multi mode for hosting providers, with optional platform fees
  and fee statements.
- **Three themes:** Masala, Fresh and Mealtally, each checked for WCAG AA contrast.
- **Languages:** 13 languages, with right-to-left layout for Arabic. English is the source; Hindi is fully translated
  and Marathi, Tamil, Telugu, Bengali, Gujarati, Kannada, Spanish, French, Brazilian Portuguese, Arabic and Indonesian
  have the most-used screens drafted. All twelve are labelled Beta until native speakers review them.
- **Any country and currency:** amounts in the currency's minor units with CLDR formatting, phone numbers in the
  local format, local tax-ID and food-licence labels, UPI only where it applies.
- **Data safety:** PostgreSQL row-level security between restaurants, an append-only meal ledger, nightly backups and a
  tested `make restore`.
- **Running it:** Docker images for amd64 and arm64, `make init` / `make up` / `make demo` / `make upgrade`, plain
  HTTP by default with documented HTTPS set-ups (Caddy, Traefik, nginx).

### Preview

Screens with sample data, labelled "Preview" and off unless `MEALTALLY_DEMO_DATASET=on` (or `make demo`). They are
not working features yet: wallets and top-ups, orders, kitchen (cooking plan, packing, labels), delivery routes and
the driver screen, invoices, expenses, notifications, cloud kitchen, and the restaurant's own website.
