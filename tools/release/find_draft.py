"""Finds a release draft left by an earlier run of the release workflow.

A draft has no tag yet, which hides it from release-please, so without this a
failed run would get a second draft. Only the run of the draft's own commit may
finish it: a later push to main fails here instead of building the draft from
newer code.

  GH_REPO=owner/repo GITHUB_SHA=<sha> GITHUB_OUTPUT=<file> python3 tools/release/find_draft.py

Writes found=false, or found=true with tag_name, sha and release_id, to
GITHUB_OUTPUT, and only after every check passed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from github import PREFIX, RELEASE_APP, REPO_RE, SHA_RE, TAG_RE, ReleaseError, failure, gh_json  # noqa: E402


def find_draft(repo, current_sha, request=gh_json):
    if not REPO_RE.match(repo or ""):
        raise ReleaseError("GH_REPO must identify an owner/repository")
    if not SHA_RE.match(current_sha or ""):
        raise ReleaseError("GITHUB_SHA must be a full commit SHA")
    pages = request(["api", f"repos/{repo}/releases?per_page=100", "--paginate", "--slurp"])
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ReleaseError("GitHub returned an invalid paginated release list")
    drafts = []
    for page in pages:
        for release in page:
            if not isinstance(release, dict):
                raise ReleaseError("GitHub returned an invalid release")
            tag = release.get("tag_name")
            if release.get("draft") is True and isinstance(tag, str) and tag.startswith(PREFIX):
                drafts.append(release)
    if len(drafts) > 1:
        raise ReleaseError("Multiple Maya release drafts exist; resolve them before retrying")
    if not drafts:
        return {"found": "false"}
    draft = drafts[0]
    if not TAG_RE.match(draft["tag_name"]) or draft.get("prerelease") is not False:
        raise ReleaseError("The pending draft must have a stable maya-plugin-vX.Y.Z tag")
    if (draft.get("author") or {}).get("login") != RELEASE_APP:
        raise ReleaseError("The pending draft was not created by the release GitHub App")
    sha = draft.get("target_commitish")
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        raise ReleaseError("The pending draft must target a full commit SHA, not a branch")
    if not isinstance(draft.get("id"), int) or draft["id"] <= 0:
        raise ReleaseError("The pending draft has no valid release ID")
    if sha.lower() != current_sha.lower():
        raise ReleaseError(f"Rerun the original release workflow for {sha.lower()}; newer pushes must not rebuild this draft")
    return {"found": "true", "tag_name": draft["tag_name"], "sha": sha.lower(), "release_id": str(draft["id"])}


def main(env=os.environ, request=gh_json, err=sys.stderr):
    try:
        outputs = find_draft(env.get("GH_REPO"), env.get("GITHUB_SHA"), request)
        if not env.get("GITHUB_OUTPUT"):
            raise ReleaseError("GITHUB_OUTPUT is not set")
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write("".join(f"{key}={value}\n" for key, value in outputs.items()))
        return 0
    except Exception as error:  # noqa: BLE001 - every failure becomes one safe line
        err.write(failure("Cannot recover a release draft", error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
