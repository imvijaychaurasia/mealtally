# SPDX-License-Identifier: AGPL-3.0-only
"""Short-lived, single-use QR identification tokens."""

from __future__ import annotations

import io
import json
import re
import secrets
import uuid

import segno
from django.core.signing import BadSignature
from django.core.signing import SignatureExpired
from django.core.signing import TimestampSigner
from django_redis import get_redis_connection

from mealtally.common.errors import QrAlreadyUsed
from mealtally.common.errors import ValidationFailed

SALT = "mealtally.qr.v1"
CODE_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"  # base32; uppercase+digits => QR "alphanumeric" mode (smallest symbols)
)
CODE_LENGTH = 12
CODE_TTL_SECONDS = 90
_CODE_RE = re.compile(rf"^[{CODE_ALPHABET}]{{{CODE_LENGTH}}}$")
MAX_AGE_SECONDS = 90
JTI_TTL_SECONDS = 120


def _signer() -> TimestampSigner:
    return TimestampSigner(salt=SALT)


def issue_token(*, customer, tenant) -> str:
    payload = {"tid": str(tenant.public_id), "cid": str(customer.public_id), "jti": uuid.uuid4().hex}
    return _signer().sign_object(payload)


def issue_code(*, customer, tenant) -> str:
    """Web QR payload: a short opaque code (12 base32 chars, 60 bits) held in Valkey for 90 s.

    It carries nothing: the server looks it up. Single-use is enforced by ``claim_jti`` exactly as for signed tokens.
    """
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    payload = {"tid": str(tenant.public_id), "cid": str(customer.public_id)}
    get_redis_connection("default").set(f"mealtally:qr:code:{code}", json.dumps(payload), ex=CODE_TTL_SECONDS)
    return code


def resolve(token: str, *, tenant) -> dict:
    """Accept either the short code (web QR) or a signed token (API clients). Returns ``{tid, cid, jti}``."""
    token = (token or "").strip()
    candidate = token.upper().replace(" ", "")
    if _CODE_RE.match(candidate):
        raw = get_redis_connection("default").get(f"mealtally:qr:code:{candidate}")
        if raw is None:
            raise ValidationFailed("This QR code has expired. Ask the customer to refresh it.", code="QR_EXPIRED")
        payload = json.loads(raw)
        if payload.get("tid") != str(tenant.public_id):
            raise ValidationFailed("Invalid QR code.", code="QR_INVALID")
        return {**payload, "jti": candidate}
    return verify_token(token, tenant=tenant)


def verify_token(token: str, *, tenant) -> dict:
    """Check signature, age (<= 90 s) and tenant. Raises QR_EXPIRED / QR_INVALID."""
    try:
        payload = _signer().unsign_object(token, max_age=MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise ValidationFailed("This QR code has expired. Ask the customer to refresh it.", code="QR_EXPIRED") from exc
    except BadSignature as exc:
        raise ValidationFailed("Invalid QR code.", code="QR_INVALID") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("tid") != str(tenant.public_id)
        or not payload.get("cid")
        or not payload.get("jti")
    ):
        raise ValidationFailed("Invalid QR code.", code="QR_INVALID")
    return payload


def claim_jti(jti: str, idempotency_key: str) -> None:
    """Mark the token used (Valkey, TTL 120 s). A retry of the *same* request (same idempotency key) is allowed.

    Uses the raw client (not the cache API) so a Valkey outage fails closed instead of silently
    accepting a replayed QR.
    """
    conn = get_redis_connection("default")
    key = f"mealtally:qr:jti:{jti}"
    if conn.set(key, idempotency_key, nx=True, ex=JTI_TTL_SECONDS):
        return
    stored = conn.get(key)
    stored = stored.decode() if isinstance(stored, bytes) else stored
    if stored != idempotency_key:
        raise QrAlreadyUsed("This QR code has already been used.")


def render_svg(token: str) -> bytes:
    buf = io.BytesIO()
    segno.make(token, error="m", micro=False, boost_error=False).save(buf, kind="svg", scale=6, border=2, xmldecl=False)
    return buf.getvalue()
