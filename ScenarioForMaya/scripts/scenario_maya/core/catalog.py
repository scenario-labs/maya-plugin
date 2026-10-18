"""The model catalog behind the picker (spec 4.3).

Cached per workspace for 24 h in ``<user dir>/catalog.json`` and refreshed in
the background, so the picker opens at once. Rows are compact: id, name, one
line, capabilities, tags, privacy, creation date. Legacy and deprecated models
are hidden unless asked for.
"""

from __future__ import annotations

import json
import os
import threading
import time

from .lanes import Lane
from .paths import user_file

TTL = 24 * 3600
_KEEP = ("id", "name", "shortDescription", "capabilities", "tags", "privacy", "createdAt", "type")


def compact(row: dict) -> dict:
    return {key: row.get(key) for key in _KEEP if row.get(key) is not None}


def is_legacy(row: dict) -> bool:
    tags = [str(tag).lower() for tag in row.get("tags") or ()]
    return any(tag in ("deprecated", "sc:legacy") or tag.startswith("deprecated:") for tag in tags)


class Catalog:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or user_file("catalog.json")
        self._lock = threading.Lock()
        self._data = self._read()

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _entry(self, workspace: str) -> dict:
        with self._lock:
            entry = (self._data.get("workspaces") or {}).get(workspace) or {}
        return entry

    def models(self, workspace: str) -> list:
        return list(self._entry(workspace).get("models") or [])

    def fresh(self, workspace: str) -> bool:
        entry = self._entry(workspace)
        return bool(entry.get("models")) and time.time() - float(entry.get("fetched") or 0) < TTL

    def refresh(self, backend, workspace: str, modalities=("image",), pages: int = 10) -> list:
        """Reads public and team models for the modalities, then saves. Blocks: run on a worker."""
        rows, seen = [], set()
        for privacy in ("private", "public"):
            for modality in modalities:
                token = ""
                for _ in range(pages):
                    page, token = backend.models(privacy=privacy, modality=modality, limit=100, page_token=token)
                    for row in page:
                        if row.get("id") and row["id"] not in seen and str(row.get("status") or "trained") == "trained":
                            seen.add(row["id"])
                            rows.append(dict(compact(row), team=privacy == "private"))
                    if not token:
                        break
        with self._lock:
            workspaces = self._data.setdefault("workspaces", {})
            workspaces[workspace] = {"fetched": time.time(), "models": rows}
            data = json.loads(json.dumps(self._data))
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, self.path)
        return rows

    def for_lane(self, workspace: str, lane: Lane, *, text: str = "", favorites=(), show_legacy: bool = False, team_only: bool = False) -> list:
        """Favorites first, then the lane's quick picks, then newest first."""
        words = [word for word in text.lower().split() if word]
        out = []
        for row in self.models(workspace):
            if not set(row.get("capabilities") or ()) & set(lane.capabilities):
                continue
            if not show_legacy and is_legacy(row):
                continue
            if team_only and not row.get("team"):
                continue
            haystack = " ".join([row.get("name") or "", row.get("shortDescription") or "", " ".join(row.get("tags") or ())]).lower()
            if words and not all(word in haystack for word in words):
                continue
            out.append(row)
        picks = {model_id: index for index, model_id in enumerate(lane.quick_picks)}
        favorite = set(favorites)

        def order(row):
            model_id = row["id"]
            created = row.get("createdAt") or ""
            return (0 if model_id in favorite else 1, picks.get(model_id, len(picks)), _negated(created))

        out.sort(key=order)
        return out

    def get(self, workspace: str, model_id: str) -> dict | None:
        return next((row for row in self.models(workspace) if row.get("id") == model_id), None)


def _negated(text: str) -> tuple:
    """Sort key for newest first on ISO dates."""
    return tuple(-ord(char) for char in text)
