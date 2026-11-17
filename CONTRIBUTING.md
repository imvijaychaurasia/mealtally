# Contributing to Mealtally

Thanks for helping. Bug reports, fixes, translations and documentation are all welcome.

## Before you start

- **Bugs:** open an issue with the bug template. Say what you did, what you expected and what happened.
- **Features:** open an issue first and describe the problem it solves for a restaurant. That saves you building
  something we can't merge.
- **Security problems:** don't open an issue; follow [SECURITY.md](SECURITY.md).
- **Translations:** see [TRANSLATING.md](TRANSLATING.md).

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## Contributor licence agreement

Before your first pull request can be merged you sign the [CLA](CLA.md). A bot comments on the pull request with the
sentence to reply with; it takes a minute and covers all your future contributions. You keep the copyright in your
work. The CLA lets the maintainer also offer Mealtally under a [commercial licence](COMMERCIAL.md).

## Development setup

You need Docker with Compose v2, `make`, and git. Python on the host is optional (for running ruff locally).

Fork the repository on GitHub, clone your fork, then:

```bash
cd mealtally
cp .env.example .env
```

In `.env`, set `MEALTALLY_ENV=development` and `MEALTALLY_ADMIN_EMAIL=you@example.com`, then run `make init`; it asks
for a country, currency and time zone (the test suite itself always uses India):

```bash
make init
```

```bash
make demo
```

`make demo` fills two demo restaurants and writes their logins to `.demo-credentials`. Open http://localhost:8000.

Everyday commands (`make help` lists them all):

| Command | What it does |
|---|---|
| `make test` | Full test suite with coverage (must stay at 95% or more) |
| `make lint` | ruff check and format check |
| `make smoke` | Playwright smoke suite against the running stack |
| `make messages` | Extract and compile translations |
| `make migrate` | Apply migrations |
| `make logs` | Follow the logs |

## How the code is organised

Read [docs/architecture.md](docs/architecture.md) first. The rules that matter most:

- **Money is integer minor units** (paise, cents) with an ISO currency; format it only through
  `mealtally.common.money`.
- **Every tenant-owned table has row-level security.** New models inherit `TenantOwnedModel`, and the migration adds
  the policy (copy an existing `0002_database_security.py`).
- **The ledger and audit log are append-only.** Corrections are new entries that reverse old ones.
- **Business rules live in `services.py`**, not in views. Views and the API call the same services.
- **Every visible string is translatable** and **layout uses logical CSS** (`ms-*`, `text-start`) so right-to-left
  languages work. Tests check both.
- **No inline scripts or styles**: the Content-Security-Policy is strict. Put JavaScript in `mealtally/static/js/`.

## Pull requests

- One topic per pull request, with tests. Bug fixes start with a test that fails without the fix.
- `make lint` and `make test` pass locally.
- New source files start with `# SPDX-License-Identifier: AGPL-3.0-only` (`scripts/spdx.py` adds it).
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/): `fix: ...`, `feat: ...`,
  `docs: ...`, `test: ...`, `chore: ...`. CI checks this.
- If you change a model, include the migration (`python manage.py makemigrations`); CI fails on a missing one.
- If you change visible text, run `make messages` and commit the `.po` and `.mo` files.
- Screens you changed: attach a screenshot, phone width and desktop.

## Releases

Maintainers tag `vX.Y.Z` (Semantic Versioning). The release workflow builds the images for amd64 and arm64 and
publishes them to GitHub Container Registry. Changes are listed in [CHANGELOG.md](CHANGELOG.md).
