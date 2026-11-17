# Changelog

All notable changes to Mealtally are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until 1.0, a minor version may include changes that need
a step from you; [docs/upgrading.md](docs/upgrading.md) lists them.

## [Unreleased]

## [0.1.0] - unreleased

The first open-source release.

### Ready

- Prepaid meal passes: plans with price, number of meals, validity (fixed days or calendar month), meal times and a
  daily limit. Renewals queue behind the current pass.
- Counter: QR scan or search by name, phone or code; redeem in one tap; protection against double scans; undo and
  override with a reason; sell a pass with a numbered receipt (PDF).
- Customer web app (installable): meals left, a refreshing QR code, history, receipts, PIN sign-in.
- Customers, staff and roles (owner, manager, counter), with an audit log of every change.
- Reports: daily consumption, monthly sales, expired passes, refused redemptions, customer statements (CSV and PDF).
- Single-restaurant mode (default) and multi-restaurant mode for hosting providers, with optional platform fees.
- Any country and currency: amounts in the currency's minor units, CLDR formatting, phone numbers in local format,
  local tax-ID and food-licence labels. UPI only where it applies (India).
- Languages: English; Hindi fully translated (Beta until reviewed); Marathi, Tamil, Telugu, Bengali, Gujarati, Kannada, Spanish, French,
  Brazilian Portuguese, Arabic and Indonesian in Beta. Right-to-left layout for Arabic.
- Three themes.
- Data safety: PostgreSQL row-level security between restaurants, an append-only ledger and audit log, nightly
  backups and a tested restore.

### Preview

Shown with sample data and labelled "Preview", off unless `MEALTALLY_DEMO_DATASET=on`: wallets and top-ups, orders,
kitchen, delivery routes and the driver screen, invoices, expenses, notifications, cloud kitchen, restaurant website.
