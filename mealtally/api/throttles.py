from rest_framework.throttling import SimpleRateThrottle


class LoginThrottle(SimpleRateThrottle):
    """Per client IP, on the login endpoints (credential stuffing): default 30 attempts / 10 minutes."""

    scope = "login"
    THROTTLE_RATES = {"login": "30/10min"}

    def parse_rate(self, rate):
        if rate is None:
            return (None, None)
        num, period = rate.split("/")
        minutes = int(period[:-3]) if period.endswith("min") and period[:-3] else 1
        return int(num), 60 * minutes if period.endswith("min") else {"s": 1, "m": 60, "h": 3600, "d": 86400}[period[0]]

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class RedeemUserThrottle(SimpleRateThrottle):
    """Per staff user, on redeem endpoints."""

    scope = "redeem_user"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class RedeemTenantThrottle(SimpleRateThrottle):
    """Per tenant, on redeem endpoints (the tenant is resolved before throttles run)."""

    scope = "redeem_tenant"

    def get_cache_key(self, request, view):
        tenant = getattr(request, "tenant", None)
        return self.cache_format % {"scope": self.scope, "ident": tenant.pk if tenant else "none"}
