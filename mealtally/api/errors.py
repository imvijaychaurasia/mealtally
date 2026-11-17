# SPDX-License-Identifier: AGPL-3.0-only
"""One JSON error envelope for everything: ``{"error": {"code", "message", "details"}}``."""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.views import set_rollback

from mealtally.common.errors import DomainError

_CODES = {
    exceptions.NotAuthenticated: ("NOT_AUTHENTICATED", 401),
    exceptions.AuthenticationFailed: ("AUTH_FAILED", 401),
    exceptions.PermissionDenied: ("FORBIDDEN", 403),
    exceptions.NotFound: ("NOT_FOUND", 404),
    exceptions.MethodNotAllowed: ("METHOD_NOT_ALLOWED", 405),
    exceptions.NotAcceptable: ("NOT_ACCEPTABLE", 406),
    exceptions.UnsupportedMediaType: ("UNSUPPORTED_MEDIA_TYPE", 415),
    exceptions.ParseError: ("MALFORMED_REQUEST", 400),
    exceptions.Throttled: ("RATE_LIMITED", 429),
}


def envelope(code: str, message: str, details=None, status: int = 400) -> Response:
    return Response({"error": {"code": code, "message": message, "details": details or {}}}, status=status)


def exception_handler(exc, context):
    if isinstance(exc, DomainError):
        # Undo any partial work done in this request's transaction -- unless the service already undid its own work
        # (its savepoint) and deliberately wrote an audit row that must survive (D03.9: ``redeem.denied``).
        if not getattr(exc, "keep_transaction", False):
            set_rollback()
        return envelope(exc.code, exc.message, exc.details, exc.status_code)
    if isinstance(exc, DjangoValidationError):
        set_rollback()
        return envelope(
            "VALIDATION_ERROR",
            "The request is invalid.",
            {"fields": exc.message_dict if hasattr(exc, "error_dict") else exc.messages},
            400,
        )
    if isinstance(exc, Http404):
        set_rollback()
        return envelope("NOT_FOUND", "Not found.", status=404)
    response = drf_exception_handler(exc, context)
    if response is None:
        return None  # genuine 500: let Django log it
    if isinstance(exc, exceptions.ValidationError):
        return envelope("VALIDATION_ERROR", "The request is invalid.", {"fields": response.data}, 400)
    for klass, (code, status) in _CODES.items():
        if isinstance(exc, klass):
            details = {}
            if isinstance(exc, exceptions.Throttled) and exc.wait is not None:
                details["retry_after_seconds"] = int(exc.wait)
            return envelope(code, str(exc.detail), details, status)
    return envelope("ERROR", str(getattr(exc, "detail", exc)), status=response.status_code)
