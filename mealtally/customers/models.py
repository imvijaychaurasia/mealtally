from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.indexes import OpClass
from django.db import models
from django.db.models.functions import Upper

from mealtally.tenancy.models import TenantOwnedModel


class Customer(TenantOwnedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        BLOCKED = "BLOCKED"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_profiles")
    customer_code = models.CharField(max_length=20)
    full_name = models.CharField(max_length=200)
    phone_e164 = models.CharField(max_length=16)
    status = models.CharField(max_length=8, choices=Status, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    pin_hash = models.CharField(max_length=255, blank=True, help_text="Hashed customer login PIN.")
    must_change_pin = models.BooleanField(default=False)
    # D03.9 (QA-01 P1-5): delivery address; staff, owner and the customer can edit it. The order cart defaults to it.
    address = models.TextField(blank=True)
    # D03.9 (QA-01 P1-3): only wallet subscribers have the (preview) wallet: Wallet tab, Home card and Order debits.
    has_wallet = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "customer_code"], name="uniq_customer_code_per_tenant"),
            models.UniqueConstraint(fields=["tenant", "phone_e164"], name="uniq_customer_phone_per_tenant"),
            models.UniqueConstraint(fields=["tenant", "user"], name="uniq_customer_user_per_tenant"),
        ]
        indexes = [
            models.Index(fields=["tenant", "full_name"]),
            # trigram indexes: fast "contains" search on name / phone / code (ADR 0012)
            GinIndex(OpClass(Upper("full_name"), name="gin_trgm_ops"), name="cust_name_trgm"),
            GinIndex(OpClass("phone_e164", name="gin_trgm_ops"), name="cust_phone_trgm"),
            GinIndex(OpClass(Upper("customer_code"), name="gin_trgm_ops"), name="cust_code_trgm"),
        ]

    def __str__(self) -> str:
        return f"{self.customer_code} {self.full_name}"
