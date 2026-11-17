# Hindi review checklist

Hindi (`hi`) is fully translated: 1,336 of 1,336 strings. It stays **Beta** (`LANGUAGE_REVIEW["hi"] = False` in
`config/settings/base.py`) until a native speaker has reviewed it and the maintainer signs off.

## Where the strings are

| What | Where |
|---|---|
| All Hindi text | `locale/hi/LC_MESSAGES/django.po` (the `.mo` next to it is compiled from it) |
| Which screen a string is on | the `#:` line above each entry names the template or Python file |
| Plurals | entries with `msgstr[0]` and `msgstr[1]` |
| Placeholders to keep unchanged | `%(name)s`, `%(n)d`, `%%`, `{{ ... }}` |

Strings by area (by the file each one comes from): Preview modules 567, owner and manager 228, marketing and legal
pages 152, shared navigation, messages and labels 111, counter 106, platform admin 67, customer app 56, sign-in and
errors 49. The counter, customer app, sign-in and shared strings (322) matter most: review those first.

## Setting up the demo instance

On a development checkout (`MEALTALLY_ENV=development` in `.env`):

```bash
make up
```

```bash
make demo
```

Open http://localhost:8000 and use the logins in `.demo-credentials`. In the language picker (top of every screen),
choose **हिन्दी · Beta**. The choice is remembered for each login.

For the counter's "redeemed" and "blocked by meal time" messages, review during a meal time of the demo plans
(lunch 12:00 to 15:00, dinner 19:00 to 22:30, India time), or outside one to see the blocked message.

## What to check on each screen

For every screen below: the meaning is right, the words are the ones staff and customers really use (for example
"मील पास", "रिडीम", "टॉप-अप" are kept as loanwords; change them if a Hindi word is more natural), nothing is cut off
or wraps badly on a phone, and numbers, dates and money read correctly.

### Sign-in and errors
- [ ] Restaurant sign-in choice page (`/t/demo-tiffin/`)
- [ ] Staff sign-in and customer sign-in, including the "forgot PIN" line
- [ ] Change password and change PIN (first sign-in)
- [ ] "Page not found" and "service paused" pages

### Counter (sign in as `counter1@saffrontiffins.example.com`)
- [ ] Redeem screen: search box, customer card, "meals left", the redeem button
- [ ] Redeemed, undo, and "already served a moment ago" confirmation
- [ ] Blocked by a meal rule (outside meal time, already had this meal, daily limit)
- [ ] Sell a pass: plan choice, payment method, reference, confirmation, receipt (screen and PDF)
- [ ] New customer with a generated PIN, and the printed PIN slip

### Owner and manager (sign in as `owner@saffrontiffins.example.com`)
- [ ] Dashboard tiles and alerts
- [ ] Customers list and a customer's page: block, reset PIN, adjust credits, void a payment
- [ ] Plans: new plan, validity choices, meal times, daily limit
- [ ] Meal times page
- [ ] Staff and roles, including "Counter" and the temporary password message
- [ ] Settings: restaurant details, country, currency, time zone, default language, theme
- [ ] Reports: each report's title, column names and CSV/PDF exports
- [ ] Audit log: the sentences that describe each change ("… ने … का भोजन वापस लिया")

### Customer app (sign in with a customer phone and PIN from `.demo-credentials`)
- [ ] Home: meals left, validity, "running low" and "expiring" messages (with 1 and with several meals: plurals)
- [ ] Show QR, and the line telling the customer what to read out
- [ ] Activity and its filters
- [ ] Account: language, PIN change, help

### Preview modules (labelled "Preview"; lower priority)
- [ ] Wallet and top-up, Order, Kitchen, Delivery and driver screen, Invoices, Expenses, Notifications

### Not in the `.po` file
- [ ] Amounts, dates and phone numbers come from CLDR data for Hindi plus the restaurant's country; report anything
  that reads wrong, but it is fixed in code, not in the translation.

## Recording corrections

Either edit `locale/hi/LC_MESSAGES/django.po` directly (Poedit works well), or list corrections as
"screen, current text, better text" in an issue. Then:

```bash
make messages
```

```bash
make test
```

## Sign-off

When every box above is ticked and the corrections are in:

1. Set `"hi"` to reviewed in `LANGUAGE_REVIEW` in `config/settings/base.py` (Hindi then drops the Beta label), and
   update the test that pins it (`mealtally/web/tests/test_i18n.py::test_language_list`).
2. Change Hindi's row in `TRANSLATING.md` and the README's language section.
3. Note the reviewer and the date in `CHANGELOG.md`.

| Reviewed by | Date | Signed off by |
|---|---|---|
| | | |
