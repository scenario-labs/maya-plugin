"""Repository checks CI runs on every pull request (no dependencies).

- No em dashes in tracked text files (house style).
- No credentials: API secrets, bearer tokens, signed URL query strings, private keys.
  A line that holds a deliberate fake value says so with ``# not a secret``.
- Every JSON file parses.
Ruff covers Python style separately (``uvx ruff check .``).
"""

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = (".py", ".md", ".json", ".yml", ".yaml", ".toml", ".txt", ".mel", ".mod", ".sh", ".html", ".css", ".js")
SKIP = ("ScenarioForMaya/scripts/scenario_maya/_vendor/",)
EM_DASH = "\u2014"
SECRETS = (
    (re.compile(r"(?i)(api[_-]?secret|client[_-]?secret|refresh[_-]?token|access[_-]?token)\s*[=:]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']"), "a credential value"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{24,}"), "a bearer token"),
    (re.compile(r"X-Amz-(Signature|Credential)=[A-Za-z0-9%/+=]{12,}"), "a signed URL"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
)
ALLOWED_SECRET_FILES = ("tools/lint.py",)


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.endswith(TEXT) and not line.startswith(SKIP)]


def main():
    problems = []
    for path in tracked_files():
        full = os.path.join(ROOT, path)
        try:
            with open(full, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError) as error:
            problems.append(f"{path}: unreadable ({error})")
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                problems.append(f"{path}:{number}: em dash")
        if path not in ALLOWED_SECRET_FILES:
            for pattern, what in SECRETS:
                for found in pattern.finditer(text):
                    number = text.count("\n", 0, found.start()) + 1
                    if "# not a secret" not in text.splitlines()[number - 1]:
                        problems.append(f"{path}:{number}: looks like {what}")
        if path.endswith(".json"):
            try:
                json.loads(text)
            except ValueError as error:
                problems.append(f"{path}: invalid JSON ({error})")
    for problem in problems:
        print(problem)
    print(f"lint: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
