# Contributing to Scenario for Maya

Thanks for helping. This guide covers what a pull request needs; the commands,
rules and code map live in [AGENTS.md](AGENTS.md), which humans and coding
agents both follow.

## Before you start

- For anything larger than a small fix, open a change request first
  ([issue chooser](https://github.com/scenario-labs/maya-plugin/issues/new/choose))
  so the approach can be agreed before you write it.
- Read the spending rules in `AGENTS.md`: price check first, single-use quotes,
  paid calls sent once, `SCENARIO_NO_SPEND=1` honored. Every change keeps them.

## Set up

- Autodesk Maya 2025, 2026 or 2027 (0.1 is tested on Maya 2027.2). The core
  unit tests do not need Maya; the headless and GUI tests need a licensed Maya.
- Python 3.11 or 3.13 for the core tests, and [uv](https://docs.astral.sh/uv/)
  to run them and the linters.
- To run the plug-in from a checkout, add the repository root to
  `MAYA_MODULE_PATH`: `ScenarioForMaya.mod` there points Maya at the
  `ScenarioForMaya/` module folder. Then enable `scenario_for_maya` in the
  Plug-in Manager.

## Run the checks

`uv run --with pytest pytest -q` (the core unit tests on Python 3.11 and 3.13,
against a fake Scenario server, 0 CU), `tools/test_maya.sh` (headless mayapy
tests, needs a licensed Maya), `tools/test_maya_gui.sh` (a scripted GUI session
with screenshots, it opens Maya windows), `python3 tools/lint.py` (no em
dashes, no secrets, JSON parses), `uvx ruff check .` and
`uvx ruff format --check .`. AGENTS.md lists every check CI runs. Live checks
against Scenario need a test key; `python3 tools/contract_check.py` is free
(reads and dry runs only). Any paid run spends Creative Units and needs
authorization for the project and budget first.

## Commits and pull requests

- Branch from `main`. Pull requests are squash-merged: the PR title becomes the
  commit header and the changelog line, so it follows Conventional Commits with
  a scope listed in AGENTS.md, for example
  `fix(maya): keep the selection after applying a material`.
- Keep one concern per pull request and fill the template briefly: the checks
  you ran, the Maya version and OS you ran them on, any action needed after
  merge and any known gap. Tick only what you ran.
- Do not edit versions or `CHANGELOG.md` by hand.
- Show UI changes with before/after screenshots of the Scenario panel,
  attached to the pull request rather than committed.

## Coding agents

Agents follow AGENTS.md. Name the harness in the pull request and keep accurate
co-author trailers on commits and in the squash message. A human reviews the
complete diff before merge.

## Licensing

The repository is under the [MIT License](LICENSE). By contributing, you agree
that your contributions are licensed under the same terms. Code or assets
adopted from elsewhere keep their compatible license and attribution.
