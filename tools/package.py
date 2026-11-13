"""Builds the release ZIP: dist/scenario-maya-<version>.zip.

It holds one folder, ``scenario-maya-<version>/``, with ``install_scenario.py``
(drag it onto a Maya viewport), the ``ScenarioForMaya`` module, its vendored
SDK (unpacked first by ``tools/vendor_sdk.py``) and the licence. Entries are
sorted and dated 1980-01-01, so the same commit always gives the same bytes.

Usage: python3 tools/package.py [--out dist]
"""

import argparse
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "ScenarioForMaya")
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_FILES = {".DS_Store"}


def version():
    with open(os.path.join(MODULE, "scripts", "scenario_maya", "__init__.py"), encoding="utf-8") as handle:
        return re.search(r'__version__\s*=\s*"([^"]+)"', handle.read()).group(1)


def contents():
    """(path in the ZIP below its top folder, file on disk), sorted."""
    out = [("install_scenario.py", os.path.join(MODULE, "scripts", "install_scenario.py")), ("LICENSE", os.path.join(ROOT, "LICENSE"))]
    for folder, dirs, files in os.walk(MODULE):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in files:
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            path = os.path.join(folder, name)
            out.append(("ScenarioForMaya/" + os.path.relpath(path, MODULE).replace(os.sep, "/"), path))
    return sorted(out)


def build(out_dir):
    name = f"scenario-maya-{version()}"
    target = os.path.join(out_dir, name + ".zip")
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(target + ".part", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for inner, path in contents():
            info = zipfile.ZipInfo(f"{name}/{inner}", date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16  # the same on every machine; Python loads modules without the execute bit
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(path, "rb") as handle:
                archive.writestr(info, handle.read())
    os.replace(target + ".part", target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = parser.parse_args()
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import vendor_sdk

    vendor_sdk.unpack()
    print(build(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
