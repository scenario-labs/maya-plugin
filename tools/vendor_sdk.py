"""Unpacks Scenario's Python SDK and its dependencies into the plug-in (``_vendor/sdk/``).

Wheels come from PyPI, pinned by version and SHA-256 in ``tools/sdk_wheels.json``.
Pure-Python wheels go to ``_vendor/sdk/lib``; ``pydantic_core`` is compiled, so
each of its builds goes to ``_vendor/sdk/native/<tag>`` and ``core/sdk.py``
picks the one for the running Maya (Python 3.11 for Maya 2025 and 2026, 3.13 for
Maya 2027; macOS arm64 and x64, Windows x64, Linux x64).

Usage:
  python3 tools/vendor_sdk.py            # download (cached in .cache/) and unpack
  python3 tools/vendor_sdk.py --update   # pin PINS anew from PyPI into tools/sdk_wheels.json
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, "tools", "sdk_wheels.json")
CACHE = os.path.join(ROOT, ".cache", "sdk-wheels")
TARGET = os.path.join(ROOT, "ScenarioForMaya", "scripts", "scenario_maya", "_vendor", "sdk")

# scenario-sdk and what it needs on Python 3.11 and 3.13 (uv pip compile).
PINS = {
    "scenario-sdk": "2.5.0",
    "annotated-types": "0.8.0",
    "anyio": "4.16.0",
    "certifi": "2026.10.23",
    "distro": "1.9.0",
    "h11": "0.16.0",
    "httpcore": "1.0.9",
    "httpx": "0.28.1",
    "idna": "3.20",
    "pydantic": "2.14.3",
    "pydantic-core": "2.50.4",
    "sniffio": "1.3.1",
    "typing-extensions": "4.16.0",
    "typing-inspection": "0.4.5",
}
NATIVE = "pydantic-core"
PYTHONS = ("cp311", "cp313")
PLATFORMS = {"macos-arm64": "macosx_11_0_arm64", "macos-x64": "_x86_64.whl", "windows-x64": "win_amd64", "linux-x64": "manylinux_2_17_x86_64"}


def update() -> None:
    wheels = []
    for name, version in PINS.items():
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as reply:
            files = [f for f in json.load(reply)["urls"] if f["packagetype"] == "bdist_wheel"]
        if name != NATIVE:
            pure = next(f for f in files if f["filename"].endswith("-none-any.whl"))
            wheels.append({"file": pure["filename"], "url": pure["url"], "sha256": pure["digests"]["sha256"], "tag": ""})
            continue
        for python in PYTHONS:
            for tag, marker in PLATFORMS.items():
                found = [f for f in files if f"-{python}-{python}-" in f["filename"] and marker in f["filename"] and ("macosx" in f["filename"]) == tag.startswith("macos")]
                if not found:
                    sys.exit(f"no {name} {version} wheel for {python} {tag}")
                wheel = found[0]
                wheels.append({"file": wheel["filename"], "url": wheel["url"], "sha256": wheel["digests"]["sha256"], "tag": f"{python}-{tag}"})
    with open(LOCK, "w", encoding="utf-8") as handle:
        json.dump({"$comment": "Written by tools/vendor_sdk.py --update; read by tools/vendor_sdk.py.", "wheels": wheels}, handle, indent=1)
        handle.write("\n")
    print(f"pinned {len(wheels)} wheels in {os.path.relpath(LOCK, ROOT)}")


def fetch(wheel: dict) -> str:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, wheel["file"])
    if not os.path.exists(path) or sha256(path) != wheel["sha256"]:
        with urllib.request.urlopen(wheel["url"], timeout=120) as reply, open(path + ".part", "wb") as handle:
            shutil.copyfileobj(reply, handle)
        os.replace(path + ".part", path)
    if sha256(path) != wheel["sha256"]:
        sys.exit(f"{wheel['file']}: SHA-256 does not match the lock")
    return path


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def unpack() -> None:
    with open(LOCK, encoding="utf-8") as handle:
        wheels = json.load(handle)["wheels"]
    shutil.rmtree(TARGET, ignore_errors=True)
    for wheel in wheels:
        folder = os.path.join(TARGET, "native", wheel["tag"]) if wheel["tag"] else os.path.join(TARGET, "lib")
        with zipfile.ZipFile(fetch(wheel)) as archive:
            archive.extractall(folder)
    with open(os.path.join(TARGET, "README.txt"), "w", encoding="utf-8") as handle:
        handle.write("Unpacked by tools/vendor_sdk.py from the wheels pinned in tools/sdk_wheels.json. Do not edit.\n")
    print(f"unpacked {len(wheels)} wheels into {os.path.relpath(TARGET, ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="pin PINS anew from PyPI")
    args = parser.parse_args()
    if args.update:
        update()
    unpack()
    return 0


if __name__ == "__main__":
    sys.exit(main())
