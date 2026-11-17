from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from mealtally.api import serializers as s
from mealtally.api.base import PlatformAPIView
from mealtally.billing import services as billing
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.models import Tenant


class TenantListCreateView(PlatformAPIView):
    @extend_schema(responses=dict)
    def get(self, request):
        return Response({"results": [s.tenant_out(t) for t in Tenant.objects.order_by("slug")]})

    @extend_schema(request=s.TenantCreateIn, responses=dict)
    def post(self, request):
        data = s.TenantCreateIn(data=request.data)
        data.is_valid(raise_exception=True)
        tenant = tenancy.create_tenant(actor=request.user, **data.validated_data)
        return Response(s.tenant_out(tenant), status=status.HTTP_201_CREATED)


class _TenantStatusView(PlatformAPIView):
    new_status = Tenant.Status.ACTIVE

    @extend_schema(request=s.TenantStatusIn, responses=dict)
    def post(self, request, slug):
        data = s.TenantStatusIn(data=request.data)
        data.is_valid(raise_exception=True)
        tenant = tenancy.set_status(
            tenant=tenancy.get_tenant_by_slug(slug),
            status=self.new_status,
            actor=request.user,
            reason=data.validated_data["reason"],
        )
        return Response(s.tenant_out(tenant))


class TenantSuspendView(_TenantStatusView):
    new_status = Tenant.Status.SUSPENDED


class TenantActivateView(_TenantStatusView):
    new_status = Tenant.Status.ACTIVE


class TenantDeactivateView(_TenantStatusView):
    new_status = Tenant.Status.DEACTIVATED


class FeePolicyView(PlatformAPIView):
    @extend_schema(request=s.FeePolicyIn, responses=dict)
    def post(self, request, slug):
        data = s.FeePolicyIn(data=request.data)
        data.is_valid(raise_exception=True)
        policy = billing.set_fee_policy(
            tenant=tenancy.get_tenant_by_slug(slug), actor=request.user, **data.validated_data
        )
        return Response(
            {
                "platform_pct": str(policy.platform_pct),
                "gateway_pct": str(policy.gateway_pct),
                "effective_from": s.iso(policy.effective_from),
            },
            status=status.HTTP_201_CREATED,
        )
