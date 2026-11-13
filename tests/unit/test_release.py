"""Release tools: the draft finder, the contributors section, the ZIP and its check (fake GitHub answers, 0 CU)."""

import io
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "release"))

import check_package  # noqa: E402
import contributors  # noqa: E402
import find_draft  # noqa: E402
import package  # noqa: E402
from github import RELEASE_APP, ReleaseError  # noqa: E402

SHA = "a" * 40
OTHER = "b" * 40


def draft(tag="maya-plugin-v0.2.0", sha=SHA, author=RELEASE_APP, **extra):
    return dict({"id": 7, "draft": True, "prerelease": False, "tag_name": tag, "target_commitish": sha, "author": {"login": author}}, **extra)


def test_no_draft_is_found_false():
    assert find_draft.find_draft("o/r", SHA, lambda args: [[{"draft": False, "tag_name": "maya-plugin-v0.1.0"}]]) == {"found": "false"}


def test_the_draft_of_this_commit_is_handed_back():
    out = find_draft.find_draft("o/r", SHA, lambda args: [[draft()]])
    assert out == {"found": "true", "tag_name": "maya-plugin-v0.2.0", "sha": SHA, "release_id": "7"}


@pytest.mark.parametrize(
    "release, message",
    [
        (draft(sha=OTHER), "Rerun the original release workflow"),
        (draft(author="someone"), "not created by the release GitHub App"),
        (draft(sha="main"), "full commit SHA"),
        (draft(tag="maya-plugin-v0.2.0-beta"), "stable"),
    ],
)
def test_a_draft_that_is_not_ours_to_finish_stops_the_run(release, message):
    with pytest.raises(ReleaseError, match=message):
        find_draft.find_draft("o/r", SHA, lambda args: [[release]])


def test_two_drafts_stop_the_run():
    with pytest.raises(ReleaseError, match="Multiple"):
        find_draft.find_draft("o/r", SHA, lambda args: [[draft(), draft(tag="maya-plugin-v0.3.0")]])


def test_main_writes_outputs_only_after_every_check(tmp_path):
    output = tmp_path / "out"
    err = io.StringIO()
    assert find_draft.main({"GH_REPO": "o/r", "GITHUB_SHA": SHA, "GITHUB_OUTPUT": str(output)}, lambda args: [[draft(sha=OTHER)]], err) == 1
    assert not output.exists() and err.getvalue().startswith("::error::")
    assert find_draft.main({"GH_REPO": "o/r", "GITHUB_SHA": SHA, "GITHUB_OUTPUT": str(output)}, lambda args: [[draft()]], err) == 0
    assert "found=true\n" in output.read_text()


NOTES = """## What's Changed
* feat(core): one by @alice in https://github.com/o/r/pull/1
* fix(ui): two by @Bob in https://github.com/o/r/pull/2
* chore(deps): three by @dependabot[bot] in https://github.com/o/r/pull/3
* fix(ui): four by @bob in https://github.com/o/r/pull/4

## New Contributors
* @alice made their first contribution in https://github.com/o/r/pull/1
"""


def test_contributors_are_the_human_authors_once_each():
    logins, first = contributors.contributors(NOTES)
    assert logins == ["alice", "Bob"] and len(first) == 1


def test_the_section_is_added_once():
    body = contributors.with_contributors("### Features\n\n* one\n", NOTES)
    assert body.endswith("### Contributors\n\nThanks to @alice and @Bob.\n\n* @alice made their first contribution in https://github.com/o/r/pull/1\n")
    assert contributors.with_contributors(body, NOTES) is None


def test_the_first_release_has_no_previous_tag():
    assert contributors.previous_tag("o/r", "maya-plugin-v0.1.0", lambda args: [[]]) == ""
    refs = [[{"ref": "refs/tags/maya-plugin-v0.1.0"}, {"ref": "refs/tags/maya-plugin-v0.3.0"}, {"ref": "refs/tags/maya-plugin-v0.2.1"}]]
    assert contributors.previous_tag("o/r", "maya-plugin-v0.3.0", lambda args: refs) == "maya-plugin-v0.2.1"


def test_the_zip_holds_the_module_installer_and_licence(tmp_path):
    path = package.build(str(tmp_path))
    top = f"scenario-maya-{package.version()}/"
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        dates = {info.date_time for info in archive.infolist()}
    assert {top + "install_scenario.py", top + "LICENSE", top + "ScenarioForMaya/plug-ins/scenario_for_maya.py"} <= names
    assert not [name for name in names if "__pycache__" in name or name.endswith((".pyc", ".DS_Store"))]
    assert dates == {(1980, 1, 1, 0, 0, 0)}, "dated alike, so the same commit gives the same bytes"


def test_the_check_finds_a_changed_file(tmp_path):
    path = package.build(str(tmp_path))
    version = package.version()
    assert [p for p in check_package.check(path, version) if not p.startswith("no pydantic_core build")] == []
    changed = tmp_path / "changed" / os.path.basename(path)
    changed.parent.mkdir()
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(changed, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            target.writestr(info, data + b"#" if info.filename.endswith("install_scenario.py") else data)
    assert "install_scenario.py differs from the checkout" in check_package.check(str(changed), version)
    assert any("not 9.9.9" in p for p in check_package.check(path, "9.9.9"))


def test_the_check_refuses_a_name_twice(tmp_path):
    path = package.build(str(tmp_path))
    doubled = tmp_path / "doubled" / os.path.basename(path)
    doubled.parent.mkdir()
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(doubled, "w") as target, pytest.warns(UserWarning, match="Duplicate name"):
        for info in source.infolist():
            if info.filename.endswith("install_scenario.py"):
                target.writestr(info.filename, b"tampered")
            target.writestr(info, source.read(info))
    assert any("more than once" in p for p in check_package.check(str(doubled), package.version()))
