"""Canonical JSON, hashes and Creative Unit formatting.

A quote is bound to the SHA-256 of the canonical JSON of its payload, so the
same form always hashes the same way: sorted keys, no spaces, UTF-8, and
``None`` values dropped (strict clients send ``null`` for every unset option).
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any


def drop_nulls(value: Any) -> Any:
    """Removes ``None`` values from dicts, recursively. Lists keep their length."""
    if isinstance(value, dict):
        return {k: drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [drop_nulls(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(drop_nulls(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def payload_hash(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def file_sha256(path: str, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def cu_exact(value: Any) -> str:
    """The exact cost string an agent must echo back: ``"120"``, ``"2.75"``.

    Scenario sends costs as JSON numbers. ``repr`` of a float is the shortest
    string that reads back to the same float, so a decimal literal from the
    server comes back unchanged; trailing zeros are removed.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError("not a cost")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"not a cost: {value!r}")
        return str(value)
    if isinstance(value, float):
        text = repr(value)
    else:
        text = str(value).strip()
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"not a cost: {value!r}") from error
    if not number.is_finite() or number < 0:
        raise ValueError(f"not a cost: {value!r}")
    normalized = format(number.normalize(), "f")
    return "0" if normalized in ("-0", "0.0") else normalized


def cu_display(exact: str) -> str:
    """``"1200"`` -> ``"1,200 CU"``, ``"2.75"`` -> ``"2.75 CU"``."""
    number = Decimal(exact)
    if number == number.to_integral_value():
        return f"{int(number):,} CU"
    return f"{number:,f} CU"
