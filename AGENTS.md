# maya-plugin: agent instructions

Root `AGENTS.md` is the repository rulebook for humans and coding agents.
[README.md](README.md) describes the plug-in for users; the design is in
[docs/spec/SPEC.md](docs/spec/SPEC.md).

## What this repository is

Scenario for Maya: an Autodesk Maya plug-in for Maya 2025 to 2027, in Python
(`maya.cmds`, OpenMaya 2.0, PySide6). It prices and runs every Scenario model
and workflow through Scenario's REST API (`https://api.cloud.scenario.com/v1`)
with Scenario's Python SDK (OAuth or an API key and secret),
lands the results in the open scene or applies them to the user's meshes as
undoable commands. People drive it from the Scenario panel; agents drive it
through a local MCP server inside Maya.

The Maya module is `ScenarioForMaya/`. A release ZIP (`tools/package.py`)
holds that folder, its vendored SDK and `install_scenario.py`;
`ScenarioForMaya.mod` at the repository root points Maya at the checkout for
development (`MAYA_MODULE_PATH=<repo>`). Releases are automated:
[RELEASING.md](RELEASING.md).

## Code map

`ScenarioForMaya/`:

- `plug-ins/scenario_for_maya.py`: the plug-in entry. Thin: puts the package
  beside it on the path, hands over to `maya/lifecycle.py`, forgets the
  package on unload so a reload runs fresh code. Maya sets no `__file__` for
  Python plug-ins.
- `scripts/install_scenario.py`: drag-and-drop installer and `uninstall()`.
  Stands alone (the package is not importable yet when it runs).
- `scripts/scenario_maya/core/` (no Maya import, unit-tested on plain Python):
  - `rest.py`: calls through the SDK (its HTTP client: OS trust store, system
    proxies, no redirects), workspace query, credential renewal, the paid-call
    rules, error kinds.
  - `sdk.py`: loads the vendored SDK, with the `pydantic_core` build for the
    running Python and platform, at the end of `sys.path`.
  - `backend.py`: the `ScenarioBackend` interface and its REST implementation;
    job normalization, model inputs to form fields, upload parts.
  - `session.py`: sign-in state, workspace, price checks, the one paid
    request, Not confirmed reviews. Every caller goes through it.
  - `quotes.py`: single-use quotes bound to payload, workspace and target.
  - `ledger.py`: the durable job list (SQLite in `<MAYA_APP_DIR>/scenario/`),
    state machine, crash recovery.
  - `auth.py`, `oauth.py`, `credstore.py`: API key and OAuth (browser with
    PKCE on a loopback port, device code), credential stores (macOS Keychain,
    Windows Credential Manager, Secret Service, owner-only file).
  - `schema.py`: model schema to form fields, validation, payloads.
  - `delivery.py`: follow a sent job (2 s reads, back-off, pause for review)
    and download its results into one folder with a `scenario.json` sidecar;
    for 3D, only the GLB, picked by the asset record's format.
  - `downloads.py`: one file per call: fresh signed link per attempt, `.part`
    resume with range requests, SHA-256 receipt, delivery host allow-list.
  - `gltf.py`: GLB reader (accessors, sparse, normalized), real file type
    by header, embedded textures written by role.
  - `gltf_write.py`: GLB writer, the reader's inverse (meshes, one UV set,
    normals, base colour textures, metres).
  - `edits.py`: Edit selection tasks (Remesh, UV unwrap, Retexture), each
    edit model's mesh field, formats and triangle cap, the checks made
    before a mesh is sent, mesh fingerprints.
  - `topology.py`: fit (uniform scale and offset from bounds), the
    matcher that proves an edit result is the sent surface (vertices,
    triangles tiling each face, one UV per face corner), and the sampled
    surface-distance check that a fitted result is the same shape.
  - `uploads.py`: a local file to a Scenario asset id: type read from the
    bytes, parts PUT to Scenario's links as given (no checksum headers), the
    same bytes reused within a session and workspace.
  - `catalog.py` (models per workspace and modality, cached 24 h),
    `lanes.py` (lane definitions: Image, 3D Text, Image, Multi-view, Edit selection and Motion modes; quick picks, presets, tag filters), `motion.py` (which motion models need, take or ignore a character; the scene's frame rate for a model's rate field), `provenance.py` (node attributes), `naming.py`.
  - `http.py`, `jsonutil.py`, `errors.py`, `paths.py`, `settings.py`,
    `status.py`, `workspaces.py`, `log.py`, `diagnostics.py`, `links.py`.
