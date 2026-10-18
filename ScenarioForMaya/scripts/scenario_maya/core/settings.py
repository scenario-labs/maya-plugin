"""Per-user settings in ``<MAYA_APP_DIR>/scenario/settings.json``.

Only ids and preferences live here, never a secret: the API key id (not its
secret), the OAuth client id, the chosen team and project, panel and agent
preferences. Unknown keys are kept, so an older plug-in version does not erase
what a newer one wrote.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from .paths import user_file

DEFAULTS: dict = {
    "auth_method": "",  # "", "api_key" or "oauth"
    "api_key_id": "",
    "oauth_client_id": "",
    "oauth_redirect_uri": "",
    "account_label": "",
    "team_id": "",
    "team_name": "",
    "project_id": "",
    "project_name": "",
    "confirm_above_cu": 0,  # people only; 0 = never ask
    "agent_server_enabled": True,
    "agent_server_port": 9878,
    "agent_token_required": True,
    "agent_allow_scene_changes": False,
    "agent_allow_python": False,
    "telemetry": "unasked",  # "unasked", "on", "off"
    "update_check": True,
    "store_prompts_on_nodes": True,
}

_SECRET_LIKE = ("secret", "token", "password", "refresh")


class Settings:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or user_file("settings.json")
        self._lock = threading.Lock()
        self._data: dict = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = {}
        with self._lock:
            self._data = data if isinstance(data, dict) else {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                return self._data[key]
        return DEFAULTS.get(key, default)

    def update(self, **values: Any) -> None:
        for key in values:
            lowered = key.lower()
            if any(word in lowered for word in _SECRET_LIKE) and key not in ("agent_token_required",):
                raise ValueError(f"settings never hold secrets: {key}")
        with self._lock:
            self._data.update(values)
            data = dict(self._data)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def as_dict(self) -> dict:
        out = dict(DEFAULTS)
        with self._lock:
            out.update(self._data)
        return out
