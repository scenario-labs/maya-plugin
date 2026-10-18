# maya-plugin: agent instructions

Root `AGENTS.md` is the repository rulebook for humans and coding agents.
[README.md](README.md) describes the plug-in for users; the design is in
[docs/spec/SPEC.md](docs/spec/SPEC.md).

## What this repository is

Scenario for Maya: an Autodesk Maya plug-in for Maya 2025 to 2027, pure Python
(`maya.cmds`, OpenMaya 2.0, PySide6). It prices and runs every Scenario model
and workflow through the hosted Scenario MCP (`https://mcp.scenario.com/mcp`:
JSON-RPC 2.0 over HTTP, SSE or JSON replies, OAuth or an API key and secret),
lands the results in the open scene or applies them to the user's meshes as
undoable commands. People drive it from the Scenario panel; agents drive it
through a local MCP server inside Maya.

The Maya module is `ScenarioForMaya/`. A release ZIP holds that folder and
`install_scenario.py`; `ScenarioForMaya.mod` at the repository root points
Maya at the checkout for development (`MAYA_MODULE_PATH=<repo>`).

## Code map

`ScenarioForMaya/`:

- `plug-ins/scenario_for_maya.py`: the plug-in entry. Thin: puts the package
  beside it on the path, hands over to `maya/lifecycle.py`, forgets the
  package on unload so a reload runs fresh code. Maya sets no `__file__` for
  Python plug-ins.
- `scripts/install_scenario.py`: drag-and-drop installer and `uninstall()`.
  Stands alone (the package is not importable yet when it runs).
- `scripts/scenario_maya/core/` (no Maya import, unit-tested on plain Python):
  - `mcp.py`: JSON-RPC client, SSE or JSON replies, session renewal, retry
    policy (reads only), tool error parsing.
  - `backend.py`: the `ScenarioBackend` interface and its hosted Scenario MCP
    implementation; job normalization.
  - `session.py`: sign-in state, workspace, price checks, the one paid
    request, Not confirmed reviews. Every caller goes through it.
  - `quotes.py`: single-use quotes bound to payload, workspace and target.
  - `ledger.py`: the durable job list (SQLite in `<MAYA_APP_DIR>/scenario/`),
    state machine, crash recovery.
  - `auth.py`, `oauth.py`, `credstore.py`: API key and OAuth (browser with
    PKCE on a loopback port, device code), credential stores (macOS Keychain,
    Windows Credential Manager, Secret Service, owner-only file).
  - `schema.py`: model schema to form fields, validation, payloads.
  - `http.py`, `jsonutil.py`, `errors.py`, `paths.py`, `settings.py`,
    `status.py`, `workspaces.py`, `log.py`, `diagnostics.py`, `links.py`.
- `scripts/scenario_maya/maya/`: Maya side. `dispatcher.py` (workers do the
  network, the main thread does the scene), `runtime.py` (one runtime per
  Maya process), `lifecycle.py` (load and unload), `compat.py`.
- `scripts/scenario_maya/ui/`: PySide6. `panel.py` (the dockable
  `workspaceControl`), `signin.py`, `workspace.py`, `jobs.py`, `menu.py`,
  `commands.py` (runtime commands), `common.py`, `qt.py`.
- `scripts/scenario_maya/agent/`: the local MCP server (milestone M5).
- `scripts/scenario_maya/_vendor/`: `truststore`, unchanged, see
  `VENDORED.md`.

`tests/`: `unit/` (core, any Python), `maya/` (mayapy, headless), `gui/`
(scripted GUI session), `fake_backend/` (a fake Scenario MCP and OAuth
server), `fixtures/mcp/` (recorded replies, scrubbed).

## Spending rules

Every change keeps them. They are enforced in `core/session.py`,
`core/quotes.py`, `core/ledger.py` and `core/mcp.py`, below every caller.

1. A price check is a dry run (`model_run` with `dry_run: true`). It is free
   and returns the exact CU cost. A price check that returns a job stops all
   price checks for the session and the job is tracked.
