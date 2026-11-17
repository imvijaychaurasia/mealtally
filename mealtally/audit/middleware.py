# SPDX-License-Identifier: AGPL-3.0-only
from mealtally.common.net import client_ip

from .context import RequestMeta
from .context import reset_request_meta
from .context import set_request_meta


class RequestMetaMiddleware:
    """Remember client IP / user-agent for audit events written during this request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_request_meta(
            RequestMeta(ip=client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:500])
        )
        try:
            return self.get_response(request)
        finally:
            reset_request_meta(token)
