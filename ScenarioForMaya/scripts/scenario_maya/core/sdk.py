"""Loads Scenario's Python SDK from ``_vendor/sdk`` (see ``tools/vendor_sdk.py``).

The SDK is pure Python; its ``pydantic_core`` is compiled, one build per Python
and platform, so the build for this Maya is picked here. Both folders go after
the packages installed in Maya's Python, so a studio's own ``pydantic`` or
``httpx`` keeps winning (the SDK accepts their versions), but before
``setuptools/_vendor``: Maya imports setuptools at start-up, which puts that
private folder on the path with an older ``typing_extensions`` than the SDK
needs. Imported on first use, not when Maya loads the plug-in.
"""

from __future__ import annotations

import os
import platform
import sys
import threading

from . import errors

VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_vendor", "sdk")
_LOCK = threading.Lock()


def build_tag() -> str:
    """``cp313-macos-arm64`` and the like: the ``pydantic_core`` build this Python needs."""
    system = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux" if sys.platform.startswith("linux") else sys.platform)
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("x86_64", "amd64") else machine
    return f"cp{sys.version_info[0]}{sys.version_info[1]}-{system}-{arch}"


def _private_vendor(entry: str) -> bool:
    """A package's own bundled dependencies put on the path (``setuptools/_vendor``)."""
    parts = os.path.normpath(entry).split(os.sep)
    return len(parts) >= 2 and parts[-1] == "_vendor" and parts[-2] == "setuptools"


def load():
    """The ``scenario_sdk`` module, with the vendored folders on the path."""
    with _LOCK:
        if "scenario_sdk" not in sys.modules:
            at = next((i for i, entry in enumerate(sys.path) if _private_vendor(entry)), len(sys.path))
            for folder in (os.path.join(VENDOR, "native", build_tag()), os.path.join(VENDOR, "lib")):
                if os.path.isdir(folder) and folder not in sys.path:
                    sys.path.insert(at, folder)
        try:
            import scenario_sdk
        except ImportError as error:
            raise errors.ProtocolError(
                f"Scenario's SDK could not be loaded on this Maya ({build_tag()}): {error}.",
                hint="Reinstall the plug-in; in a checkout, run tools/vendor_sdk.py.",
            ) from error
        return scenario_sdk
