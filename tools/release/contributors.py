"""Thanks a draft release's pull request authors, as GitHub's generated notes list them.

release-please's notes name no authors. The workflow runs this with
continue-on-error: a missing thank-you never holds back a release.

  GH_REPO=owner/repo TAG=maya-plugin-vX.Y.Z RELEASE_SHA=<sha> python3 tools/release/contributors.py

The notes cover the pull requests since the highest earlier release tag, or
since the first commit for the first release.
"""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from github import PREFIX, REPO_RE, SHA_RE, TAG_RE, ReleaseError, failure, gh, gh_json, tag_version  # noqa: E402

HEADING = "### Contributors"
AUTHOR_RE = re.compile(r" by @([A-Za-z0-9-]+(?:\[bot\])?) in https://\S+$")
FIRST_RE = re.compile(r"^\* @([A-Za-z0-9-]+) made their first contribution in https://\S+$")


def contributors(notes):
    """The human authors (sorted, one spelling each) and GitHub's first-contribution lines."""
    authors, first = {}, []
    for raw in notes.split("\n"):
        line = raw.strip()
        author = AUTHOR_RE.search(line)
        if author:
            login = author.group(1)
            if not login.endswith("[bot]"):
                authors.setdefault(login.lower(), login)
        elif FIRST_RE.match(line):
            first.append(line)
    return [authors[key] for key in sorted(authors)], first


def mention_list(logins):
    names = [f"@{login}" for login in logins]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def with_contributors(body, notes):
    """The body with a Contributors section, or None when there is nothing to add."""
    if re.search(rf"^{re.escape(HEADING)}\s*$", body, re.MULTILINE):
        return None
    logins, first = contributors(notes)
    if not logins:
        return None
    section = f"{HEADING}\n\nThanks to {mention_list(logins)}.\n"
    if first:
        section += "\n" + "\n".join(first) + "\n"
    return f"{body.rstrip()}\n\n{section}"


def previous_tag(repo, tag, request):
    """The highest release tag below ``tag``, or "" for the first release."""
    pages = request(["api", f"repos/{repo}/git/matching-refs/tags/{PREFIX}", "--paginate", "--slurp"])
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ReleaseError("GitHub returned an invalid tag list")
    current = tag_version(tag)
    best = None
    for ref in (ref for page in pages for ref in page):
        name = ref.get("ref", "").removeprefix("refs/tags/") if isinstance(ref, dict) else ""
        version = tag_version(name)
        if version and version < current and (best is None or version > best[1]):
            best = (name, version)
    return best[0] if best else ""


def update(repo, tag, sha, request=gh_json, run=gh):
    if not REPO_RE.match(repo or ""):
        raise ReleaseError("GH_REPO must identify an owner/repository")
    if not TAG_RE.match(tag or "") or not SHA_RE.match(sha or ""):
        raise ReleaseError("TAG and RELEASE_SHA must be a stable release tag and a full commit SHA")
    draft = request(["release", "view", tag, "--json", "body,isDraft,targetCommitish"])
    if draft.get("isDraft") is not True or str(draft.get("targetCommitish") or "").lower() != sha.lower():
        raise ReleaseError(f"{tag} is not the draft for {sha}")
    args = ["api", "--method", "POST", f"repos/{repo}/releases/generate-notes", "-f", f"tag_name={tag}", "-f", f"target_commitish={sha}"]
    previous = previous_tag(repo, tag, request)
    if previous:
        args += ["-f", f"previous_tag_name={previous}"]
    notes = request(args).get("body") or ""
    body = with_contributors(draft.get("body") or "", notes)
    if body is None:
        return False
    with tempfile.TemporaryDirectory(prefix="release-notes-") as folder:
        path = os.path.join(folder, "notes.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        run(["release", "edit", tag, "--notes-file", path])
    return True


def main(env=os.environ, request=gh_json, run=gh, out=sys.stdout, err=sys.stderr):
    try:
        changed = update(env.get("GH_REPO"), env.get("TAG"), env.get("RELEASE_SHA"), request, run)
        out.write("Added the Contributors section\n" if changed else "No Contributors section to add\n")
        return 0
    except Exception as error:  # noqa: BLE001 - every failure becomes one safe line
        err.write(failure("Cannot list release contributors", error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
