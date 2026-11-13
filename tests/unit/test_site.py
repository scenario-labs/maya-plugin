"""The page of maya.scenario.com (site/index.html) and its stamping."""

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "release"))

import stamp_site  # noqa: E402

PAGE = os.path.join(ROOT, "site", "index.html")


def page():
    with open(PAGE, encoding="utf-8") as handle:
        return handle.read()


def test_the_page_leads_to_the_download_and_names_only_the_support_address():
    html = page()
    assert 'href="/download/latest"' in html
    assert chr(0x2014) not in html, "no em dashes"
    assert set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", html)) == {"support@scenario.com"}


def test_every_local_file_the_page_uses_is_published():
    """``assets/`` ships with the page; ``media/`` is docs/media, copied in by pages.yml."""
    for ref in re.findall(r'(?:src|href)="([^"#:]+)"', page()):
        if ref.startswith("/"):
            continue  # served by the proxy: /download/latest, /page.js
        source = os.path.join(ROOT, "docs", ref) if ref.startswith("media/") else os.path.join(ROOT, "site", ref)
        assert os.path.isfile(source), ref


def test_stamping_fills_the_version_and_the_ref():
    out = stamp_site.stamp(page(), "0.2.0", "maya-plugin-v0.2.0")
    assert "{{" not in out and "scenario-maya-0.2.0.zip" in out and "/blob/maya-plugin-v0.2.0/README.md" in out


@pytest.mark.parametrize("version, ref", [("0.2", "main"), ("0.2.0", "feature"), ("0.2.0", "photoshop-plugin-v0.2.0")])
def test_stamping_refuses_what_is_not_a_release(version, ref):
    with pytest.raises(ValueError):
        stamp_site.stamp(page(), version, ref)