- `scripts/scenario_maya/maya/`: Maya side. `dispatcher.py` (workers do the
  network, the main thread does the scene), `runtime.py` (one runtime per
  Maya process), `jobs.py` (quote to landed result, recovery),
  `landing.py` (images as card, material or image plane, 3D models on the
  ground, at a matrix or fitted onto a box, one undo step each; the
  off-frame clip note), `import_command.py` (the recording `scenarioImport`
  command that makes any import one undo step), `fbx_import.py` (FBX results through Maya's `FBXImport`: options set per import, root namespace then renamed in, timeline and up axis kept, importer's materials kept, skinned meshes not inheriting, clip moved to the start frame), `glb_builder.py` (GLB to
  meshes, materials, joints, skins, blend shapes and keys; import checks), `scene.py` (project folders, camera, selection, scene id),
  `capture.py` (a viewport still for a model input, and the selection from named sides for multi-view models; outside the undo queue),
  `mesh_export.py` (selected meshes to the GLB sent for an edit or as a
  motion's character, with the record kept to find and fit the result), `apply.py` (edit results back
  on the mesh: target by UUID, fit against the kept sent file; Apply as
  gather, compare, run with a review: Replace UVs, textures or geometry), `uv_command.py` (the undoable
  `scenarioSetUVs` command),
  `lifecycle.py` (load and unload), `compat.py`.
