# SPDX-License-Identifier: AGPL-3.0-only
"""Plain-words copy for domain error codes (the same codes the API returns)."""

from django.utils.translation import gettext_lazy as _

FRIENDLY = {
    "NO_ACTIVE_PASS": _("This customer has no active pass. Sell a pass first."),
    "PASS_NOT_VALID_NOW": _("This pass is not valid right now. It has expired or has not started yet."),
    "NO_CREDITS": _("No meals left on this pass."),
    "DAILY_CAP_REACHED": _("The daily meal limit for this pass has been reached."),
    "COOLDOWN_CONFIRM_REQUIRED": _("This customer was served a moment ago."),
    "QR_EXPIRED": _("This QR code has expired. Ask the customer to refresh their QR."),
    "QR_INVALID": _("This QR code is not valid for this restaurant."),
    "QR_ALREADY_USED": _("This QR code was already used. Ask the customer to refresh their QR."),
    "NOT_ALLOWED": _("You can't do this here. Ask the owner if you think you should."),
    "TENANT_PAUSED": _("This restaurant is paused. Meals can't be redeemed right now."),
    "ALREADY_REVERSED": _("This meal was already undone."),
    "PASS_NOT_ACTIVE": _("Meals can only be restored on an active pass."),
    "QUEUE_FULL": _("This customer already has the maximum number of queued passes."),
    "AMOUNT_MISMATCH": _("The amount must equal the plan price."),
    "VOID_NOT_ALLOWED": _("This payment can no longer be voided (a meal was already redeemed, or the pass ended)."),
    "ACCOUNT_LOCKED": _("Too many attempts. Try again in 15 minutes, or ask the owner."),
    "AUTH_FAILED": _("Those details did not match. Please check and try again."),
}


def friendly(exc) -> str:
    # A NOT_ALLOWED raised with a sentence for people (e.g. "Staff can only reverse today's...") keeps that sentence;
    # the bare role-matrix message ("Role STAFF may not perform ...") gets the friendly copy.
    if exc.code == "NOT_ALLOWED" and exc.message and not exc.message.startswith("Role ") and exc.message != exc.code:
        return str(exc.message)
    return str(FRIENDLY.get(exc.code, exc.message))
