<!--
The PR title becomes the squash commit header: type(scope): summary.
Use an imperative summary, no trailing period, and at most 120 characters.
Scopes: core, maya, ui, agent, lanes, docs, tools, tests, ci, deps,
release, repo (see AGENTS.md).
Example: fix(maya): keep the selection after applying a material

Keep one concern per PR and the description short. Tick only checks you did;
leave the rest unticked without comment. Never claim review, results or
authorization that has not happened.
-->

## What does this PR change?

<!--
One to three sentences: the problem and what changes. Add a before/after only
for a behavior change. Name any action needed after merge and any known gap.
Closes #n for complete issue scope; Refs #n otherwise, saying what remains.
Show a visible change with screenshots of the Scenario panel, before/after
for UI.
-->

## Validation

- [ ] `uv run --with pytest pytest -q` passes; for changes that touch Maya code, `tools/test_maya.sh` passes too. The Maya version and OS are listed below.
- [ ] `python3 tools/lint.py`, `uvx ruff check .` and `uvx ruff format --check .` pass.
- [ ] Packaging changes: the release ZIP installs by dragging `install_scenario.py` onto a Maya viewport with no errors or warnings in the Script Editor, and its contents were inspected.
- [ ] Maya or UI changes were tried in a Maya session (`tools/test_maya_gui.sh` or by hand), with before/after screenshots for UI.
- [ ] Live status is stated: `python3 tools/contract_check.py` (free) when calls to Scenario change; any paid run had prior authorization for its project and budget.

Commands and results:

<!-- One line per command run and its result. Keep the line above: it stops
GitHub merging this list into the checklist. -->

## Public content

- [ ] No credentials, tokens, signed URL query strings, or private account, team, project, job or asset IDs are included.
- [ ] No personal paths, machine details, agent session IDs or spend anecdotes are included.

## Rules

- [ ] The spending rules in `AGENTS.md` still hold (price check first, single-use quotes, paid calls sent once, `SCENARIO_NO_SPEND`).
- [ ] No unrelated manual version or changelog edits; documentation matches the resulting behavior.

## Authorship and licensing

- [ ] Human review of the complete diff is recorded before merge.
- [ ] Adopted third-party code or assets keep their compatible licenses and attribution; original contributions are licensed under MIT, the repository license.

<!-- If an agent contributed, name the harness and keep accurate co-author
trailers on commits and in the final squash message. -->