- `scripts/scenario_maya/ui/`: PySide6. `panel.py` (the dockable
  `workspaceControl`), `lane.py` (a lane: model, prompt, settings, priced
  Generate, result cards), `inputs.py` (the image row: file, viewport
  capture, Image results; the Multi-view row: one slot per named view, Capture views), `mesh_input.py` (the Edit selection row: task,
  Use selection, checks, send; the Motion mode's character row), `apply_review.py` (the Apply review), `fields.py` (settings from a model schema),
  `picker.py`, `signin.py`, `workspace.py`, `jobs.py`, `menu.py`,
  `commands.py` (runtime commands), `common.py`, `qt.py`.
- `scripts/scenario_maya/agent/`: the local MCP server (milestone M5).
- `scripts/scenario_maya/_vendor/`: `truststore`, unchanged, and `sdk/`
  (Scenario's SDK and its dependencies, unpacked by `tools/vendor_sdk.py`, not
  in git), see `VENDORED.md`.

`tests/`: `glb_samples.py` (hand-written GLB fixtures), `site/` (the Vercel middleware of maya.scenario.com, Node's test runner), `unit/` (core, any Python), `maya/` (mayapy, headless), `gui/`
(scripted GUI session), `fake_backend/` (a fake Scenario REST API and OAuth
server), `fixtures/mcp/` (recorded model schemas, scrubbed; the fake turns them
back into the API's shape).

## Spending rules

Every change keeps them. They are enforced in `core/session.py`,
`core/quotes.py`, `core/ledger.py` and `core/rest.py`, below every caller.

1. A price check is a dry run (`POST /generate/custom/{modelId}` with
   `dryRun=true`, answered 269). It is free
   and returns the exact CU cost. A price check that returns a job stops all
   price checks for the session and the job is tracked.
2. Generate needs an unused quote for this exact payload, workspace and target
   and consumes it. Quotes expire after 120 seconds. Agents pass `quote_id`
   and `approved_cost` equal to the quote's exact CU string.
3. The intent row is written to the ledger before the paid request. If it
   cannot be written, nothing is sent.
4. A paid call is sent once, with the SDK's retries off. A refused token (403
   with `x-amzn-errortype: AccessDeniedException`, or 401) is refused by the
   API's gateway before any handler runs, so the token is renewed and the
   request sent once more. Any failure where Scenario may have started the work marks the job
   Not confirmed, which blocks an identical request until a person links it to
   a Scenario job or marks it reviewed. A 429 or a 4xx refusal is reported as
   not sent and never retried by itself.
5. `SCENARIO_NO_SPEND=1` refuses paid calls before any request.
6. Secrets live in the OS credential store only: never in settings, Maya
   preferences, the scene, logs, provenance or error messages.

## Commands

```sh
uv run --python 3.13 --no-project python tools/vendor_sdk.py  # once, and after a pin change: unpack the SDK into _vendor/sdk
uv run --python 3.13 --with pytest pytest -q   # core unit tests, fake server, 0 CU (also 3.11)
tools/test_maya.sh                             # mayapy tests, headless (needs a licensed Maya)
tools/test_maya_gui.sh [install generate restart oauth] # scripted GUI session with screenshots; opens Maya windows; generate spends a few CU
tools/readme_media.sh <signed-in MAYA_APP_DIR> # README pictures, GIFs and videos from a real session; opens Maya; spends one image and one 3D model
MAYA_DISABLE_CER=1 mayapy tools/render_glb.py result.glb out/ --turn 60 --gif out/turn.gif  # Viewport 2.0 stills or a turntable of a GLB or FBX, headless, 0 CU
python3 tools/lint.py                          # no em dashes, no secrets, JSON parses
node --test tests/site/*.test.js               # the maya.scenario.com proxy (Node of .nvmrc)
uvx ruff check . && uvx ruff format --check .
python3 tools/contract_check.py                # free live check, needs a test key
uv run --python 3.13 --no-project python tools/package.py  # dist/scenario-maya-<version>.zip, the release ZIP
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
| `ci.yml` | pull requests, `main` | `lint` (tools/lint.py, ruff), `site proxy` (`tests/site/` on the Node of `.nvmrc`), `unit` (pytest on Python 3.11 and 3.13, Linux, macOS, Windows); `ci-ok` requires all three; `coverage` measures the PR head and `upload-coverage` sends it to GitHub code coverage (skipped on fork PRs), neither required |
| `pr-name.yml`, `commitlint.yml` | pull requests | `pr-title` and `commits`: the PR title and each commit against `commitlint.config.mjs` |
| `contract.yml` | weekly, PRs changing `core/` or the tool | `tools/contract_check.py` with `SCENARIO_NO_SPEND=1`, 0 CU (test key secrets; skipped with a warning without them) |
| `links.yml` | weekly, docs PRs | links in Markdown |
| `scorecard.yml` | weekly, `main` | OpenSSF Scorecard |
| `project.yml` | non-draft PRs, when opened, reopened or marked ready (not Dependabot's) | adds them to the Plugins project (31) |
| `release-please.yml` | push to `main` | the release PR; once merged, builds, checks, attests and attaches the ZIP to a draft, checks it again on macOS, publishes it (RELEASING.md) |
| `publish-changelog.yml` | release published, or by hand | posts the release notes to www.scenario.com/changelog |
| `pages.yml` | after `release-please`, changes to the docs, by hand | publishes maya.scenario.com with scenario-labs/plugin-site: the handbook from the release's docs (`handbook.config.json`), the release ZIP under `/download/` (RELEASING.md, Site) |

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
  `tests`, `ci`, `deps`, `release`, `repo` (the list in
  `commitlint.config.mjs`, which the `pr-title` check applies). Example:
  `fix(maya): keep the selection after applying a material`.
- Fill `.github/pull_request_template.md`; tick only what you ran.
- Screenshots of a visible change go in the PR description, never in a commit.
  The one exception is `docs/media/`, the README's pictures and recordings,
  made by `tools/readme_media.sh` with the team and account names masked,
  and `tools/render_glb.py` (renders of a result, no interface in them);
  look at every file before committing it.
- Name the contributing agent in the PR and keep its co-author trailer on
  commits and in the squash message. A human reviews the complete diff before
  merge.
