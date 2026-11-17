"""Tiny structured (JSON-lines) log formatter -- no extra dependency."""

from __future__ import annotations

import json
import logging
from datetime import UTC
from datetime import datetime

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        payload.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")})
        return json.dumps(payload, default=str)
