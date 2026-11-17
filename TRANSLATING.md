# Translating Mealtally

Mealtally uses Django's gettext catalogues: one `locale/<code>/LC_MESSAGES/django.po` file per language, compiled to
`django.mo`. Both files are committed.

## Languages

| Code | Language | Status |
|---|---|---|
| `en` | English | Source language |
| `hi` | हिंदी (Hindi) | Beta: fully translated, waiting for review ([REVIEW-hi.md](REVIEW-hi.md)) |
| `mr` | मराठी (Marathi) | Beta |
| `ta` | தமிழ் (Tamil) | Beta |
| `te` | తెలుగు (Telugu) | Beta |
| `bn` | বাংলা (Bengali) | Beta |
| `gu` | ગુજરાતી (Gujarati) | Beta |
| `kn` | ಕನ್ನಡ (Kannada) | Beta |
| `es` | Español (Spanish) | Beta |
| `fr` | Français (French) | Beta |
| `pt-br` | Português do Brasil | Beta |
| `ar` | العربية (Arabic, right-to-left) | Beta |
| `id` | Bahasa Indonesia | Beta |

**Beta** means that about 200 of the most visible strings have a draft translation: navigation, sign-in, the customer
app, the counter screen, receipts and the meal-rule messages. The drafts were machine-written and are marked `fuzzy`
until a native speaker reviews them. Anything without a translation falls back to English. The language picker shows
"Beta" next to these languages.

The release image compiles the catalogues with `--use-fuzzy`, so Beta drafts are shown to users. A language leaves
Beta when a native speaker has reviewed the whole file, no `fuzzy` entries are left, and `LANGUAGE_REVIEW` in
`config/settings/base.py` marks it as reviewed.

## How the language is chosen

1. The language picker (in the header or footer of every screen) sets the `mealtally-language` cookie. For a
   signed-in user it also saves the choice to their profile, so it follows them to other devices.
2. With no choice made on this device: the user's saved language, then the restaurant's default language
   (Settings → Restaurant), then `MEALTALLY_LANGUAGE` from `.env`.

## Translating or reviewing a language

1. Open `locale/<code>/LC_MESSAGES/django.po` in a PO editor such as [Poedit](https://poedit.net/) or
   [Lokalize](https://apps.kde.org/lokalize/), or a plain text editor.
2. Translate or correct each entry. When you have checked a `fuzzy` entry, remove the `fuzzy` flag. In Poedit,
   that means marking it "Needs work" off.
3. Keep every placeholder exactly as written: `%(name)s`, `%(n)d`, `%%` and `{{ ... }}`. You may move them within
   the sentence, but don't translate or drop them. `msgfmt --check-format` (run by the tests) fails if one is
   missing.
4. Plural entries (`msgstr[0]`, `msgstr[1]`, ...) follow the plural rule in the file header. Arabic has six forms.
5. Compile and test:

   ```bash
   make messages
   make test
   ```

6. Open a pull request with both the `.po` and the `.mo` file.

Translators keep their copyright and license the translation under the project licence through the CLA (see
`CONTRIBUTING.md`).

### Words to keep as they are

Product and protocol names stay in Latin script: Mealtally, UPI, QR, PDF, CSV, PIN, UTR, WhatsApp, GSTIN, FSSAI.
"Meal pass" is the product idea that people pay once for a number of meals, so translate it with the usual local
phrase for a prepaid meal card or coupon book.

## For developers

- Mark every visible string: `{% trans %}` or `{% blocktrans %}` in templates, `gettext` / `gettext_lazy` in Python.
  `mealtally/web/tests/test_i18n.py` fails on template text that isn't marked. If a word really is the same in every
  language (a brand or unit), add it to `ALLOWED` in `mealtally/web/i18n_check.py`.
- Use logical CSS (`ms-*`, `me-*`, `ps-*`, `pe-*`, `start-*`, `end-*`, `text-start`, `text-end`, `border-s`,
  `rounded-e`, `padding-inline-start`, ...) instead of left/right, so the layout mirrors in right-to-left
  languages. Every page sets `<html dir="rtl">` for Arabic.
- After changing strings, run `make messages` and commit the updated `.po` and `.mo` files.

## Adding a language

1. Add it to `LANGUAGES` in `config/settings/base.py`, written in its own script (and to
   `MEALTALLY_BETA_LANGUAGES` while it is in Beta).
2. Run `docker compose --profile test run --rm --entrypoint "" test python manage.py makemessages -l <locale>`,
   then `make messages`.
3. Add a row to the table above.

## Hosted translation (optional)

The catalogues are standard gettext files, so a hosted platform such as [Weblate](https://weblate.org/) can work on
them directly: point a Weblate component at `locale/*/LC_MESSAGES/django.po`, file format "gettext PO file", with
English as the source language. Weblate then opens pull requests with the translated `.po` files, and a maintainer
runs `make messages` to recompile the `.mo` files before merging.
