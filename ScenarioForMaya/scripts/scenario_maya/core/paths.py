"""Where the plug-in keeps its per-user files, without importing Maya.

``<MAYA_APP_DIR>/scenario/`` holds the job ledger, settings (ids only, never a
secret), the catalog cache and the fallback credential file. It is shared by
every Maya version and by ``mayapy`` runs of the same user. Tests point it
elsewhere with ``SCENARIO_MAYA_HOME``.
"""

from __future__ import annotations

import os
import sys


def maya_app_dir() -> str:
    env = os.environ.get("MAYA_APP_DIR", "").strip()
    if env:
        return env
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Preferences", "Autodesk", "maya")
    if sys.platform.startswith("win"):
        return os.path.join(home, "Documents", "maya")
    return os.path.join(home, "maya")


def user_dir(create: bool = True) -> str:
    path = os.environ.get("SCENARIO_MAYA_HOME", "").strip() or os.path.join(maya_app_dir(), "scenario")
    if create:
        os.makedirs(path, exist_ok=True)
        if not sys.platform.startswith("win"):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
    return path


def user_file(name: str) -> str:
    return os.path.join(user_dir(), name)


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")
