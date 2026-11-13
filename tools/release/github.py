"""What the release scripts share: the gh CLI calls and the shapes they check.

The workflow passes GH_TOKEN and GH_REPO in the environment, never as arguments.
"""

import json
import re
import subprocess

PREFIX = "maya-plugin-v"
# The GitHub App that creates release-please's drafts and publishes them.
RELEASE_APP = "gh-actions-token-retriever-public[bot]"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
TAG_RE = re.compile(r"^maya-plugin-v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class ReleaseError(Exception):
    """A check that failed. Its message is ours and safe to print; any other
    error prints only its type, since API answers may hold private data."""


def gh(args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


def gh_json(args):
    return json.loads(gh(args))


def tag_version(tag):
    """(major, minor, patch) of a release tag, or None."""
    match = TAG_RE.match(tag or "")
    return tuple(int(part) for part in match.groups()) if match else None


def failure(prefix, error):
    message = str(error) if isinstance(error, ReleaseError) else type(error).__name__
    return f"::error::{prefix}: {message}\n"
