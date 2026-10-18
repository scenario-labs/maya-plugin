"""File log in ``<scenario dir>/logs/``: ids and states, never credentials.

A filter masks anything that looks like a credential or a signed link, as a
second line of defence behind messages that are written without them.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re

from .paths import user_dir

LOGGER = logging.getLogger("scenario_maya")

_MASKS = (
    (re.compile(r"(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 ***"),
    (re.compile(r"([?&](?:X-Amz-[A-Za-z-]+|Signature|sig|token|code|Key-Pair-Id|Policy)=)[^&\s\"']+", re.I), r"\1***"),
    (re.compile(r"\b(rt|at)_[A-Za-z0-9_-]{8,}"), r"\1_***"),
)


def redact(text: str) -> str:
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


class _Redact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def configure(level: int = logging.INFO) -> str:
    """Adds the rotating file handler once. Returns the log path."""
    folder = os.path.join(user_dir(), "logs")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "scenario.log")
    for handler in LOGGER.handlers:
        if getattr(handler, "baseFilename", "") == os.path.abspath(path):
            return path
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler.addFilter(_Redact())
    LOGGER.addHandler(handler)
    LOGGER.setLevel(level)
    LOGGER.propagate = False
    return path


def close() -> None:
    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()
