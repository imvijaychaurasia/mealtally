# SPDX-License-Identifier: AGPL-3.0-only
from django.utils.translation import gettext as _


def actor_label(user) -> str:
    """Who did it: name, else e-mail/phone, else 'System' (jobs and automatic activations have no actor)."""
    if user is None:
        return _("System")
    return user.name or user.email or user.phone_e164 or _("System")


from django.utils.translation import gettext_lazy  # noqa: E402

ENTRY_LABELS = {
    "ISSUE": gettext_lazy("Credits issued"),
    "REDEEM": gettext_lazy("Meal redeemed"),
    "REVERSAL": gettext_lazy("Undo"),
    "ADJUST": gettext_lazy("Adjusted"),
    "EXPIRE": gettext_lazy("Expired"),
}
SOURCE_LABELS = {
    "STAFF_SEARCH": gettext_lazy("Counter search"),
    "QR_SCAN": gettext_lazy("QR scan"),
    "DEVICE": gettext_lazy("Device"),
    "SYSTEM": gettext_lazy("System"),
    "ADMIN": gettext_lazy("Admin"),
}
