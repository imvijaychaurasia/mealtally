# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from mealtally.accounts.models import Role
from mealtally.accounts.policy import Action
from mealtally.accounts.policy import require
from mealtally.api import serializers as s
from mealtally.api.base import ALL_ROLES
from mealtally.api.base import TenantAPIView
from mealtally.api.pagination import StandardPagination
from mealtally.billing import services as billing
from mealtally.customers import qr
from mealtally.customers import services as customers
from mealtally.ledger import services as ledger
from mealtally.passes import services as passes


class _MeView(TenantAPIView):
    """Customer self-service. Any member with a customer profile at the tenant may use it."""

    allowed_roles = ALL_ROLES

    def customer(self, request):
        return customers.get_customer_for_user(user=request.user, tenant_id=request.tenant.id)


class MeView(_MeView):
    credential_exempt = True  # a customer with a temporary PIN can still read their profile (and see the flag)

    @extend_schema(responses=dict)
    def get(self, request):
        customer = self.customer(request)
        active = passes.active_pass_for(customer.id)
        queued = list(passes.queued_passes_for(customer.id))
        return Response(
            {
                "customer": s.customer_out(customer),
                "tenant": {"slug": request.tenant.slug, "name": request.tenant.name},
                "active_pass": s.pass_out(active, consumed=ledger.consumed_count(active)) if active else None,
                "queued_passes": [s.pass_out(p) for p in queued],
                "meals_remaining": active.meals_remaining if active else 0,
                "meals_consumed": ledger.consumed_count(active) if active else 0,
                "starts_at": s.iso(active.starts_at) if active else None,
                "ends_at": s.iso(active.ends_at) if active else None,
            }
        )

    @extend_schema(request=s.OwnProfileIn, responses=dict)
    def patch(self, request):
        if request.actor.role == Role.CUSTOMER:
            require(request.actor, Action.EDIT_OWN_PROFILE)
        data = s.OwnProfileIn(data=request.data)
        data.is_valid(raise_exception=True)
        customer = customers.update_own_name(
            customer=self.customer(request), full_name=data.validated_data["full_name"]
        )
        return Response({"customer": s.customer_out(customer)})


class MeLedgerView(_MeView):
    @extend_schema(responses=dict)
    def get(self, request):
        customer = self.customer(request)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(ledger.entries_for_customer(customer.id), request, view=self)
        return paginator.get_paginated_response([s.entry_out(e) for e in page])


class MePaymentsView(_MeView):
    @extend_schema(responses=dict)
    def get(self, request):
        customer = self.customer(request)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(billing.payments_for_customer(customer.id), request, view=self)
        return paginator.get_paginated_response([s.payment_out(p) for p in page])


class MeQrTokenView(_MeView):
    @extend_schema(responses=dict)
    def get(self, request):
        customer = self.customer(request)
        code = qr.issue_code(customer=customer, tenant=request.tenant)
        return Response(
            {
                "token": code,  # short opaque code: this is what the QR carries
                "format": "code",
                "expires_in": qr.CODE_TTL_SECONDS,
                "signed_token": qr.issue_token(customer=customer, tenant=request.tenant),  # still accepted by redeem/qr
            }
        )


class MeQrSvgView(_MeView):
    @extend_schema(responses={(200, "image/svg+xml"): bytes})
    def get(self, request):
        code = qr.issue_code(customer=self.customer(request), tenant=request.tenant)
        response = HttpResponse(qr.render_svg(code), content_type="image/svg+xml")
        response["Cache-Control"] = "no-store"
        return response
