from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestMeta:
    ip: str | None = None
    user_agent: str = ""


_EMPTY = RequestMeta()
_meta: ContextVar[RequestMeta] = ContextVar("mealtally_request_meta", default=_EMPTY)


def get_request_meta() -> RequestMeta:
    return _meta.get()


def set_request_meta(meta: RequestMeta):
    return _meta.set(meta)


def reset_request_meta(token) -> None:
    _meta.reset(token)
