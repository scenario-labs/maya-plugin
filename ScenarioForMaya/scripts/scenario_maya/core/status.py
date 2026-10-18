"""Status words for job rows (spec 4.6), shared by the panel, the agent tools and the API.

The ledger state says what the plug-in knows; Scenario's own status and
progress refine it while the job runs. No time estimates.
"""

from __future__ import annotations

_REMOTE = {
    "queued": "Queued",
    "warming-up": "Starting",
    "in-progress": "Generating",
    "processing": "Generating",
    "finalizing": "Finalizing",
}

_FIXED = {
    "prepared": "Preparing",
    "submitting": "Submitting",
    "uncertain": "Not confirmed",
    "cancel_requested": "Canceling",
    "succeeded": "Finished",
    "download_failed": "Download failed",
    "ready": "Ready to apply",
    "applied": "Applied",
    "apply_failed": "Apply failed",
    "canceled": "Canceled",
}

# Tone drives colour and icons; the word is always shown as well.
TONES = ("busy", "ok", "warning", "error", "neutral")


def _percent(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 1.0:
        number *= 100.0
    return f" {max(0, min(100, int(number)))}%"


def status_word(row: dict) -> str:
    state = row.get("state", "")
    result = row.get("result") or {}
    if state == "remote":
        word = _REMOTE.get(str(result.get("status") or "").lower(), "Queued")
        return word + (_percent(result.get("progress")) if word == "Generating" and result.get("progress") else "")
    if state == "downloading":
        progress = result.get("download_progress")
        return "Downloading" + (_percent(progress) if progress is not None else "")
    if state == "applying":
        return "Needs review" if not row.get("owner") and row.get("hint") else "Applying"
    if state == "failed":
        return "Blocked" if str(row.get("error") or "").startswith("Blocked") else "Failed"
    return _FIXED.get(state, state.replace("_", " ").capitalize())


def status_tone(row: dict) -> str:
    state = row.get("state", "")
    if state in ("prepared", "submitting", "remote", "cancel_requested", "succeeded", "downloading", "applying"):
        return "warning" if state == "applying" and not row.get("owner") and row.get("hint") else "busy"
    if state in ("ready", "applied"):
        return "ok"
    if state in ("uncertain", "download_failed"):
        return "warning"
    if state in ("failed", "apply_failed"):
        return "error"
    return "neutral"
