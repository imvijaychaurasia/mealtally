"""In-app help articles (D03 #23, D03.2): short how-tos in our own words, shown by audience in the header help drawer.

Audiences: ``customer`` (the customer app), ``staff`` (counter staff), ``owner`` (owners and managers; they also see staff articles).
"""

from django.utils.translation import gettext_lazy as _

CUSTOMER, STAFF, OWNER = "customer", "staff", "owner"

ARTICLES = [
    # --- customers ----------------------------------------------------------------------------------------------
    (
        CUSTOMER,
        _("How do I show my QR at the counter?"),
        _("Open My QR and show the screen to the staff. The code refreshes by itself and each code works only once."),
    ),
    (
        CUSTOMER,
        _("How do I see how many meals I have left?"),
        _("Your Home screen shows meals left, days left and the date your pass ends."),
    ),
    (
        CUSTOMER,
        _("What happens when my pass ends?"),
        _(
            "Unused meals expire on the end date and cannot be carried forward. Renew at the counter and the new pass starts right after."
        ),
    ),
    (
        CUSTOMER,
        _("How do I change my PIN?"),
        _("Open Profile and choose Change PIN. If you forgot it, ask the counter staff to reset it for you."),
    ),
    # --- staff and owners ------------------------------------------------------------------------------------------
    (
        STAFF,
        _("How do I sell a pass?"),
        _(
            "Open Sell pass, find the customer (or add them), pick the plan and the payment method, then confirm. The receipt is ready straight away."
        ),
    ),
    (
        STAFF,
        _("How do I redeem a meal?"),
        _(
            "On Redeem, scan the customer's QR or type the last digits of their phone, then tap Redeem meal. You can undo for 30 seconds."
        ),
    ),
    (
        STAFF,
        _("The card is red — what now?"),
        _(
            "The customer has no active pass. Tap Sell pass to renew; a new pass can queue to start when the current one ends."
        ),
    ),
    (
        STAFF,
        _("A meal was redeemed by mistake"),
        _(
            "Tap Undo on the green card within 30 seconds, or use Reverse in Today's redemptions. Every reversal is recorded with your name."
        ),
    ),
    (
        STAFF,
        _("Who can see what?"),
        _(
            "Owners and managers see everything. Counter staff see Redeem, Sell and customer lookup. Chefs see the kitchen and drivers see their route."
        ),
    ),
    (
        OWNER,
        _("How do I add a staff login?"),
        _(
            "Owners can open More → Staff, add a name and phone or email, and share the temporary password. They choose their own at first login."
        ),
    ),
    (
        OWNER,
        _("What does the platform fee cover?"),
        _(
            "Money → Platform fee statement lists each payment, the fee on it and any reversals, month by month. It always adds up to the invoice."
        ),
    ),
    (
        OWNER,
        _("How do customers see their balance?"),
        _(
            "They log in with their phone and PIN. Their home screen shows meals left, validity and a QR for the counter."
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