2. Generate needs an unused quote for this exact payload, workspace and target
   and consumes it. Quotes expire after 120 seconds. Agents pass `quote_id`
   and `approved_cost` equal to the quote's exact CU string.
3. The intent row is written to the ledger before the paid request. If it
   cannot be written, nothing is sent.
4. A paid call is sent once. A 401 or an expired session is refused before
   the tool runs, so the token or session is renewed and the request sent once
   more. Any failure where Scenario may have started the work marks the job
   Not confirmed, which blocks an identical request until a person links it to
   a Scenario job or marks it reviewed. A 429 or a 4xx refusal is reported as
   not sent and never retried by itself.
5. `SCENARIO_NO_SPEND=1` refuses paid calls before any request.
6. Secrets live in the OS credential store only: never in settings, Maya
   preferences, the scene, logs, provenance or error messages.

## Commands

```sh
uv run --python 3.13 --with pytest pytest -q   # core unit tests, fake server, 0 CU (also 3.11)
tools/test_maya.sh                             # mayapy tests, headless (needs a licensed Maya)
tools/test_maya_gui.sh [install restart oauth] # scripted GUI session with screenshots; opens Maya windows
python3 tools/lint.py                          # no em dashes, no secrets, JSON parses
uvx ruff check . && uvx ruff format --check .
python3 tools/contract_check.py                # free live check, needs a test key
```

Every Maya run sets `MAYA_DISABLE_CER=1` so a crash never opens Autodesk's
crash reporter, and uses a throwaway `MAYA_APP_DIR`. Never run
`tools/test_maya_gui.sh` from a background agent: it opens windows.

`tools/contract_check.py` sends reads and dry runs only and refuses paid tools
itself. It needs `SCENARIO_API_KEY` and `SCENARIO_API_SECRET`, or on macOS a
Keychain item with the service `Scenario for Maya tests` (account = key id).
Any paid run needs explicit authorization for the project and budget first.

## CI

| Workflow | When | What |
| --- | --- | --- |
| `ci.yml` | pull requests, `main` | `lint` (tools/lint.py, ruff), `unit` (pytest on Python 3.11 and 3.13, Linux, macOS, Windows); `ci-ok` requires all |
| `contract.yml` | weekly, PRs changing `core/` or the tool | `tools/contract_check.py` with `SCENARIO_NO_SPEND=1`, 0 CU (test key secrets; skipped with a warning without them) |
| `links.yml` | weekly, docs PRs | links in Markdown |

GitHub runners have no Maya, so `tools/test_maya.sh` and
`tools/test_maya_gui.sh` run on a Mac with Maya before each release; their
reports go under `tests/reports/`.

## Rules

- No em dashes, in code, docs, commit messages and PR titles.
- This repository is public: no credentials, session IDs, personal paths,
  team, project, job or asset ids, account records, machine details or spend
  anecdotes in code, docs, commits or PRs.
- No code from `scenario-labs/blender-plugin` (GPL-3.0). Behaviour comes from
  the shared Scenario specs; the code here is written for this repository.
- `core/` never imports Maya. Network and file IO run on workers; scene work
  runs on the main thread through the dispatcher. Painting code never calls
  the network or `maya.cmds`.
- Never open or use Maya's `commandPort`.
- Never `cmds.file(i=True)` into a test scene meant to check undo: it erases
  the undo history.
- Tests write only to temporary folders and ignored folders
  (`tests/reports/tmp/`, `.cache/`).
- Keep doc edits in a feature PR to the prose the change makes wrong.

## Commits and pull requests

- Branch from `main`; pull requests are squash-merged, so the PR title becomes
  the commit header and the changelog line. Titles follow Conventional Commits
  with a scope: `core`, `maya`, `ui`, `agent`, `lanes`, `docs`, `tools`,
  `tests`, `ci`, `deps`, `release`, `repo`. Example:
  `fix(maya): keep the selection after applying a material`.
- Fill `.github/pull_request_template.md`; tick only what you ran.
- Screenshots of a visible change go in the PR description, never in a commit.
- Name the contributing agent in the PR and keep its co-author trailer on
  commits and in the squash message. A human reviews the complete diff before
  merge.
