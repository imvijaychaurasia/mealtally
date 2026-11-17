# Security policy

## Reporting a vulnerability

**Please don't open a public issue for security problems.**

Report them privately through GitHub: on the repository page, open **Security → Report a vulnerability**. Only the
maintainers can see the report.

Please include:

- what an attacker can do and what they need first (for example "a counter login at one restaurant"),
- the steps or a request that shows it,
- the version or commit you tested.

You can expect an answer within 5 working days. We'll agree a disclosure date with you, credit you in the release
notes if you want, and publish a GitHub security advisory once a fix is released.

## Supported versions

Security fixes go into the latest `0.x` release and `main`. Until 1.0, upgrade to the latest release to get them.

## Scope

In scope: the Mealtally code in this repository and the official container images.

Out of scope: how a particular instance is run (its TLS, proxy, backups or passwords), denial of service by sheer
request volume, and findings that need an already-compromised server or platform-admin account.

## What the design already protects

These are worth knowing before you test, and a break in any of them is a serious bug:

- **Tenant isolation is enforced by PostgreSQL row-level security**, not only by the application. The application
  connects as a role that cannot bypass it.
- **The ledger and audit log are append-only**: database triggers reject `UPDATE`, `DELETE` and `TRUNCATE`.
- **QR codes are single-use and short-lived**, and a meal is redeemed at most once even when two counters scan at the
  same moment.
- **Logins are rate-limited** (django-axes for passwords, a separate limit for customer PINs).
