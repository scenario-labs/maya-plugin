"""Checks a release ZIP against the checkout it claims to come from.

  python3 tools/release/check_package.py dist/scenario-maya-X.Y.Z.zip X.Y.Z

The ZIP must hold exactly the files ``tools/package.py`` takes from this
checkout, byte for byte (the vendored SDK included, so run
``tools/vendor_sdk.py`` first), under ``scenario-maya-X.Y.Z/``; the plug-in's
version must be X.Y.Z, and every ``pydantic_core`` build Maya needs must be in.
"""

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import package  # noqa: E402
import vendor_sdk  # noqa: E402

BUILDS = [f"{python}-{platform}" for python in vendor_sdk.PYTHONS for platform in vendor_sdk.PLATFORMS]


def check(path, expected_version):
    problems = []
    if package.version() != expected_version:
        problems.append(f"the checkout is version {package.version()}, not {expected_version}")
    top = f"scenario-maya-{expected_version}/"
    if os.path.basename(path) != f"scenario-maya-{expected_version}.zip":
        problems.append(f"the file is named {os.path.basename(path)}")
    expected = dict(package.contents())
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        outside = [name for name in names if not name.startswith(top)]
        if outside:
            problems.append(f"{len(outside)} entries outside {top}")
        found = {name[len(top) :]: name for name in names if name.startswith(top)}
        for inner in sorted(set(expected) - set(found)):
            problems.append(f"missing {inner}")
        for inner in sorted(set(found) - set(expected)):
            problems.append(f"unexpected {inner}")
        for inner in sorted(set(expected) & set(found)):
            with open(expected[inner], "rb") as handle:
                if archive.read(found[inner]) != handle.read():
                    problems.append(f"{inner} differs from the checkout")
    for build in BUILDS:
        if not any(inner.startswith(f"ScenarioForMaya/scripts/scenario_maya/_vendor/sdk/native/{build}/pydantic_core/") for inner in expected):
            problems.append(f"no pydantic_core build for {build}")
    return problems


def main(argv=sys.argv[1:]):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    problems = check(argv[0], argv[1])
    for problem in problems:
        print(f"::error::{problem}")
    print(f"{argv[0]}: {'OK' if not problems else str(len(problems)) + ' problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
