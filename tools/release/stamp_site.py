"""Fills the page of maya.scenario.com with the release it describes.

``site/index.html`` says ``{{version}}`` where it names the build and ``{{ref}}``
in its links to the repository; ``.github/workflows/pages.yml`` stamps them with
the newest published release (its version and tag) when it publishes. The
repository spells no version in the page, so a release never leaves it naming
the one before. Ported from photoshop-plugin's ``tools/release/stamp-site.js``.

  python3 tools/release/stamp_site.py <page.html> <version> <ref>
"""

import re
import sys

VERSION = re.compile(r"^\d+\.\d+\.\d+$")
REF = re.compile(r"^(main|maya-plugin-v\d+\.\d+\.\d+)$")


def stamp(html, version, ref):
    if not VERSION.match(version):
        raise ValueError(f"Not a release version: {version!r}")
    if not REF.match(ref):
        raise ValueError(f"Not main or a release tag: {ref!r}")
    if "{{version}}" not in html:
        raise ValueError("The page has no {{version}} to fill")
    out = html.replace("{{version}}", version).replace("{{ref}}", ref)
    left = re.search(r"\{\{\s*[\w.-]+\s*\}\}", out)
    if left:
        raise ValueError(f"The page keeps {left.group(0)}")
    return out


def main(argv=sys.argv[1:]):
    if len(argv) != 3:
        sys.stderr.write("usage: python3 tools/release/stamp_site.py <page.html> <version> <ref>\n")
        return 2
    path, version, ref = argv
    try:
        with open(path, encoding="utf-8") as handle:
            html = stamp(handle.read(), version, ref)
    except ValueError as error:
        sys.stderr.write(f"stamp_site: {error}\n")
        return 1
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
