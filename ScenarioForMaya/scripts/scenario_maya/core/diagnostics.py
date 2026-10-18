"""Diagnostics text for bug reports: versions, paths, network and state. Never a secret."""

from __future__ import annotations

import platform
import sys

from .. import __version__
from . import http
from .log import redact
from .paths import user_dir


def report(session=None, dispatcher=None, extra: dict | None = None) -> str:
    lines = [
        f"Scenario for Maya {__version__}",
        f"Host: {http.user_agent()}",
        f"Python: {sys.version.split()[0]} on {platform.platform()}",
        f"TLS trust: {http.ssl_source()}",
        f"Data folder: {user_dir(create=False)}",
    ]
    if session is not None:
        status = session.status()
        lines += [
            f"Signed in: {'yes, ' + status['method'] if status['signed_in'] else 'no'}",
            f"Account: {status['account'] or '-'}",
            f"Workspace: {status['team']['name'] or '-'} / {status['project']['name'] or '-'} ({session.workspace() or '-'})",
            f"Spending: {status['spending']}; price checks: {status['price_checks']}",
            f"Credential store: {status['credential_store']}{' (file, owner only)' if status['credential_store_insecure'] else ''}",
            f"Endpoint: {session.endpoint}",
        ]
        counts: dict = {}
        for row in session.ledger.list(limit=500):
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        lines.append("Jobs: " + (", ".join(f"{state} {n}" for state, n in sorted(counts.items())) or "none"))
    if dispatcher is not None:
        name, took = getattr(dispatcher, "longest_call", ("", 0.0))
        lines.append(f"Main thread: longest slice {dispatcher.longest_slice_ms:.1f} ms over {dispatcher.slices} slices; slowest call {name or 'none'} {took:.1f} ms; {dispatcher.pending()} queued")
        if dispatcher.errors:
            lines.append("Recent main-thread errors: " + " | ".join(dispatcher.errors[-3:]))
    for key, value in (extra or {}).items():
        lines.append(f"{key}: {value}")
    return redact("\n".join(lines))
