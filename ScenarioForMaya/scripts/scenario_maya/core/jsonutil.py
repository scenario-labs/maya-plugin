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
    """Spec 4.2: ``"1200"`` -> ``"1,200 CU"``, ``"2.75"`` -> ``"2.75 CU"``, ``"12345"`` -> ``"12.3K CU"``.

    Up to three decimals without trailing zeros, thousands separators below
    10,000, then K, M and B with three significant digits. A non-zero price
    that rounds to zero shows as ``< 0.001 CU``.
    """
    number = Decimal(str(exact))
    if number < 10000:
        rounded = number.quantize(Decimal("0.001"))
        if number > 0 and rounded == 0:
            return "< 0.001 CU"
        text = f"{rounded:,f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return f"{text} CU"
    for size, suffix in ((Decimal(10) ** 9, "B"), (Decimal(10) ** 6, "M"), (Decimal(10) ** 3, "K")):
        if number >= size:
            scaled = number / size
            digits = 3 - len(str(int(scaled)))
            text = f"{scaled:.{max(digits, 0)}f}"
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return f"{text}{suffix} CU"
    return f"{number} CU"  # pragma: no cover
