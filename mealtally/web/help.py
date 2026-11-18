# SPDX-License-Identifier: AGPL-3.0-only
"""In-app help articles: short how-tos in our own words, shown by audience in the header help drawer.

Audiences: ``customer`` (the customer app), ``staff`` (counter staff), ``owner`` (owners and managers; they also see staff articles).
"""

from django.utils.translation import gettext_lazy as _

CUSTOMER, STAFF, OWNER = "customer", "staff", "owner"

ARTICLES = [
    # --- customers ----------------------------------------------------------------------------------------------
    (
        CUSTOMER,
        _("Show your QR at the counter"),
        _("Open My QR and show the screen to the staff. The code refreshes by itself and each code works only once."),
    ),
    (
        CUSTOMER,
        _("See how many meals you have left"),
        _("Your Home screen shows meals left, days left and the date your pass ends."),
    ),
    (
        CUSTOMER,
        _("When your pass ends"),
        _(
            "Unused meals expire on the end date and cannot be carried forward. Renew at the counter and the new pass starts right after."
        ),
    ),
    (
        CUSTOMER,
        _("Change your PIN"),
        _("Open Profile and choose Change PIN. If you forgot it, ask the counter staff to reset it for you."),
    ),
    # --- staff and owners ------------------------------------------------------------------------------------------
    (
        STAFF,
        _("Sell a pass"),
        _(
            "Open Sell pass, find the customer (or add them), pick the plan and the payment method, then confirm. The receipt is ready straight away."
        ),
    ),
    (
        STAFF,
        _("Redeem a meal"),
        _(
            "On Redeem, scan the customer's QR or type the last digits of their phone, then tap Redeem meal. You can undo for 30 seconds."
        ),
    ),
    (
        STAFF,
        _("If the card is red"),
        _(
            "The customer has no active pass. Tap Sell pass to renew; a new pass can queue to start when the current one ends."
        ),
    ),
    (
        STAFF,
        _("If a meal was redeemed by mistake"),
        _(
            "Tap Undo on the green card within 30 seconds, or tap Undo in Today's redemptions. Your name is recorded with each undo."
        ),
    ),
    (
        STAFF,
        _("What each role can see"),
        _(
            "Owners and managers see everything. Counter staff see Redeem, Sell and customer lookup. Chefs see the kitchen and drivers see their route."
        ),
    ),
    (
        OWNER,
        _("Add a staff account"),
        _(
            "Owners open Staff under More, add a name and a phone number or email, and share the temporary password. Staff choose their own password the first time they sign in."
        ),
    ),
    (
        OWNER,
        _("What the platform fee statement shows"),
        _(
            "The Platform fee statement under Money lists each payment, its fee and any reversals, month by month. It always adds up to the invoice."
        ),
    ),
    (
        OWNER,
        _("How customers see their meals left"),
        _(
            "They sign in with their phone number and PIN. Their home screen shows meals left, the end date and a QR code for the counter."
        ),
    ),
]
_VISIBLE = {
    "CUSTOMER": {CUSTOMER},
    "STAFF": {STAFF},
    "CHEF": {STAFF},
    "DRIVER": {STAFF},
    "MANAGER": {STAFF, OWNER},
    "OWNER": {STAFF, OWNER},
}


def articles_for(role: str):
    """(question, answer) pairs the role should see: customers get customer articles, staff get staff articles, owners both."""
    allowed = _VISIBLE.get(str(role), set())
    return [(q, a) for aud, q, a in ARTICLES if aud in allowed]
