"""Single-use quotes bound to the exact payload.

A quote is what turns a free price check into permission to spend that
price, once. It is bound to the model, the canonical parameters and their
hash, the workspace, the input asset ids and the scene origin (scene, target
node and its fingerprint). It expires after 120 seconds. Taking a quote
checks all of that and the exact cost string, then marks it used, under one
lock, so two callers can never spend the same quote.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from . import errors
from .jsonutil import canonical_json, cu_display, sha256_hex

QUOTE_TTL = 120.0


@dataclass
class Quote:
    quote_id: str
    kind: str  # "model", "workflow" or "spark"
    target_id: str  # model or workflow id
    params: dict
    params_hash: str
    workspace: str  # "team/project" or "key:<id>"
    input_asset_ids: tuple
    origin: dict  # {"scene_uuid", "scene_path", "target", "fingerprint"}
    cu_cost_exact: str
    created: float
    expires: float
    driver: str = "person"
    used: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def quote_hash(self) -> str:
        return sha256_hex(canonical_json({"q": self.quote_id, "p": self.params_hash, "c": self.cu_cost_exact, "w": self.workspace}))

    def cu_cost_display(self) -> str:
        return cu_display(self.cu_cost_exact)

    def seconds_left(self, now: float | None = None) -> float:
        return max(0.0, self.expires - (now if now is not None else time.time()))

    def public(self) -> dict:
        """What an agent sees: no internal fields."""
        return {
            "quote_id": self.quote_id,
            "model_id" if self.kind != "workflow" else "workflow_id": self.target_id,
            "cu_cost_exact": self.cu_cost_exact,
            "cu_cost": self.cu_cost_display(),
            "expires_in_s": round(self.seconds_left()),
            "bound_to": {
                "params_hash": self.params_hash[:16],
                "workspace": self.workspace,
                "input_asset_ids": list(self.input_asset_ids),
                "target": self.origin.get("target", ""),
            },
        }


def input_assets(params: dict) -> tuple:
    found = []

    def walk(value):
        if isinstance(value, str) and value.startswith("asset_"):
            found.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(params)
    return tuple(sorted(set(found)))


class QuoteBook:
    def __init__(self, ttl: float = QUOTE_TTL, clock=time.time) -> None:
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._quotes: dict = {}

    def issue(self, *, kind: str, target_id: str, params: dict, workspace: str, cu_cost_exact: str, origin: dict | None = None, driver: str = "person") -> Quote:
        now = self._clock()
        canonical = canonical_json(params)
        quote = Quote(
            quote_id="q_" + secrets.token_urlsafe(12),
            kind=kind,
            target_id=target_id,
            params=params,
            params_hash=sha256_hex(canonical),
            workspace=workspace,
            input_asset_ids=input_assets(params),
            origin=dict(origin or {}),
            cu_cost_exact=cu_cost_exact,
            created=now,
            expires=now + self._ttl,
            driver=driver,
        )
        with self._lock:
            self._purge(now)
            self._quotes[quote.quote_id] = quote
        return quote

    def get(self, quote_id: str) -> Quote | None:
        with self._lock:
            return self._quotes.get(quote_id)

    def take(
        self,
        quote_id: str,
        *,
        approved_cost: str | None = None,
        params: dict | None = None,
        workspace: str | None = None,
        origin: dict | None = None,
    ) -> Quote:
        """Validates and consumes a quote. Raises ``QuoteError`` with the exact reason."""
        now = self._clock()
        with self._lock:
            quote = self._quotes.get(quote_id or "")
            if quote is None:
                raise errors.QuoteError("Unknown quote. Check the price again.")
            if quote.used:
                raise errors.QuoteError("This quote was already used. Check the price again for another run.")
            if now >= quote.expires:
                raise errors.QuoteError("The quote expired (120 s). Check the price again.")
            if approved_cost is not None and approved_cost != quote.cu_cost_exact:
                raise errors.QuoteError(f"approved_cost must be exactly {quote.cu_cost_exact!r}, the quoted price.")
            if params is not None and sha256_hex(canonical_json(params)) != quote.params_hash:
                raise errors.QuoteError("The parameters changed since the price check. Check the price again.")
            if workspace is not None and workspace != quote.workspace:
                raise errors.QuoteError("The workspace changed since the price check.")
            if origin is not None:
                for key in ("scene_uuid", "target", "fingerprint"):
                    if quote.origin.get(key, "") != origin.get(key, ""):
                        raise errors.QuoteError("The scene or target changed since the price check.")
            quote.used = True
            return quote

    def release(self, quote_id: str) -> None:
        """Puts back a quote whose request was refused locally before anything was sent."""
        with self._lock:
            quote = self._quotes.get(quote_id)
            if quote is not None:
                quote.used = False

    def clear(self) -> None:
        with self._lock:
            self._quotes.clear()

    def _purge(self, now: float) -> None:
        stale = [key for key, quote in self._quotes.items() if now - quote.expires > 600]
        for key in stale:
            del self._quotes[key]
