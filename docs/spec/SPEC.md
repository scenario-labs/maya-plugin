# Scenario for Maya: Spec v1

Status: **approved 2026-10-19**, with the decisions recorded in section 16. Drafted 2026-10-18. Repository: `scenario-labs/maya-plugin`, created locally, no remote, nothing pushed until the plug-in is built and tested end to end in a real Maya session.

This spec covers the product, the architecture and the plan for a Maya plug-in that gives an artist or an AI agent the whole Scenario platform from inside Autodesk Maya: every model, the team's trained models, workflows, the asset library and prompt tools, with the deepest support for 3D (generate, remesh, retexture, UV unwrap, rig, animate, split into parts) and results landing as native Maya nodes. It follows the money and trust contract shared by the Scenario plug-ins for Blender, Godot, Unity and Unreal, and adapts it to Maya.

Facts are marked **[verified]** when they were checked on 2026-10-18 in a source (Autodesk documentation, the Maya 2027.2 install, the hosted Scenario MCP, our own plug-ins) or in a live headless test with `mayapy` 2027.2, and **[to verify]** when they are reasoned but not yet checked. Live tests ran headless only; nothing has run in the Maya GUI yet. Section 17 lists what is verified and what is assumed.

---

## 0. Verdict

1. **One action layer, three drivers.** A dockable Scenario panel, a larger Studio window and a quick composer for artists; a local MCP server inside Maya for agents; a Python API for scripts, `mayapy` batch jobs and other tools. All three call the same actions, so the same price checks, approvals, import code, undo and provenance apply whoever drives.
2. **Pure Python, no compiled code.** `maya.cmds`, OpenMaya API 2.0 and PySide6, one code base for Maya 2025, 2026 and 2027 on Windows, macOS and Linux. No per-version binaries, nothing to sign, and the same code runs in the GUI and in `mayapy`.
3. **Maya 2025, 2026 and 2027.** Developed and tested live on 2027.2 (macOS, Apple Silicon). 2025 and 2026 share Python 3.11 and PySide6 6.5; 2027 moves to Python 3.13 and PySide6 6.8. The plug-in is written for both.
4. **Sign in with Scenario in one click.** Browser sign-in (OAuth authorization code with PKCE, loopback redirect) through the hosted Scenario MCP, with a device code fallback for remote machines. API key and secret, and environment variables, for CI and headless use. Secrets live in the OS credential store, never in the scene, the Maya project or Maya's preferences.
5. **The hosted Scenario MCP is the API**, as in the Godot, Unity and Unreal plug-ins: one JSON-RPC client, every model and tool, OAuth accepted. The transport sits behind an interface so the REST API can replace it later.
6. **GLB lands through our own reader.** Maya 2025 to 2027 ship no glTF importer [verified], and Scenario's 3D outputs are GLB first. A pure-Python GLB reader (prototyped: meshes, UVs, normals, PBR materials, skins, skeletal animation, blend shapes, all matching Maya USD's own import to the centimetre on a reference character [verified]) builds Maya nodes directly. FBX through Maya's FBX plug-in is the fallback and the route for Maya-targeted outputs.
7. **3D apply modes on the user's own meshes.** Beyond "import as new", a result can replace geometry, replace UVs, replace textures, split the mesh into parts, attach a returned rig and weights, apply returned animation onto an existing skeleton (with HumanIK retargeting for bipeds) or add face shapes, each with preconditions checked first, a review that says exactly what will change, one Ctrl+Z, and a kept original. Every mode was prototyped headless in Maya 2027.2 with exact undo and redo [verified].
8. **Price before every paid call, never a double charge.** The Generate button carries the exact price from a free dry run bound to the payload. A quote is used once. Paid calls are never retried; an uncertain submission blocks an identical one until it is reconciled.
9. **Agents are first-class but contained.** The MCP server listens on loopback with a token. Reading the scene is always allowed; changing the scene needs the "Allow agents to change this scene" switch (off by default), running Python needs a second switch, and spending needs a quote the server issued. A call with a valid quote is approved automatically, with no prompt and no cap, the same rule as every Scenario plug-in.

---

## 1. Goals, non-goals, users

### 1.1 Goals

- Anyone in Maya reaches every Scenario model and workflow without leaving Maya, and gets a usable Maya result (wired materials, skinned meshes, keyed clips, a lit sky dome), placed where it is needed, in one more click.
- 3D is the deepest lane: a generated or edited mesh lands with correct scale, axis, materials and color spaces; edits can land on the user's existing mesh, not only beside it.
- First generation in under two minutes from a fresh install, sign-in included.
- The price is visible before any spend, and every spend is explicit (a click by a person, or a quote-bound call by an agent).
- Everything generated is traceable: select any node and see which model, prompt, job and cost produced it, and list every Scenario node in a scene.
- Agents (Claude Code, Codex, Cursor, Claude Desktop) can generate and land results with the same safety rules as a person, and cannot change the scene unless the user allows it.
- Works for film and VFX, animation, games, previs, archviz, product visualization, training content.

### 1.2 Non-goals

- A chat assistant inside Maya. Agents run in the user's own client.
- Generic Maya automation (modeling tools, rigging tools, render farm submission). Agents can already script Maya; our tools stay focused on Scenario results and the scene reads they need. Python execution exists, gated.
- Model training, workflow authoring, team administration and billing. These stay in the Scenario web app and the hosted Scenario MCP; the plug-in links to them.
- Rendering Gaussian splats in Viewport 2.0 (Arnold renders PLY splats; see 6.6).
- Maya LT and Maya 2024 or older.

### 1.3 Target users and their jobs

| User | Job to be done | What the plug-in gives them |
|---|---|---|
| Animation or VFX artist | "Give me a hero prop for this shot, a sky that matches the plate, and temp music on the cut." | Prompt, see the price, generate; the prop lands at the camera's interest point with openPBR or Arnold materials; the sky dome is lit; the sound is on the Time Slider at the current frame. |
| Game tech artist | "Retopologize, UV and retexture this AI mesh, keep our naming, and prove where every asset came from." | Mesh edits on the selected mesh with apply modes, Maya's own retopology and UV as follow-ups, namespaces and naming from project settings, provenance attributes on every node. |
| Rigger | "Auto-rig this character, keep my mesh and UVs, and give me clean weights to start from." | Attach rig: the returned skeleton and weights are bound to the user's own mesh when the surface matches; a weight check report; HumanIK characterization as the next step. |
| Animator and previs artist | "Put a walk on my character, turn this reference video into motion, and restyle my playblast into a look test." | Apply animation onto the existing skeleton (names, hierarchy and rest pose checked), clips as Time Editor clips or on an animation layer, Render Video from a playblast range. |
| Pipeline TD | "Run 200 asset generations overnight in `mayapy`, and give agents a safe way in." | Python API with environment credentials, headless server mode, the same money rules, `SCENARIO_NO_SPEND` for dry runs, a module that deploys like any studio module. |
| Agent-driven pipeline | "Claude, block out a forest clearing with generated props and a sky, and keep me in control of spend." | Local MCP server with Scenario and landing tools, one-click client setup, every spend shown in Maya, mutate switch, read-back results. |

### 1.4 What we learned from other tools

From a survey of AI and agent integrations for Maya (Autodesk's own, community Maya MCP servers, third-party AI asset plug-ins, and AI plug-ins in Houdini, 3ds Max and Substance), done on 2026-10-18:

- **Autodesk ships no MCP server or agent API for Maya.** Autodesk Assistant in Maya 2027 is a documentation chatbot; Autodesk's MCP servers cover Fusion, Revit and product help [verified]. The one open generative hook is the LookdevX Generative Textures API (image and texture models, experimental) [verified].
- **Community Maya MCP servers are small** (the largest has about 100 stars), mostly single-maintainer, and many rely on Maya's `commandPort`, which has no authentication and runs any command with the user's rights [verified]. One evaluation found most agent calls going through raw Python and typed tools returning success while doing nothing [verified].
- **Third-party AI asset plug-ins for Maya are one-way importers.** None of those read shows a price before running, documents undo, recovers jobs after a restart, or works on a mesh already in the scene (one exception auto-rigs a selected mesh) [verified, from public pages].
- **Maya users expect** a docked PySide6 panel, a shelf and a menu, Hypershade-readable material networks, Arnold awareness, HumanIK compatibility, namespaces, respected units and up axis, and one Ctrl+Z per action [inferred from the survey].
- From our own Blender plug-in (the product benchmark): apply modes with surface matching and a review before apply, the job ledger with intent saved before submit, human-only reconciliation of uncertain submissions, and the MCP tool vocabulary. From the Unreal spec: the action layer, the import checks on every 3D result, and "never return OK on a no-op".

---

## 2. Maya versions and platforms

### 2.1 Versions

| Version | Latest update | Python | PySide6 / Qt | Maya USD | Role in v1 |
|---|---|---|---|---|---|
| 2027 | 2027.2 (July 2026) | 3.13.9 [verified live] | 6.8.3 [verified live] | 0.37.0, USD 25.11 [verified live] | Primary. Developed and tested live. Required by the Autodesk Marketplace. |
| 2026 | 2026.3 (November 2025) | 3.11.9 [verified: Autodesk table] | 6.5.3 | 0.31 to 0.34 | Supported. Test suite in its `mayapy` [to verify: needs an install]. |
| 2025 | 2025.3 (October 2024) | 3.11.x [verified: Autodesk table] | 6.5.3 | 0.27 and later | Supported. Floor for v1: first Qt 6 release. |
| 2024 and older | | 3.10 / PySide2 | | | Not supported: Qt 5 and PySide2 would double the UI work. |
| Maya Creative | | | | | Not supported in v1. Autodesk's comparison page does not list third-party plug-in loading for Creative, while its installers write Creative module folders for some partners [verified]. Detected at runtime (`cmds.about(creativeVersion=True)`) with a clear message. |
| Maya Indie | | | | | Supported: described by Autodesk as the same features as Maya [verified, secondary]. |

Code rules: Python 3.11 syntax, nothing removed in 3.12 or 3.13 (`distutils`, `imp`, `cgi`, `imghdr`, `urlopen(cafile=...)`); PySide6 fully scoped enums (the old enum style was removed in 6.6); API 2.0 everywhere except `MQtUtil` (only in API 1.0 `maya.OpenMayaUI`). No PyMEL: not shipped since Maya 2023 [verified]. A small `compat` module holds the few version branches.

### 2.2 Platforms

| Platform | Maya 2027 minimum | Test plan in v0.1 |
|---|---|---|
| macOS 14 or later (Apple Silicon and Intel) | macOS 14 [verified, secondary] | Live tests, GUI and `mayapy` |
| Windows 11 x64 | Windows 11 | Core tests on GitHub runners; Maya paths written but untested live (no Windows machine) |
| Linux (RHEL or Rocky 8.10 and 9.7) | RHEL/Rocky 8.10, 9.7 | Core tests on GitHub runners; Maya paths written but untested live |

The platform-specific code is small and isolated: credential store, folder locations, video encoding and audio decoding fallbacks.

---

## 3. Architecture

### 3.1 Python only

| Option | For | Against | Decision |
|---|---|---|---|
| Pure Python (cmds, OpenMaya 2.0, PySide6) | One code base for three Maya versions and three OSes; no compile, no signing, no binary per Maya point release; same code in GUI and `mayapy`; reviewable | Slower for very heavy loops | **Everything** |
| C++ devkit plug-in | Speed for per-vertex work | A binary per Maya version and OS, notarization on macOS, a devkit toolchain in CI, a much slower release cycle | **No.** Measured: the prototype GLB reader built each test sample, a skinned and animated character included, in 0.01 to 0.07 s [verified]; numpy ships with Maya for heavier arrays. Large meshes are measured in M3; revisit only if a profiled hot path needs it. |

One community Maya MCP server built in C++ ships a separate binary for each Maya point release (2027.1 and 2027.2) [verified]; staying pure Python avoids that.

### 3.2 Modules

```
ScenarioForMaya/                      the Maya module (one folder, see 11.1)
  ScenarioForMaya.mod
  plug-ins/scenario_for_maya.py        Maya plug-in entry: registers commands, menu, shelf,
                                       callbacks, starts the agent server (GUI); thin
  scripts/scenario_maya/
    core/          No Maya import. Backend client (Scenario MCP over JSON-RPC, SSE, session,
                   error kinds, retry policy), auth (OAuth PKCE + device code, API key),
                   credstore (Keychain, Credential Manager, Secret Service, file), quotes,
                   job ledger, schema forms, catalog cache, downloads, uploads, naming,
                   CU formatting, glTF parser (numpy), provenance records.
    maya/          Maya side. Main-thread dispatcher, actions (generate, capture, import,
                   apply, organize), importers per kind (GLB builder, FBX, USD, images,
                   PBR, sky, video, audio), apply modes, surface matching, mesh export
                   (GLB writer, FBX), captures, provenance attributes, undoable commands
                   (MPxCommand), scene checks.
    ui/            PySide6. Panel, Studio window, composer, model picker, jobs, results,
                   apply review dialog, sign-in, settings, Attribute Editor section.
    agent/         Local MCP server (loopback HTTP listener, protocol, tools, approvals,
                   activity log), client setup writers, headless runner.
    api.py         Public Python API (same actions), used by scripts, mayapy jobs and
                   other tools.
  vendor/          Pure-Python dependencies, imported under a private name (truststore only
                   in v1).
  icons/           Plug-in icons (added to XBMLANGPATH by the module).
  docs/agent-skill/ Pointer to the scenario-maya skill (section 9).
```

`core` imports nothing from Maya, so it is unit-tested with plain Python 3.11 and 3.13 on any machine, the same way the other plug-ins test their cores.

### 3.3 Threading and the job layer

Maya commands and OpenMaya are main-thread only [verified: Autodesk docs]. The plug-in never blocks the main thread on the network, and never touches the scene from a worker.

```
Worker threads (ThreadPoolExecutor, 4)            Main thread (Maya)
  HTTPS to mcp.scenario.com (urllib + truststore)   UI, scene reads, imports, applies
  downloads to .part, SHA-256, atomic rename        <- results through the dispatcher
  uploads (presigned multipart PUTs)                 dispatcher drained by:
  GLB parsing into numpy arrays                        GUI: a QTimer (30 to 50 ms)
  job polling (one poller, back-off)                   mayapy: the runner's pump loop
```

Measured facts behind this design [verified live in `mayapy` 2027.2]:
- `maya.utils.executeDeferred` never runs in `mayapy` or `maya -batch`, even with `processIdleEvents()`. `executeInMainThreadWithResult` from a worker deadlocks unless the main thread pumps idle events. Neither is used.
- A queue plus `concurrent.futures.Future`, drained on the main thread, ran every call on the main thread with no deadlock, in a prototype HTTP server taking 8 parallel requests (about 40 ms in total).
- Maya releases the GIL inside heavy commands, so workers keep downloading while Maya computes.
- `urllib` with the default SSL context fails in `mayapy` on macOS (no CA bundle found); a vendored `truststore` context uses the OS trust store and works, including behind studio proxies that inspect TLS; `certifi` (bundled with Maya) is the fallback.
- `mayapy` has a `QCoreApplication`, no `QApplication`: Qt timers and queued signals only run when `processEvents()` is pumped. So the core never depends on Qt; only the GUI drain uses a `QTimer`.

The **job ledger** is a SQLite database (Python standard library) in the per-user Maya folder (`<MAYA_APP_DIR>/scenario/ledger.sqlite3`), shared by every Maya version and by `mayapy` runs of the same user, with WAL mode and a per-job lock so two Maya sessions never deliver the same job twice. Jobs belong to the account and workspace, not to a scene file; each job remembers the scene it was started from (file path and the scene's UUID stored in `fileInfo`) so results can be offered back in that scene. States follow the Blender plug-in: `prepared`, `submitting`, `remote`, `uncertain`, `cancel_requested`, `succeeded`, `failed`, `canceled`, `downloading`, `ready`, `download_failed`, `applying`, `applied`, `apply_failed` (section 7.1).

**Budgets:** no main-thread slice above 16 ms from the plug-in during polling and downloads (measured by the dispatcher itself and reported in Diagnostics); the panel opens in under 300 ms with a cached catalog; GLB parsing and texture decoding happen on workers, only node creation runs on the main thread.

### 3.4 Backend interface

`ScenarioBackend` declares what the plug-in needs (catalog, schema, estimate, run, jobs, assets, uploads, downloads, workflows, prompt tools, usage, teams and projects). v1 implements it over the hosted Scenario MCP (`https://mcp.scenario.com/mcp?toolsets=full`, JSON-RPC 2.0, replies in JSON or SSE, `MCP-Protocol-Version` header, session id kept and renewed). Reasons: the hosted MCP accepts OAuth tokens while the REST API does not yet; it is the contract the Godot, Unity and Unreal plug-ins use and test; it brings schema normalization, `recommend` and 3D format conversion. Risk: the MCP is designed for agents and its replies can change, so parsing is defensive (structured content first, then the JSON text block), recorded fixtures cover every call (shared with the other plug-ins), and a weekly free contract check runs in CI. A REST backend can be added later behind the same interface.

The plug-in identifies itself with `User-Agent: ScenarioMaya/<version> (Maya <x.y>; <OS>)`. No personal or scene data goes in that header.

### 3.5 Where the MCP server lives

| Option | For | Against | Decision |
|---|---|---|---|
| In Maya, inside the plug-in | Direct access to the scene through the dispatcher; nothing extra to install; dies with Maya; the money contract stays in the process that holds the credentials | Stops when Maya closes | **Chosen** |
| Sidecar process | Survives Maya restarts | Needs its own channel into Maya anyway (usually `commandPort`, unauthenticated), a second thing to install and keep in step | No |
| Maya's `commandPort` | Built in | No authentication, any local process can run any command; Autodesk published an advisory about it [verified, secondary] | Never used or opened by the plug-in |
| An existing community Maya MCP server | Already has scene tools | Small, single-maintainer projects; generic `execute_python`; an agent on them could call our Python API and skip quotes | Adapters later (8.5), never the base |
| Both: our server plus a hosted one | The hosted Scenario MCP (`mcp.scenario.com`) stays the place for platform-wide work (training, usage, team admin) | Two servers in the client | **Yes**: the plug-in's server covers scene and Scenario-in-Maya; its instructions point agents to the hosted server for the rest, as the Blender plug-in does |

The server is a `ThreadingHTTPServer` from the standard library, bound to `127.0.0.1` only, default port **9878** (Blender uses 9876, Unreal 9877, Unity 8791; it avoids 7001, the port the Maya expert skills use for their `commandPort` bridge). If 9878 is taken it tries the next nine ports and the Connect buttons write the actual one. Every tool call is queued to the main thread through the dispatcher, with a time limit; long waits (`wait_for_job`) are answered from the worker side so they never hold the main thread. A prototype of this server (token check, Origin check, main-thread dispatch, 8 parallel calls) passed in `mayapy` [verified].

**Headless:** `mayapy -m scenario_maya.serve [--scene file.ma] [--port N]` starts Maya standalone, loads the plug-in, opens the scene if given, starts the server and runs the main-thread pump loop until stopped. This is how CI and agent pipelines drive Maya without a GUI. Tools that need the GUI (viewport screenshots of the active panel, dialogs) return a clear error headless; captures use `ogsRender` with an explicit camera, which works headless [verified].

### 3.6 The action layer

Every user-visible operation is one action with typed inputs, a dry description ("what would change"), and a result that reports exactly what changed (nodes created with their full DAG paths, nodes modified and how, files written, undo availability). The panel, the composer, menus, the MCP tools and the Python API all call actions. This is what lets an agent read back the result of every call, and what makes "never return OK on a no-op" enforceable: an action that changed nothing returns an error that says so.

Scene changes run as undoable commands (section 7.3): one action, one named undo chunk, one Ctrl+Z.

### 3.7 Architecture diagram

```
 Artist                          Agent (Claude Code, Codex, Cursor...)       Script / mayapy / CI
   |                                    |                                         |
 Panel, Studio, composer,        Local MCP server (127.0.0.1:9878)          scenario_maya.api
 menu, shelf, AE section         token, Origin check, approvals              headless runner
   |                                    |                                         |
   +-------------------+----------------+---------------------+-------------------+
                       |                                      |
                Action layer (maya/)                  Permissions
                generate, capture, import, apply,     (mutate switch, Python switch,
                organize                               spend rules, activity log)
                       |
        +--------------+-------------------+-------------------------+
        |                                  |                         |
   core/ (no Maya)                  Importers and apply modes     Provenance
   backend client, auth, ledger,    GLB builder, FBX, USD,        node attributes,
   quotes, schema forms, catalog,   materials, sky, media,        sidecar JSON,
   downloads, uploads, glTF parse   surface matching, undo         "In this scene" view
        |
   Hosted Scenario MCP (HTTPS)  ->  Scenario platform (models, jobs, assets, workflows)
```

---

## 4. UX

### 4.1 Information architecture

Entry points, all created by the plug-in at load and removed at unload, GUI sessions only (in batch, Maya's UI commands return `False` without raising [verified], so the plug-in checks `MGlobal.mayaState()` and skips UI):

- **Scenario menu** in Maya's main menu bar (tear-off): Panel, Studio, Quick Composer; a **From selection** submenu (Make 3D from image, Edit mesh, Remesh, UV unwrap, Retexture, Rig, Animate, Split into parts, Make material, Restyle this view); Jobs; In this scene; Import glTF or GLB... (6.7); Connect an agent; Sign in or Sign out; Preferences; Help (Handbook, Privacy, Report a problem, About).
- **Scenario shelf** with six buttons: Panel, Composer, Generate from selection, Restyle view, Jobs, Agents. The Autodesk Marketplace requires a shelf button or a menu [verified]; we ship both. How the shelf is kept out of the user's saved shelves is settled in M2 (section 13) [to verify].
- **Hotkeys**: every action is a `runTimeCommand` in the category "Scenario" (`default=True`, so it is not saved to preferences, and tied to the plug-in so it loads it on use) [verified: Autodesk docs]. The plug-in never creates or switches hotkey sets; users bind keys in the Hotkey Editor, and the docs list suggested bindings (4.8).
- **Scenario panel**: the main surface, a dockable `workspaceControl` that restores with the layout (4.2).
- **Studio**: a larger window with tabs for longer work (4.4).
- **Quick composer**: a one-line prompt strip at the bottom of the active viewport (4.5).
- **Attribute Editor**: a "Scenario" section on any node with Scenario provenance: model, prompt, cost, date, job, buttons Reload settings, Next step, Open on Scenario, Select related nodes. Implemented through Maya's Attribute Editor custom-content callback [to verify: hook behaviour on transform, mesh and shading nodes in 2025 to 2027].
- **Marking menu** (v1.1): a Scenario marking menu on a user-chosen key with the From selection actions.

Preferences live in a **Scenario Preferences** window (Maya's own Preferences dialog has no extension point for Python plug-ins [to verify]). Per-user settings are stored in `<MAYA_APP_DIR>/scenario/settings.json`; project settings (output folder, naming, import defaults, model allow-list) in `<Maya project>/scenario.json`, meant to be committed with a studio's project. No secret is stored in either, in optionVars (plain text in `userPrefs.mel` [verified]), in `fileInfo` or anywhere in the scene.

### 4.2 Scenario panel (dock)

Docked by default as a tab beside the Channel Box and Layer Editor; it restores with the workspace through a `workspaceControl` whose `uiScript` is a one-line import and whose `requiredPlugin` is the plug-in [verified: Autodesk docs; GUI restore to verify in M2].

```
+- Scenario ------------------------------------- [Studio] [=] -+
| Acme Studio / Lantern Film v      1,240 CU left    (o) Agent  |
+---------------------------------------------------------------+
| [Image] [Video] [3D] [Material] [Audio] [Env] [Render] [Block] |
| 3D:  (Text) (Image) (Multi-view) (Edit selection)              |
+---------------------------------------------------------------+
| Model  [thumb] Meshy 7.1 Image to 3D               [Change]    |
|        Image or up to 4 views to a textured mesh               |
| Image  [ lantern_concept.png ]  [+ Viewport] [+ Camera]        |
|        [+ Render view] [+ File] [+ Library]                    |
| Prompt [ a brass ship lantern, worn, hand-painted     ]        |
|        [Spark: New / Rewrite / Translate . about 2.75 CU]      |
| Settings  Texture [on]  Polycount [30,000]  Pose [-]           |
|           More settings (5)                                    |
| Lands as: new group at the camera's interest point, 1 m tall   |
| +-----------------------------------------------------------+ |
| |               Generate . 120 CU            Ctrl+Enter      | |
| +-----------------------------------------------------------+ |
+- Results -----------------------------------------------------+
| [img] Ready . 120 CU   brass ship lantern                      |
|       [Import] [Import at selection] [Next v] [...]            |
| [img] Generating 42% ............                     [...]    |
+- Jobs (2) -------------------------------- Show all jobs ------+
```

Section order is fixed in every lane: Model, inputs (images, mesh, video), Prompt, Settings, destination line, Generate, Results. One primary action per view.

**Lanes and modes** (stable lane ids, separate from labels, so a renamed label never breaks saved state):

| Lane | Modes | v1 |
|---|---|---|
| Image | Generate, Edit (references), Expand, Upscale, Remove background, Tools | v1 |
| Video | Text to video, Image to video, Edit video | v1 |
| 3D | Text, Image, Multi-view, Edit selection (Remesh, UV unwrap, Retexture, Rig, Animate, Parts, Edit by prompt), Motion (text or video to motion) | v1 |
| Materials | Text to PBR, Image to PBR maps | v1 |
| Audio | Music, Sound effects, Speech | v1 |
| Environment | Generate panorama, From image, HDRI, Upscale panorama, World (splat) | v1 (splat as file, 6.6) |
| Render | Image (restyle a viewport, camera or Arnold view), Video (restyle a playblast range) | v1 |
| Blockout | Plan a layout from a prompt, build it from primitives, then generate per block | v1.1 |

The **destination line** always says where the result will land before Generate is pressed: "new group at the camera's interest point", "on the selected mesh pCube1 (material)", "replaces the sky dome", "on the Time Slider at frame 101". It changes as the selection changes.

The **Generate button** states: `Generate . 120 CU`, `Checking price...`, `Needs a prompt`, `Needs image 1`, `Select a mesh to edit`, `Price unavailable (Retry)`, `Spending off` (`SCENARIO_NO_SPEND`), `Sign in to generate`, `Offline`, `Waiting for Scenario...` (after a submit, until the job is confirmed plus 2 s while a fresh quote loads). It is enabled only with a current quote for this exact form. A click submits; a confirm dialog appears only above a threshold the user set (off by default).

CU formatting follows the Scenario plug-ins: up to three decimals, no trailing zeros, thousands separators below 10,000, then K, M, B with three significant digits (`12.3K CU`); a non-zero price that rounds to zero shows as `< 0.001 CU`. The exact decimal string from Scenario is kept in the quote, the job and the node metadata.

### 4.3 Model picker

```
+- Choose a model -------------------------------------------------- x -+
| [ Search models...                                 ]  [x] Team models  |
| [Image] [Video] [3D] [Audio]                           [ ] Show legacy |
| (All) (Generate) (Remesh) (Retexture) (UV unwrap) (Rigging) (Animate)  |
| (Parts) (Splat) (Trained)                                              |
+-------------------------------------+---------------------------------+
| * Meshy 7.1 Image to 3D   Featured  | [ large thumbnail ]             |
|   Tripo 3.1 Image to 3D             | Meshy 7.1 Image to 3D           |
|   Rodin Gen-2.5                     | img23d . GLB + OBJ . PBR        |
|   Hunyuan 3D Pro 3.1                | Image or up to 4 views to a     |
|   Hitem3D 3.0               New     | textured mesh, A or T pose.     |
|   Lantern Props v2    Team . LoRA   | From 80 CU                      |
|   ...                               | [Use this model]                |
+-------------------------------------+---------------------------------+
```

Type tabs and category chips mirror Scenario's web app. 3D chips: Generate, Remesh, Retexture, UV unwrap, Rigging, Animate, Parts, Splat. The catalog carries no chip field, so the plug-in keeps its own model-to-task map, read from tags and capabilities, with unmatched models under Generate [verified: Scenario MCP schema]. Favorites (star) stay on top, then the lane's quick picks, then the catalog newest first. Rows for 3D models show what the model returns (formats, PBR, rig, quads) and its input limits (face cap, accepted mesh formats). Team allow and block lists are respected. Keyboard: type to search, arrows, Enter, Esc. The catalog is cached for 24 h under `<MAYA_APP_DIR>/scenario/` and refreshed in the background. Picking a model of another type switches lane.

### 4.4 Studio

A larger window (floating `workspaceControl`, dockable) with horizontal tabs: **Create, Workflows, Library, Jobs, Results, Connection**. It reuses the panel's widgets and state: a prompt typed in the panel is in the Studio's Create tab, and the reverse.

| Tab | Content |
|---|---|
| Create | The panel's form with more room: reference strip with thumbnails, settings in two columns, results grid with previews |
| Workflows | Team and public workflows, inputs form built from the workflow's declared inputs, exact price, Run (with a confirm that shows the price) |
| Library | Scenario project assets (search, collections, tags); **In this scene**: every node with Scenario provenance, grouped by asset, with Select, Show job, Reload settings |
| Jobs | The durable job list (4.6) |
| Results | Session results and cloud project history (Load older), with every result's actions |
| Connection | Account, workspace, balance, sign out; **Agents**: server state, URL, port, connected clients, permission switches, activity log, Connect a client; **Diagnostics**: versions, paths, network check, main-thread budget report, Copy diagnostics (secrets removed) |

### 4.5 Quick composer

```
+-- persp ---------------------------------------------------------------+
|                                                                        |
|                              (viewport)                                |
|                                                                        |
|  +------------------------------------------------------------------+  |
|  | [Img|3D|Mat|Env|Rnd]  Tripo 3.1 v  [settings]  [Panel]            |  |
|  | > a mossy stone well, stylized                  [Generate . 45 CU] |  |
|  | Generating 42% .......   |   Ready: stone well  [Import] [Next v]  |  |
|  +------------------------------------------------------------------+  |
+------------------------------------------------------------------------+
```

It shares state with the panel (same model, prompt, quote). Enter generates when a valid quote exists; Esc returns focus to the viewport. It never lands anything by itself. Implementation: a frameless Qt tool window that follows the active model panel's bottom edge, rather than a widget drawn inside Viewport 2.0, because child widgets over the viewport's native surface are unreliable [to verify on macOS Metal and Windows DirectX in M2; fallback: a strip docked under the viewport].

### 4.6 Jobs and results

```
+- Jobs --------------------------------------------------------------------+
| State           Model                  Prompt / input        Quoted Charged|
| Generating 42%  Meshy 7.1 Image to 3D  brass ship lantern    120    .      |
| Ready to apply  Meshy UV Unwrap        pCube1 (2,400 faces)  20     20     |
| Downloading 63% Seedance 2.5           lantern flicker, 5 s  .      .      |
| Not confirmed (!) PATINA Material      wet cobblestone       27     ?      |
|   Scenario may or may not have received this request. An identical one    |
|   stays blocked until you check.   [Find in Scenario history] [Details]   |
+---------------------------------------------------------------------------+
```

Row actions, shown only when valid (hidden, never greyed): Import, Import at selection, Apply to... (3D edits, materials, sky, media), Retry download, Re-run (fills the form, sends nothing), Reload settings, Details (inputs, asset ids, error with its support id, Copy), Open on Scenario, Cancel (only where Scenario allows it, which today excludes most generation jobs [verified]), Dismiss. Status words: Preparing, Submitting, Not confirmed, Queued, Starting, Generating N%, Finalizing, Downloading N%, Download failed, Ready to apply, Applying, Applied, Needs review, Failed, Blocked (moderation), Canceled. No time estimates.

Jobs belong to the account, not to the scene, and are listed in every Maya session of the same user. A job remembers the scene it started from; its results are offered in that scene first and can be applied elsewhere through Apply to... after a fresh review.

### 4.7 Apply review

Every change to existing scene content goes through a review that says exactly what will change, before anything is touched. The same review text is returned to agents by `prepare_result_application`.

```
+- Apply mesh edit ----------------------------------------------- x -+
| Result   Meshy UV Unwrap . GLB (primary result) . 2,412 faces        |
| Target   |props|crate_GRP|crate_GEO   (mesh crate_GEOShape)          |
| Edit     (Replace UVs)  Replace geometry  Replace textures  ...      |
|          Default edit follows this job's UV unwrap task.             |
| Checks   Same surface: yes (2,400 faces, matched after               |
|          triangulation, max offset 0.00001 of size)                  |
|          History on target: none     Instanced: no                   |
| Changes  UV set "map1" coordinates replaced. Geometry, other UV      |
|          sets, materials and history unchanged.                      |
| [x] Keep original UVs as set map1_scnPrev                            |
| One Ctrl+Z undoes this.                                              |
|                                  [Cancel]   [Apply UVs]              |
+---------------------------------------------------------------------+
```

Imports of new content use a shorter review in the result card (what lands, where, in which namespace); an explicit setting ("Import new results without review") skips it for people. Agents always prepare first.

### 4.8 Keyboard

Global actions are runtime commands without default bindings (default hotkey sets cannot be changed, and taking keys from users breaks muscle memory). Suggested bindings in the docs, checked against Maya's default set in M2:

| Action | Suggested |
|---|---|
| Open or focus the Scenario panel | Alt+Shift+S |
| Toggle quick composer | Alt+Shift+Space |
| Generate from selection (opens the panel on the right lane) | none |

Inside our widgets (scoped to the widget, so they never fire in the viewport): Ctrl/Cmd+Enter Generate, Ctrl/Cmd+M model picker, Ctrl/Cmd+K command palette (actions, models, recent jobs), Ctrl/Cmd+I import the selected result, Esc close overlays. Typing in our text fields never triggers Maya hotkeys [to verify in M2 with the default hotkey set].

### 4.9 Visual language

No global stylesheet or palette: our widgets inherit Maya's style, fonts and colours, and use Maya's icons through Qt resources (`":/polyCube.png"`) where one fits [verified: resources resolve in Maya 2027]. Scenario appears only as the black and white mark, the primary button and the price chip. Status colours are reserved for states and never the only signal. Sizes scale with Maya's UI scale (`MQtUtil.dpiScale()`) [verified: available]; tested at 100, 150 and 200 percent. Every button has a one-sentence tooltip that starts with the action and states the cost when it spends. Painting code never calls the network or `maya.cmds`.

### 4.10 Sign-in and first run

```
+- Scenario ------------------------------------------------------+
|                                                                 |
|          [S]  Every Scenario model, inside Maya.                |
|                                                                 |
|          [  Sign in with Scenario  ]   (opens your browser)     |
|                                                                 |
|          Sign in on another device  .  Use an API key           |
|          Create an account                                      |
|                                                                 |
|  Prompts and files you send go to Scenario. Nothing is sent     |
|  until you press Generate or allow an agent to. Privacy         |
+-----------------------------------------------------------------+
```

First-run path (target under 2 minutes from install):
1. Drag `install_scenario.py` from the download onto the Maya viewport. It copies the module into the user's modules folder, writes the `.mod` file, loads the plug-in for this session, sets it to load on startup and opens the panel. No restart, no `userSetup.py` edit, no admin rights. (About 10 s.)
2. **Sign in with Scenario**: the browser opens, the user approves (usually already signed in on scenario.com), the page says "Signed in. You can return to Maya." (About 20 s.)
3. Workspace: with one team and one project it is chosen automatically; otherwise a two-step picker (team, project), remembered per Maya project.
4. The panel opens on the Image lane with a fast, low-cost model, a starter prompt ("a carved wooden treasure chest, game prop, studio light") and its price already on the button. Generate. (About 15 s.)
5. The result card offers Import as card, Apply to selection (material) and Image plane. One click lands it; one Ctrl+Z removes it.
6. A next-step chip offers "Make it 3D" with its price on the chip (an image to 3D model at about 45 CU [verified: dry run]); a one-time card offers "Connect your agent" (skippable).

### 4.11 Empty, loading and error states

| Situation | What the user sees |
|---|---|
| No results yet | "Nothing generated yet. Type what you need and press Generate." and three example prompts for the lane |
| Catalog loading | Placeholder rows in the picker; Generate shows "Loading models..." |
| Price check failed | "Price unavailable" with Retry; Generate disabled |
| A price check returned a job | "Automatic prices are off until Maya restarts: a price check started a job." with the job id; the job is tracked |
| 401 | One silent token refresh first; then "Your Scenario session ended. Sign in again." [Sign in] |
| 403 | "This account cannot use <model> in <project>." with Scenario's reason and a link to team settings |
| 429 | Reads: "Scenario is busy, retrying in N s". Paid calls: "Not sent: Scenario asked us to slow down. Try again." (never retried by itself) |
| Not enough CU | "This needs 120 CU. The project has 40 left." [Open billing] |
| Moderation | "Blocked by Scenario's content rules." with the reason; never retried |
| Offline | Banner "Offline. Jobs continue on Scenario and resume here when you are back." |
| Download stopped | "Download stopped at 63%." [Resume] (fresh signed link, resumes from the received bytes) |
| Not confirmed | "Scenario may or may not have received this request." [Find in Scenario history] [Details]; identical request blocked |
| Import or apply failed | "Nothing was imported: <reason>." or "Nothing was applied: <reason>." The files stay in the cache. [Retry] [Show file] |
| Precondition failed | The exact reason and the fix: "pCube1 has construction history (polySmooth1). Delete history or choose Keep original and apply to a copy." |
| Maya busy | Agents get "Maya is busy (a modal dialog or long operation); try again", the panel shows nothing |

Messages never contain secrets, tokens or full signed URLs. Logs go to Maya's Script Editor at warning level and to `<MAYA_APP_DIR>/scenario/logs/` with ids, never credentials.

---

## 5. Sign-in and credentials

### 5.1 Options compared

| Method | Steps for the user | Works on | Verdict |
|---|---|---|---|
| **Browser sign-in, authorization code + PKCE, loopback redirect** | Click, approve in the browser, done | Any desktop where the browser can reach `127.0.0.1` | **Default** |
| Device code | Click, a short code shows, enter it on scenario.com from any device | Remote workstations, render nodes with a display, locked-down browsers | **Fallback**, offered when the loopback callback fails, and as "Sign in on another device" |
| API key + secret | Create a key on the team page, paste two values (or a `key:secret` pair) | Everywhere, including CI and farms | **Alternative** for CI, shared machines and teams that prefer keys |
| Environment variables | Set `SCENARIO_API_KEY` and `SCENARIO_API_SECRET` | `mayapy`, CI, render farms, Docker | Always read first when set |

Facts **[verified 2026-10-18]**: the hosted Scenario MCP publishes OAuth metadata with grant types `authorization_code`, `refresh_token` and `urn:ietf:params:oauth:grant-type:device_code`, PKCE `S256`, dynamic client registration and public clients. OAuth callers pass `team_id` and `project_id` on each call; an API key is already scoped to its project. The REST API does not accept these tokens yet. **[to verify]**: a full browser round trip from a desktop app and device-code registration, shared with the Unreal and Unity plug-ins.

### 5.2 Flow details

- Discovery from `https://mcp.scenario.com/.well-known/oauth-authorization-server`; client registration once per install, cached with its redirect URI; loopback redirect on `http://127.0.0.1:<random port>/callback` served by a one-shot listener on a worker thread; `state` and PKCE verified; `resource=https://mcp.scenario.com/mcp`.
- Refresh: one silent refresh on a 401, then one resend. Safe for paid calls because a 401 means the request was refused before dispatch.
- Workspace: `teams_list` then `projects_list`; the choice is stored per user and per Maya project (ids only, no secret). Switching workspace clears quotes and private catalog entries, and never touches jobs already submitted.
- Sign out revokes the refresh token, deletes it from the credential store and clears cached private data.
- When Scenario's shared authorization server serves first-party clients, the plug-in moves to a registered client id with a branded consent page.

### 5.3 Where secrets live

| Secret | macOS | Windows | Linux | Never |
|---|---|---|---|---|
| OAuth refresh token, API secret, agent server token | Login keychain, generic password, service "Scenario for Maya" | Credential Manager, generic credential, target "Scenario for Maya/<account>" | Secret Service through `secret-tool` (secret passed on stdin) | The scene (`.ma`, `.mb`, `fileInfo`, node attributes), optionVars and `userPrefs.mel`, `Maya.env`, `workspace.mel`, `scenario.json`, logs, crash reports, the Script Editor history |
| OAuth access token | Memory only | Memory only | Memory only | Disk |
| API key id (not secret), team and project ids | `settings.json` | `settings.json` | `settings.json` | |

Implementation: a small `credstore` module with no compiled dependency. macOS through ctypes on Security.framework (prototype stored, read, updated and deleted a test item from `mayapy` 2027.2 [verified]); Windows through ctypes on `CredWriteW` and `CredReadW` (blob limit 2,560 bytes, enough for a refresh token or an API secret, not for long access tokens, which stay in memory) [verified: Microsoft docs; not run, no Windows machine]; Linux through `secret-tool` with the secret on stdin, never on the command line [verified: man page]; if none is available, a file readable only by the user under `<MAYA_APP_DIR>/scenario/`, and the Connection tab says so. The `keyring` package was considered and dropped: it needs a compiled `cryptography` on Linux [verified].

Known risk [to verify in M1]: on macOS a keychain item is trusted by default for the program that created it. Maya and `mayapy` are different programs, and a Maya update replaces them, so reading an item may show a macOS "wants to use your confidential information" prompt. If the GUI test shows the prompt, items are written through `/usr/bin/security -i` reading commands on stdin, which keeps one trusted program across Maya binaries and versions.

Read order: environment variables, then the credential store, then the fallback file. Environment variables:

| Variable | Use |
|---|---|
| `SCENARIO_API_KEY`, `SCENARIO_API_SECRET` | Credentials for CI, farms and `mayapy` |
| `SCENARIO_TEAM_ID`, `SCENARIO_PROJECT_ID` | Workspace for OAuth tokens supplied by a CI secret manager |
| `SCENARIO_NO_SPEND=1` | Refuses every paid call and upload locally (price checks still work) |
| `SCENARIO_MAYA_MCP_PORT`, `SCENARIO_MAYA_MCP_TOKEN` | Agent server port and token for headless runs |
| `SCENARIO_MAYA_OFFLINE=1` | No network at all (catalog from cache, jobs paused) |

When credentials come from `Maya.env`, the Connection tab warns that `Maya.env` is plain text.

---

## 6. Capability matrix

Legend: **v1** in the first release, **v1.1** next release, **Later** after v1.1. Model names and prices are examples from free dry runs on 2026-10-18 [verified]; the catalog changes often, so defaults are re-checked before each release (best and most recent model per task, by Scenario's `recommend` and the newest catalog entries), and the price shown is always the live quote.

### 6.1 Scope

Scenario's public catalog has 92 3D models, about 66 of them current, reached through the same model call as every other lane [verified]. A Maya plug-in feeds them four kinds of input: a prompt, 1 to 8 images, a mesh (for remesh, UV, retexture, rig, animate, parts and prompt edits) and a video (motion capture). Mesh inputs are uploaded assets, so every Maya mesh is exported and uploaded first. Outputs are GLB first, often with an OBJ beside it; some models return FBX (quad meshes, motion), one returns Maya `.ma` or `.mb` on request, splat models return SPZ or PLY [verified]. Scenario converts 3D downloads to GLB, FBX or OBJ only [verified].

One real run per 3D operation, made the same day by the Scenario Unity plug-in's acceptance tests, adds facts the importer relies on [verified: those runs]:
- Stored files do not always match their declared type: a builder edit is stored as a Blender file, a splat declared SPZ is a PLY, motion comes as FBX. Downloading with `format=glb` converts them, keeping skins and clips, at no cost. Forcing that conversion on a file that already is a GLB timed out on a 91 MB result, so real GLBs are downloaded as they are. The plug-in reads each file's real format from its header, never from the declared type.
- Some results carry vertex colours and no material (a remesh model, a multicolour model, a parts model); the builder creates a colour set and a material that shows it.
- Rigger outputs differ: Meshy Rigging returns five GLBs (the rigged mesh plus walk and run clips, some on a bare skeleton, linked to the mesh by their parent id); bone counts range from 24 to 52 (two riggers use Mixamo-style names); one rigger writes centimetres where glTF expects metres, which the fit in 6.4 detects.
- Meshy 7.1 returns about 947,000 triangles by default; asking for a 30,000 target polycount costs the same, so the plug-in proposes a polycount for real-time projects.

### 6.2 Generate 3D

| Operation | Input from Maya | Default model (alternatives) | Price example | Result | Landing | Release |
|---|---|---|---|---|---|---|
| Text to 3D | Prompt | Meshy 7.1 (Rodin Gen-2.5, Tripo P2, Meshy T2.5 Smart Topology) | 120 CU; 20 CU untextured on T2.5 | GLB + OBJ + textures | New group, openPBR materials, real-world size | v1 |
| Image to 3D | 1 to 4 images: a file, a viewport capture, a result from the Image tab (camera capture and a rendered view later) | Meshy 7.1 Image to 3D, preset to a 30,000-face game mesh (Tripo P2, Rodin Gen-2.5, Tripo 3.1, Hunyuan 3D Pro 3.1) | 120 CU; Tripo P2 220 CU; Tripo 3.1 45 CU | GLB | Same | v1 |
| Multi-view to 3D | Front, left, back, right: four captures from a camera rig the plug-in places around the selection, or four files | Tripo 3.1 Multiview (Meshy 7.1 multi-image, Hunyuan 3.1 Multiview) | 45 CU | GLB | Same | v1 |
| Sketch to 3D | A sketch image (a Blue Pencil drawing captured from the viewport, or a file) and a prompt | Hunyuan 3D Pro Sketch | 105 CU | GLB | Same | v1 |
| Build from references | 1 to 8 images, prompt; returns a rigged, UV'd model with LODs on request | Claude Opus 5.5 3D (GPT-6 Astra 3D) | 400 to 700 CU by build effort | Scene file converted to GLB or FBX on download; Mixamo-named joints, ARKit face shapes | Same, with skin, joints and blend shapes | v1 |
| Quad mesh | Any of the above with the model's quad option | Tripo P2 or 3.1 with `quad` (Rodin quad mesh options) | Tripo P2 quad 210 CU | FBX (quads survive only in FBX) | FBX path (6.7) | v1 |
| Voxels | Prompt, up to 4 references | Voxel Crafter | 36 CU | VOX | No Maya reader; converted to a mesh of cubes | Later |
| Parts at generation | Image with the model's parts option | Tripo 3.1 `generateParts` | +cost | GLB with several meshes | Group with one child per part | v1 |

The panel shows, before Generate, what a model returns (formats, PBR, rig, quads, typical face count) from the catalog and the asset records, so the user knows what will land.

A 3D job returns several assets: the GLB, an OBJ and MTL of the same model, and texture images. The plug-in reads each asset record and downloads only the lane's preferred format (GLB first), choosing by the record's `metadata.format` (else its MIME type), never by position; with no match it keeps every file so the import can say what arrived. The record's face count and dimensions show on the result card before import, and its thumbnail becomes the card's picture [verified 2026-10-19]. Scenario renders that thumbnail a few seconds after the job ends: Tripo P2 and Meshy 7.1 with remeshing had none when the GLB was downloaded, and the Meshy record carried one 9 s after the asset was written [verified 2026-10-19]. The plug-in reads the asset again up to four times, 5 s apart, after the download, and the card shows "3D" until a picture arrives.

**Image to 3D** is the Image mode of the 3D tab (4.2). Its image row fills the model's first image field and offers as many images as that field takes: four for Meshy 7.1 (Scenario gives a file list's limit as `max_length`), one for Tripo P2. A file or a viewport capture is uploaded when the person adds it, the explicit action of 7.1 point 8; an Image tab result is already an asset and is used as it is. The prompt box follows the model: Meshy 7.1's optional `texturePrompt` only guides the texture, and Tripo P2 takes no prompt, so the box is hidden. A job with no prompt is named after its images.

Default model, chosen on 2026-10-19 [verified: one concept image, one run each]: Scenario's `recommend` ranked Tripo P2 first for quality and Meshy 7.1 Image to 3D second. On the same concept of a carved chest, Meshy 7.1 with the 30,000-face preset returned 28,984 faces in about 140 s for 120 CU and kept the carving on every side; Tripo P2 returned 4,222 faces in about 85 s for 220 CU, with no non-manifold edges (Meshy: 53) and flatter carving, and its first run failed on Scenario's side ("the connection to the generation service timed out"); the retry succeeded. Meshy 7.1 is the default for its detail at a game budget, its price and its four views; Tripo P2 is the second quick pick. Both GLBs import through the plug-in's builder with three textures and one material.

### 6.3 Sending a Maya mesh (edit inputs)

Every mesh task starts with **Capture selected meshes**: the plug-in exports the selection, checks it against the chosen model's limits, uploads it and keeps a local record of exactly what was sent (node paths, a geometry and attribute fingerprint, transforms, the export's hash), so the result can be mapped back.

- **Format per model**: GLB by default (our writer, the inverse of the reader: meshes, UVs, normals, base colour, metal and roughness textures, skin and joints when needed); FBX through Maya's FBX exporter with embedded textures where a model requires FBX (Hunyuan Texture Edit accepts FBX only; a GLB input fails after submission and the failed job record keeps its price [verified]) or where quads must survive. Maya has no GLB exporter [verified], and OBJ export drops textures and is unitless [verified], so OBJ is used only where a model requires it. The plug-in keeps a table of accepted formats and face caps per model (for example Meshy UV Unwrap up to 44,000 faces, Hunyuan UV Unwrapping 30,000, Tripo Smart UV 80,000 triangles [verified]) and refuses before upload, because price checks do not validate formats or caps [verified].
- **Space and units**: geometry is exported in the object's local space, in metres, with the object's world matrix recorded, so placement back can be by world, local or fitted coordinates (6.4).
- **What is included**: only the selected meshes and what the task needs. Static tasks export the mesh with its current material assignments; rig and animate tasks export the skin and skeleton; history and deformers are evaluated (the exported mesh is what the user sees) and the review says so.
- **Names**: neutral names by default (7.5).
- **Several meshes**: up to 64 in one export, for tasks that accept several objects (UV, retexture, rig).
- **Reuse**: a captured mesh's asset id is kept for the session, so a second task on the same unchanged mesh does not upload again.

[verified: export formats and their texture behaviour in `mayapy` 2027.2; to verify: which input formats each edit model accepts beyond GLB, tested with the cheapest model of each family in M3]

### 6.4 Apply modes: results on the user's own meshes

A 3D result can land as a new object (the default, always available) or be applied to an existing mesh, rig or head in the scene. Each apply mode below was prototyped headless in `mayapy` 2027.2 on purpose-built fixtures, with full scene snapshots compared before the apply, after undo and after redo [verified, unless tagged]. Real Scenario outputs have not been run through them yet (M3).

**Rules for every apply** (shared with the Blender plug-in's contract):
- Download and apply are separate. Only images land by themselves on request; every 3D result waits at **Ready to apply**.
- Two steps: **prepare** captures the target (node, shape, a geometry and attribute fingerprint, transform, history, deformers) and returns the review; **apply** consumes the single-use handle once. The handle dies on any scene change, frame change, undo, redo, file open or credential switch in between.
- Targets are never found again by name or by the current selection: the captured node identity (Maya UUID plus DAG path) is used, and a changed fingerprint makes the target stale.
- Order at apply: rehash the result files against their receipts, run the preflight (below), recheck the target, claim the job (`ready` to `applying`), open one named undo chunk, stage the result, validate it, make the mode's edits, clean the staged nodes, close the chunk, read back what changed, and record `applied`. A failure before the edits closes the chunk and undoes it once, and the row reads **Nothing was applied: <reason>** [to verify: the abort path inside a chunk].
- A result can be applied again to another target ("another application, never another generation") after a new review.

**The modes**

| Mode (`mesh_policy`) | What changes | What is kept (Keep original) | Maya method that passed | Exact or approximate | Refused when | Confirmed when |
|---|---|---|---|---|---|---|
| **Replace geometry** (`REMESH`) | The target's shape node is replaced by the result's mesh | The transform (path, UUID, custom attributes, parent, sets, downstream connections); the old shape stays as a hidden intermediate shape `<shape>_scnPrev` | The returned shape is parented under the user's transform, renamed, the old shape set intermediate, downstream `worldMesh`/`outMesh` connections moved to the new shape; one undo step | Exact undo and redo. Rewiring `inMesh` (redo fails) and swapping transforms (redo misplaces) were rejected | The target is deformed (skin or blend shape: undo fails and weights or deltas land on wrong vertices; offer import as new, then Attach rig), referenced or locked (rename refused by Maya) | The shape is instanced (every instance changes); per-face materials will become one material (104 of 128 faces lost theirs in the test); an option keeps the shape node itself and needs construction history deleted |
| **Replace UVs** (`UV`) | Coordinates of one UV set | Geometry, other UV sets, materials, history; the old set copied to `<set>_scnPrev` first | A small undoable command writes the UVs (no history added); on a skinned mesh it writes to the bind-pose shape and flows through the skin | Exact when the topology check allows it (UV error 0.0); approximate transfer by closest point otherwise (planar UVs: max error 0.011; UVs with seams: max 0.98) | The target is locked; the topology differs and the approximate error at seams is above a threshold | Which set to replace when there are several; approximate transfer, with its error figures; referenced target (stored as a reference edit) |
| **Replace textures** (`RETEXTURE`) | A new openPBR material from the result's maps is assigned to the target; when the result's UVs differ from the target's and the topology matches, its UVs are applied first (as Replace UVs) | Geometry; the old material, kept unassigned; the old UV set as backup | New shading network (6.8), assigned to the target only | Exact | The target has no UVs and the result's UVs cannot be mapped; the topology differs (textures-only on mismatched UVs gave a UV delta of 0.954) | Re-pointing a material shared with other objects (they are listed); per-face materials become one. Maya's default material is never edited |
| **Attach rig** (`RIG`) | The target gets the result's joints and a skinCluster with the result's weights | Geometry, UVs, materials; an existing skin is replaced only after a confirm | Restore the returned bind pose, bind, copy weights by vertex id with a small undoable command (0.023 s on 8,435 vertices, against 6.7 s per vertex with `skinPercent`), copy each influence's bind matrix | Same topology: exact (deformation error 0 at every frame; binding at a posed frame without the bind matrix copy gave 34.1 cm). Different topology: approximate, closest-point weight copy (posed surface gap median 0.09 cm, max 0.77 cm on the test) | The target is instanced [inferred] | Approximate transfer, with figures; a rescale (a file that lost its units arrived 100 times too small with no warning, detected by a similarity fit with 0.0007 cm residual); replacing an existing skin [to verify: rebinding over a skin was not tested]; an option prunes to N influences per vertex (4 for engines) |
| **Apply animation** (`ANIMATE`) | The result's clip lands on the target's existing skeleton | Mesh, skin, rig, the target's existing keys (the clip goes on a new override layer or a Time Editor clip) | The result is staged, keys are copied per attribute with a joint name map (exact names, then a saved map, then HumanIK for bipeds), with the user's start frame | Exact for the same skeleton and rest pose; HumanIK retarget when rest poses differ (0.3 s headless, 0 degrees error, against 45 degrees for a direct copy); 6.5 | The skeleton cannot be mapped; the target has no skin | Target joints already keyed (layer or replace); joints driven by constraints; character sets or existing animation layers; HumanIK retarget (shows the mapping) |
| **Add face shapes** (`BLENDSHAPES`) | A new blendShape `scn_arkit` with the result's shapes (for example the 52 ARKit shapes from a builder model) | Mesh, skin; the new node sits before the skin in the deformer chain so expressions turn with the head | Deltas copied by vertex id into a new blendShape placed at the front of the chain (without that, a 90 degree head turn left a 90 degree error) | Exact (delta error 7e-6), identical topology only | The topology is not identical (no approximate path) | A blendShape with the same target names exists |
| **Replace with parts** (`PARTS`) | A new group of part meshes aligned on the target; the target is hidden, never deleted | The target untouched | Group, pivot at the parts' bottom centre, aligned to the target's bounds (or to its world matrix when parts come in its object space) | Exact undo and redo; alignment error 0 | | Nothing; the group name Maya returns is always used (it renames on a clash) |
| **Import as new** (`import`) | Nothing existing | Everything | The GLB builder or the staged FBX import (6.7) | Exact undo and redo | | |

`BLENDSHAPES` is new in Maya; the other policy names are the Blender plug-in's. Several captured meshes in one job (up to 64) accept `UV`, `RETEXTURE` and `RIG` only, all or none.

**Defaults** follow the job's task, as in the Blender plug-in: Remesh starts on Replace geometry, UV unwrap on Replace UVs, Retexture on Replace textures, Rigging on Attach rig, Animate on Apply animation for a skinned target and Attach rig otherwise, Parts on Replace with parts. A skinned target on a static task starts on Attach rig. A default that does not come from the job's task is shown as such ("Default edit is not from this job's task; check it."). **Keep original** is on by default.

**Topology matching.** Which modes are exact depends on proving that the result is the same surface as the target. The prototype's check compares counts, face sizes, face vertex sets, edges, ordered face connections, face corners and positions (raw and normalised to the bounds), and returns one of `identical`, `same_topology_moved`, `vertex_order_differs`, `same_mesh_reindexed`, `different`, with two flags: per-vertex data can be copied by id (weights, blend shape deltas), and per-face-vertex data can be copied (UVs). Only the ordered face connections catch every reordering; counts and edges miss renumbered vertices and rotated face starts. FBX, OBJ and USD round trips kept the order; Maya's `meshRemap` restores a vertex order headless; `polyTransfer` does not guard against reordering (UV error 0.954 on a face-reordered mesh) and also drops other UV sets, so it is never used.

The prototype does not yet accept what GLB results usually look like: triangulated, with vertices split at UV seams. The plug-in's matcher adds the Blender plug-in's rules [to build in M3]: weld coincident vertices within 1e-5 of the target's size, then prove that each result triangle lies inside exactly one target face with the same winding and that the triangles tile it exactly; split corners of one target corner must carry the same UV within 1e-5. Failures name a count ("the result splits UV coordinates at 53 target face corners"). Work is capped at 2,000,000 combined components.

**Placement** (`mesh_placement`): **Object coordinates** (`LOCAL`, the default, since meshes are exported in their local space and metres converted back to scene units), **Scene coordinates** (`WORLD`), **Fit and verify** (`FIT`: one uniform scale plus offset from bounds, never a rotation, verified by sampled surface distance both ways with at most 5% of samples beyond 2% of the target's diagonal and none beyond 10%, as in the Blender plug-in). The fit found the "100 times too small" file above. Mirrored or zero-scale targets allow object coordinates only.

**Preflight.** Before any review, the target is checked and each finding is refused, confirmed or shown, per mode [verified: detection of every code on fixtures; the policy is this spec's]:

| Finding | Geometry | UVs | Textures | Rig | Animation | Face shapes | Parts |
|---|---|---|---|---|---|---|---|
| Referenced node | refuse | confirm | confirm | confirm | confirm | confirm | inform |
| Locked node | refuse | refuse | inform | confirm | confirm | confirm | inform |
| Deformed (skin, blend shape) | refuse | write to bind-pose shape | | confirm (replace skin) | | inform (order) | |
| Instanced | confirm | confirm | confirm | refuse | | refuse | |
| Construction history | confirm (only for the keep-shape option) | inform | | | | | |
| Per-face materials | confirm | | confirm | | | | |
| Shared or default material | | | confirm re-point; never edit the default | | | | |
| Several UV sets | inform | confirm which | inform | | | | |
| No UVs | | inform | refuse (textures only) | | | | |
| Non-manifold, lamina faces | inform | confirm | | inform | | | |
| Negative scale | confirm | | | confirm | | | confirm |
| Scene units, up axis | inform | | | confirm (rescale) | confirm | | confirm |
| Namespace | inform | | | inform | confirm (name map) | | |
| Keys, layers, character sets, constraints on joints | | | | | confirm | | |
| Rest orientation in `rotate` instead of `jointOrient` | | | | inform | confirm (HumanIK) | | |

**Undo transaction** [verified across two full undo and redo cycles per mode, with the result's import inside the chunk]:
1. Outside any chunk: load the importer plug-ins (`loadPlugin` is never undone) and set importer options, including `FBXImportMode add` (the default `merge` imports nothing when a node of the same name exists).
2. One named chunk per apply, closed in `finally`: create a temporary namespace; stage the result with the plug-in's undoable import command, which records every node it creates; validate on the staged nodes; make the mode's edits with `maya.cmds` or with the plug-in's small undoable commands for API edits (API edits made from a script never enter the undo queue, and history overwrites them, so they are always wrapped); delete the staged leftovers; remove the namespace.
3. The import command's undo deletes the DAG nodes it created, then every remaining DG node (materials, shading groups, bind poses) with a separate modifier; its redo restores the same nodes, never re-imports. The full delete list is decided before anything is queued (once a parent is queued for deletion, its children's paths read as empty).
4. The GLB builder runs as the same kind of command: node creation recorded, undo deletes, redo restores.
5. Queries the plug-in makes during an apply (time, selection) run without entering the undo queue.

**Read-back** after every apply: the result reports nodes created and modified, the topology verdict, fit residual, weights copied and influences per vertex, keyed joints counted after an animation apply (a "Success" from the FBX merge path applied 0 keys on a namespaced skeleton, so a return code is never trusted), and undo availability.

**Follow-ups in Maya** (6.7): retopology (`polyRetopo`, about 1 s for 9,400 triangles to 1,900 quads) and automatic UVs (planar seed then the Unfold3D seam, unfold and layout chain, about 1 s; non-manifold input is refused first) run headless with exact undo. Quad Draw is a viewport tool and cannot be driven by the plug-in.

### 6.5 Motion

| Operation | Input from Maya | Model examples | Price example | Result | Landing | Release |
|---|---|---|---|---|---|---|
| Preset animation | The selected character mesh (rigged or not) and an action | Meshy Animation | 32 CU | FBX with skeleton and clip (auto-rigged) | Import as new character, or Apply animation onto the user's rig | v1 |
| Text to motion | Prompt and a character (the selected skinned mesh, captured; or an image) | Meshy Text to Motion, Uthana Text to Motion 3.0, Cartwheel Text to Motion | 40 CU for 2 s; about 24 CU per second on Cartwheel | FBX, GLB; Cartwheel also Maya-targeted FBX, `.ma` or `.mb` | Same | v1 |
| Video to motion | A video file or a playblast, up to 30 s and 30 MB | Cartwheel Video to Motion, Uthana Video to Motion 2.1 | 120 to 130 CU | Same | Same | v1 |
| Rig only | Selected mesh at rest pose | Meshy Rigging (bipeds), Tripo Rigging 2.5 (quadrupeds and other non-bipeds), Uthana, Cartwheel | 20 to 70 CU | Rigged GLB or FBX | Attach rig (6.4), or import as new | v1 |

- Cartwheel refuses to price without a character [verified]. With a 3D character the motion was priced at 120 CU, with a character image at 1,560 CU [verified: Unity plug-in acceptance runs], so the plug-in captures the selected skinned mesh and sends it as the character, and says so.
- For Cartwheel the plug-in asks for the Maya-targeted FBX, never `.ma` or `.mb`: importing a scene file goes through `cmds.file`, which would erase the user's undo history [verified].
- Rest orientation: FBX rigs arrive with rest orientation in `jointOrient` and zero `rotate` [verified]; rigs whose rest sits in `rotate` break a direct key copy (71.9 cm error in the test). The GLB builder therefore writes rest orientation into `jointOrient` and converts keys accordingly, so GLB and FBX rigs land the same way [verified: Maya's joint matrix is rotate x jointOrient; keys converted as key x rest inverse land on the glTF pose to the centimetre, and a Khronos character matches the reader prototype at every checked frame].
- Retargeting: exact joint names first, then a name map saved per rig, then HumanIK for bipeds (characterize both skeletons, lock, set input, bake, delete the HumanIK nodes; keys survive) [verified headless; HumanIK has no official scripting reference, so this path is covered by tests on every supported version]. Automatic HumanIK mapping covers the joint naming of the riggers Scenario offers and Maya's own Quick Rig in v1; a mapping UI for other skeletons is v1.1.
- Clips that come as separate files of the same job (walk and run beside a rigged mesh) are offered as clips of that rig, not as new characters.
- Landing: an override animation layer (default; an additive layer doubled absolute motion in the test) or a Time Editor clip at the current frame (option; its undo leaves Maya's single `timeEditor` node, which is harmless and stated). Never on the target's base curves without a confirm.
- Frame rate: clips keep their timing in seconds and are resampled to the scene's rate; a mismatch is reported.

### 6.6 Splats and worlds

| Operation | Input | Model examples | Price example | Result | Landing | Release |
|---|---|---|---|---|---|---|
| World from text, image, panorama or video | Prompt, image, 2:1 panorama, video | Marble 1.0 Draft and 1.1, HY World, TripoSplat | 25 to 1,600 CU | SPZ, PLY | PLY: an Arnold `aiGaussianSplat` node (renders in Arnold [verified]; viewport display not verified); SPZ: saved and revealed, with "Open in Scenario" | v1 file and PLY node; SPZ to PLY conversion Later |

Maya has no splat format of its own and Viewport 2.0 does not draw splats; Arnold 7.5 renders PLY splats [verified]. A splat is never "applied" to scene content.

### 6.7 Import hygiene and interop

**Carriers, in order**: GLB through our builder (no conversion loss, undoable node creation, full control of units, names and materials); FBX through `FBXImport` inside the wrapping undo command, for FBX-only results and as a fallback; OBJ the same way (OBJ is unitless: scaled from metres explicitly); USD through `mayaUSDImport` if Scenario ever delivers it. The glTF reader prototype rebuilt meshes, UVs, normals, materials with correct colour spaces, skins, skeletal animation and morph targets for four Khronos samples, and matched Maya USD's own import of the same character to the centimetre [verified]. Not handled yet: Draco and meshopt compression, KTX2 textures, texture transforms, second joint sets, emissive strength [to verify against Scenario's real outputs in M3]. Maya's install contains glTF libraries for internal use, but no glTF translator is registered for scripts [verified: translator list; how those libraries are reached is unknown], so the plug-in does not rely on them.

**Traps found in tests, each handled by the importer** [verified in `mayapy` 2027.2]:

| Trap | Handling |
|---|---|
| `FBXImportUpAxis z` switches the whole scene to Z-up | Up axis set from the scene before each import, restored after |
| `FBXImportConvertUnitString m` shrinks a 1 m cube to 1 cm | Unit option set from the scene's unit |
| `cmds.file` FBX import brings no animation and erases the user's undo history; `FBXImport` does neither | `FBXImport` only, inside the plug-in's undoable import command (6.4) |
| The FBX importer's default merge mode imports nothing when a node of the same name exists | `FBXImportMode add` before every import |
| `mayaUSDImport` undoes once; after an undo and a redo, later undos leave its nodes | Staged through the same undoable import command |
| `mayaUSDImport -parent` disables unit and axis conversion | No `-parent`; group after import |
| `preferredMaterial` marks data textures sRGB | Colour spaces set by role after import |
| Importers change the playback range | Range, current frame and rate captured and restored |
| FBX and OBJ create several top-level nodes | New assemblies found by diff, grouped under one transform |
| Leading digits dropped, non-ASCII becomes `?`, `-` becomes `FBXASC045` | Names slugified first; FBX names cleaned after import |
| FBX embedded media extract beside the FBX, with no extension sometimes | FBX copied into the asset folder first; textures renamed by format |
| Arnold writes `.tx` files beside textures | Texture folders are inside the project and writable |
| WebP cannot be read by the file node | Converted to PNG |

**Import checks on every 3D result** (shown in the result card, returned to agents): face and vertex counts, bounds in metres and scene units, UV sets present, non-manifold edges, zero-area faces, missing textures, materials created, joints and influences, clips and their frame ranges, blend shape targets. A check that fails does not block the import; it is shown.

**Follow-ups inside Maya** ("Next step" chips on a landed mesh): Maya's own retopology (`polyRetopo`) and UV tools (automatic projection, Unfold3D unfold and layout) run headless on generated meshes [verified; Unfold3D refuses non-manifold UVs], MASH scatter of a prop on a selected surface (Later). They are Maya operations, free, each in its own undo step.

**Import any GLB**: because Maya has no glTF importer, the builder is also offered as **Scenario > Import GLB...** for any local file. It needs no sign-in. JSON `.gltf` files with external buffers are not read in v1.

**Welding**: glTF splits vertices along UV and normal seams; the builder welds them back by position so the mesh is one piece, keeping UVs and normals per face-vertex. Where separate shells touch, welding can create non-manifold edges (7 on the DamagedHelmet sample); the import checks report them [verified on four Khronos samples].

### 6.8 Materials

| Operation | Input | Model examples | Result | Landing | Release |
|---|---|---|---|---|---|
| Text or image to PBR set | Prompt or image | PATINA family | Base colour, normal, roughness or smoothness, metallic, height, AO maps | New material on the selected meshes or faces (Keep the old assignment to restore with undo), or a new material only | v1 |
| Image to PBR maps | Image (a texture, a capture) | Image to maps models | Same | Same | v1 |
| Tiling and scale | Repeat UV on the material's placement node | none | | Settings in the result card | v1 |

**Recipe** [verified on openPBRSurface in `mayapy` 2027.2; Arnold render and Viewport 2.0 checked]:
- Shader: openPBRSurface (Maya 2027's default surface; exports to USD and MaterialX); standardSurface where openPBRSurface is missing; aiStandardSurface on request.
- Colour spaces from Maya's default OCIO config: base colour `sRGB Encoded Rec.709 (sRGB)`; roughness, metallic, height, normal `Raw`; HDR images `scene-linear Rec.709-sRGB`. `ignoreColorSpaceFileRules` is set on every file node so Maya's rules do not override them.
- Roughness and metallic through `outAlpha` with `alphaIsLuminance`; a smoothness map through a `reverse` node; normal maps through `bump2d` in tangent-space mode, with the green channel flipped for DirectX-convention maps; height through a `displacementShader` on the shading group (off by default for real-time projects); AO kept, not connected.
- Texture roles come from Scenario's stored role on each asset, never from file names. Scenario does not promise channel layout or normal convention per role [verified], so the plug-in checks the normal map's convention by its blue channel and green bias before wiring, and says what it assumed.
- UDIM sets: `uvTilingMode` 3 with `<UDIM>` in the path [verified].

### 6.9 Images

| Scenario category | Maya result | Placement | Release |
|---|---|---|---|
| Generate, Edit (references), Expand, Upscale, Remove background, Tools | File texture (PNG; EXR for HDR; WebP converted) | A textured card (`polyPlane` at the image's aspect, facing the camera, at the centre of interest); or base colour of a new material on the selection; or an image plane on the active camera for concept reference | v1 |
| Same, as a decal | Projected texture or Arnold decal | On the surface under the viewport centre | Later |
| Vectorize (SVG) | Maya imports SVG as curves and extruded geometry | SVG import node | Later |
| Trained models (LoRA, compositions) | Picker chip "Trained"; strength per LoRA | As above | v1 single LoRA, v1.1 stacks |

### 6.10 Video

| Scenario category | Maya result | Placement | Release |
|---|---|---|---|
| Text, image or video to video, Lipsync, Upscale | Movie file | Image plane on a chosen camera (`type` movie, frame offset at the current frame); a free-floating textured card; an image sequence when frame accuracy matters | v1 |

MP4 (H.264) on an image plane showed a black first frame and ran one frame late on macOS in tests; MOV and WebM were frame-exact [verified]. The plug-in rewraps MP4 to MOV without re-encoding when `ffmpeg` is found, and otherwise lands the MP4 with a note. Windows and Linux codecs are not verified.

### 6.11 Audio

| Scenario category | Maya result | Placement | Release |
|---|---|---|---|
| Music, Sound effects, Speech | Audio node | On the Time Slider at the current frame (`sound` node); a Time Editor audio clip when the scene uses the Time Editor | v1 |

Maya's `sound` node reads WAV and AIFF; an MP3 loads with length 0 [verified]. MP3 results are decoded to WAV on a worker (Qt's audio decoder, which works in `mayapy` [verified]), the original kept. Sound file names must not start with a digit [verified]. Audio to text and audio to video models: Later.

### 6.12 Environment

| Operation | Model examples | Result | Landing | Release |
|---|---|---|---|---|
| Generate panorama, From image, Upscale panorama | Skybox models | 2:1 PNG or JPG | Arnold sky dome (`aiSkyDomeLight`, lat-long, sRGB file node); replaces the scene's Scenario sky dome or adds one, never touches another dome without the review | v1 |
| HDRI | HDRI skybox model | EXR or HDR | Same, `scene-linear Rec.709-sRGB`, exposure on the dome | v1 |
| Viewport-only sky (no Arnold) | | | Textured sphere, display only | v1.1 |

Viewport 2.0 lights the scene with the dome's image but did not draw it as a background in an offscreen capture [verified]; display in the GUI viewport is checked in M2 [to verify].

### 6.13 Render (restyle a view)

| Mode | Capture | Model examples | Landing | Release |
|---|---|---|---|---|
| Image | Viewport (GUI), a camera with Viewport 2.0 (`ogsRender`, works headless [verified]), Arnold (needs a render licence for unwatermarked batch output [verified]); optional clay, depth and normal passes made with temporary shading, restored after [verified] | Image edit and control models | New image beside the capture; as an image plane on the capture camera for comparison | v1 |
| Video | Playblast of a frame range from a camera (GUI; headless, playblast only uses the default perspective camera, so the plug-in gives it the chosen camera's position and lens for the capture and restores it after, which matched a capture from that camera [verified]) | Render to real and 3D to video models (for example LTX 2.3 Quality Render to Real, Minimax H3 3D to video) | Movie on an image plane of the same camera, aligned to the range | v1 |

Captures state what they captured (camera, renderer, size, frames). Switching render layers then rendering crashed `mayapy` once [verified], so captures never switch render layers.

A viewport capture for a model input is a one-frame playblast of the viewport the person looks through, as JPEG, with the grid, the heads-up display and the selection highlight hidden for the capture. Undo recording is paused around it, and only when it was on, so the capture adds no undo step and the user's last step stays the first undo [verified 2026-10-19 in mayapy]. Batch `ogsRender` writes scene-linear values unless the renderer output transform is on, so a render without it looks far darker than the viewport, which applies the view transform [verified 2026-10-19]; renders meant for people turn it on.

### 6.14 Blockout

Plan a layout from a prompt (named blocks with sizes and positions), build it from Maya primitives in one undo step, then generate per block (image to 3D or text to 3D) and replace each block with its mesh at the block's size. Same flow as the Blender plug-in's Blockout lane. **v1.1**.

### 6.15 Platform features

| Feature | Detail | Release |
|---|---|---|
| Workflows | Team and public workflows; form from the workflow's declared inputs (image, 3D, text) with mesh inputs captured from Maya; exact price; Run with confirm | v1 (step decisions v1.1) |
| Library | Search the project's assets and collections; drag an asset into a form as a reference; land any library 3D asset like a result | v1 (organizing v1.1) |
| Prompt Spark | New, Rewrite, Translate with a separate priced Approve. The free price check returns 0 while Scenario's docs say about 2.75 CU per first result [verified], so the price shown is the docs' value marked "about" until the two agree | v1 |
| Trained models and LoRA | Team models in the picker; LoRA strength; project LoRA defaults | v1 |
| Recommend | "Suggest a model" uses Scenario's recommendation for the lane and task | v1 |
| Balance and usage | Credit balance from Scenario's team limits endpoint when the credentials allow it (API key; OAuth [to verify]), otherwise usage this month | v1 |
| Cloud history | Project history with Load older; Save for recovery on cloud jobs | v1 |
| Open on Scenario | Every result and node with provenance links to the web app | v1 |

---

## 7. Safety and trust

### 7.1 Money contract (shared with the other Scenario plug-ins)

1. **Price check and generate stay separate.** A price check is the model run with `dry_run: true`. It is free, runs by itself 0.7 s after the last edit of the visible form, and its result is the price on the button. A dry run checks required inputs but not mesh formats or face caps [verified], so the plug-in checks those itself before quoting (6.3).
2. **A quote is single use and bound to the payload**: model id, canonical JSON of the parameters with its SHA-256, workspace, input asset ids, and the scene origin it was made from (scene, target node and its fingerprint). Any change invalidates it. Quotes expire after 120 s. Before quoting, every model named in the form (LoRAs, composition members) is re-read and must be usable.
3. **A price check that returns a job is an alarm**: automatic price checks stop until Maya restarts, and the job is tracked like any other.
4. **The intent is saved before the paid request.** The ledger row moves `prepared` to `submitting` with the payload hash, quote hash, exact cost string and claim time, then exactly one request is sent, with no retry. Any failure after the claim where Scenario may have started the work (no reply, a timeout, 408, 5xx, a tool error that is not a 4xx refusal) makes the job **Not confirmed** (`uncertain`). A 401 or an expired session is refused before the tool runs: the token or session is renewed and the request sent once more. A 429 or a 4xx refusal from Scenario is reported as not sent and is never retried by itself. On restart, a saved `submitting` row whose Maya session has ended becomes `uncertain`.
5. **A Not confirmed job blocks an identical request** (same workspace, model, target and payload hash), checked after the price check, before the claim and inside the claim under a lock. Resolution is human only: the plug-in lists candidate jobs from Scenario's history (same model or workflow, from 10 minutes before to 1 hour after the claim, closest first, at most 20, none preselected); the person links one, which is verified by a fresh read, or marks the row reviewed. Agents can search candidates but cannot link or mark. This follows the Blender plug-in's rule, stricter than the automatic match in the Unreal spec; decision 9 makes it the rule for every plug-in.
6. **Spend guards**: an optional confirmation threshold for people (off by default), `SCENARIO_NO_SPEND=1`, and team caps enforced by Scenario and shown as errors. The plug-in sets no CU cap of its own.
7. **Moderation shows as Blocked** and is never retried. Failed jobs show Scenario's error and hint; refund is Scenario's policy and is not inferred from the job record (the record has no refund field [verified]).
8. **Uploads are free** as far as the job records show (`cuCost: 0` on upload jobs [verified]), but still happen only on an explicit action, because they send the user's files.

### 7.2 Approvals

| Who | What needs approval | How |
|---|---|---|
| Person | Every paid call | The click on a priced Generate button; a confirm dialog only above a threshold the user chose. Workflows and Prompt Spark have their own priced Approve button |
| Person | Changes to existing scene content | The Apply click in a review that names the target and what changes (4.7). New content (an import) is one click on the result card |
| Agent | Every paid call | The agent must call `estimate_cost` and pass the returned `quote_id` and the exact `approved_cost` string; the server refuses anything else. A call with a valid quote is approved automatically: no prompt in Maya and no CU cap from the plug-in, the same rule for every Scenario plug-in (decision 7). Each agent spend shows in the panel and the Agents activity log with client, tool, model and CU. `SCENARIO_NO_SPEND=1` and Scenario's own team limits still apply |
| Agent | Any change to the scene | Only when **Allow agents to change this scene** is on (off by default, per user, shown in the panel header). When it is off, `apply_result_application` returns `pending_approval` and the panel shows a proposal card that the person applies or dismisses |
| Agent | Running Python or MEL | Only when **Allow agents to run Python** is on (separate switch, off by default, needs the first one). It is not a sandbox: code runs with the user's rights |

The agent's own description of a price is guidance, never authorization. Automatic approval never skips the quote check.

### 7.3 Undo

Measured in `mayapy` 2027.2 [verified]: `cmds.file(i=True)` flushes Maya's whole undo queue for FBX, OBJ and `.ma` (0 of 3 earlier user steps could be undone afterwards), so the user would lose all undo history; the FBX plug-in's own `FBXImport` command records nothing and flushes nothing; `mayaUSDImport` undoes only once; edits made through the API from a script never enter the undo queue. A small Python API 2.0 command (`MPxCommand`) that records every node an import creates, deletes them in `undoIt` (DAG nodes, then the remaining DG nodes such as materials and shading groups) and restores the same nodes in `redoIt` gave exact undo and redo over two full cycles for every apply mode; a version whose redo re-imported crashed Maya, and one that deleted only DAG nodes left materials behind.

Measured in the Maya 2027.2 GUI on macOS [verified 2026-10-19]: a card landed from its result card's button and a 3D import from **Import** are each removed by one undo and restored by redo, with the panel's events running in between as after a person's click. Two Maya behaviours matter for scripts and agents. Maya finishes `file -new` on idle and resets the undo queue then, so an undo step made in the same tick as a new scene can be lost (a cube made right after `file -new` had no undo entry); scripted checks wait for the new scene to settle. A playblast, even offscreen, and a selection change are undo steps of their own, so a check that runs either between the landing and the undo undoes that step instead.

Rules:
- **One action, one undo step.** Every scene change runs inside one named undo chunk (`Scenario: Import brass lantern`, `Scenario: Replace UVs on crate_GEO`), opened and closed in `try/finally`, so one Ctrl+Z reverts the whole action, including materials, file nodes, namespaces and selection.
- **Never `cmds.file(i=True)` into a user scene.** GLB lands through our builder and FBX, OBJ and USD through their importers, each inside the plug-in's recording import command (6.4); any other loader is wrapped the same way. Plug-ins are loaded and importer options set before the chunk opens.
- **Redo never re-imports or regenerates.** It restores the same nodes. Undo and redo change scene data only: job state, receipts and spending stay as they are, and applying a result again needs a fresh review.
- **Undo off or limited.** If the user turned undo off or set a short queue, the review says "Undo is off in this session; Keep original is on" and turns Keep original on. The plug-in never changes undo settings.
- **Keep original** (default on for edits): the original stays in the scene in the form each mode allows (the old shape hidden, a backup UV set, the old material unassigned, the source hidden; 6.4), so it can be restored after the undo history is gone. Undo removes it with the rest of the action.
- **Known residue**: undoing a Time Editor clip leaves Maya's single `timeEditor` node, which is harmless.
- **What undo cannot revert**: files written to disk (downloads, captures, exports) stay in the project's Scenario folders; nothing in the user's scene points to them after undo. The menu offers "Clean unused Scenario files", which lists them with sizes and moves them to the OS trash after confirmation.
- **Saving**: the plug-in never saves the scene. Agents cannot save it in v1. Downloaded files are new files with unique names, never overwrites.
- **Crash during an apply**: the job stays `applying` and shows **Needs review**; it is never retried by itself. Maya's autosave or crash recovery file may hold a half-applied state, and the review says so.

### 7.4 Job recovery

- The ledger (3.3) survives Maya restarts and crashes. At startup it only reads: jobs are listed for inspection, and work resumes only from an explicit action (Resume, Retry download, Find in Scenario history) or, for people, the "Resume my jobs" banner. A job that was `remote` before the restart resumes polling when the person opens the panel or an agent calls `recover_local_job`.
- Polling: one read every 2 s; on timeout, lost connection, 408, 429 or 5xx the next read waits 4, 8, 16, 32, then 60 s (or `Retry-After`, up to 300 s) with the note "Status not refreshed; retrying"; after eight transient failures in a row, or any other error, delivery pauses for review.
- Downloads go to `<file>.part` with HTTP range requests, each attempt with a fresh signed link (signed links are never stored, and Scenario's signed links expire at the end of the month [verified]); each finished file gets a SHA-256 receipt and is renamed atomically. Existing receipts are rehashed, never downloaded again. A per-job OS lock tells a live download from an interrupted one across Maya sessions.
- Cancel is offered only where Scenario accepts it; most generation jobs refuse it today [verified], so the UI usually shows "Scenario cannot cancel this job; it will finish and be charged."
- Long jobs: the hosted MCP's wait call returns after about 180 s [verified], so the poller handles any length (some world models run close to an hour).
- Adopting a finished cloud job ("Save for recovery") creates a local record with no fabricated quote, so results generated elsewhere (web app, another machine) can be applied in Maya.

### 7.5 What leaves the machine

Summary here, full text in [`docs/PRIVACY.md`](../PRIVACY.md).

- **To Scenario**: prompts, parameters, files the user attaches or captures (viewport and camera captures, playblasts, exported meshes for 3D edits), workflow inputs, and the identity of the account or key. Price checks send the form while it is being edited.
- **Mesh exports** contain only the nodes the user chose: geometry, UVs, normals, materials and their textures, skin and skeleton when the task needs them. Node and material names are replaced by neutral names (`scn_input_0`) by default, and the mapping stays local, so project and character names do not leave the machine unless the user turns the option off.
- **Nothing else from the scene**: no scene listing, file paths or node names, unless the user or an allowed agent sends them as an input.
- **To nobody**: the agent server listens on loopback only. What an agent receives (scene summaries, screenshots, node details) goes to that agent's own model provider under the user's agreement with that provider.
- **Update check**: once a day the plug-in reads the latest release number from GitHub (no account or scene data); it can be turned off.
- **Telemetry**: off by default, asked once, documented field by field (decision 12).
- **Stored in the scene and shared with it**: provenance attributes on generated nodes (10.3), including the prompt unless the project setting leaves it out. Anyone who receives the `.ma` or `.mb` file can read them.

---

## 8. MCP design

### 8.1 Principles

1. **Same names as the Blender plug-in's server for shared concepts**, so one cross-DCC skill and one agent habit cover both. Verb-first snake case. Maya-only tools use Maya terms.
2. **Small tool definitions.** A test caps the total size of `tools/list` (target under 40,000 characters) and each tool description (2,500 characters). Edge cases go in results and docs.
3. **Every tool that changes something reports what changed**: nodes created, with full DAG paths; nodes modified and how; files written; undo availability. A call that changed nothing returns an error that says so.
4. **No dialogs.** Nothing an agent triggers may open a modal dialog; a step that would returns an error with the reason. Importer options are always set explicitly.
5. **Prepare, then apply.** Every result that lands in the scene goes through `prepare_result_application` (no network, no scene change, returns the review text and a single-use `application_id`) and `apply_result_application` (once, in one undo chunk). The handle dies on any scene change, frame change, undo, redo, file open or credential switch in between.
6. **Optional means optional**; `null` arguments count as omitted (strict clients send `null` for every unset option).
7. **Captures say what they captured**: camera, renderer, resolution, frame, and whether it was the GUI viewport or an offscreen render.
8. **Annotations**: read-only tools declare `readOnlyHint`; tools that change the scene declare `destructiveHint`; tools that spend say "Spends credits" first in their description. Every paying tool is annotated the same way (the Blender server is not consistent here).

### 8.2 Transport and security

- `http://127.0.0.1:9878/mcp`, JSON-RPC over POST, JSON replies, `GET /health`. Protocol versions 2025-06-18 (preferred), 2025-03-26 and 2024-11-05, as in the Blender plug-in. Server `instructions` at `initialize`: start with `scene_summary`, prefer specific tools over Python, quote before generating, prepare and show the review before applying, platform-wide work (training, usage, team admin) on the hosted Scenario MCP.
- Host check on every request (one Host header naming `127.0.0.1`, `localhost` or `[::1]`); Origin absent or loopback; CORS preflight refused. This blocks DNS rebinding and web pages.
- **Bearer token on by default**, generated once per user, stored in the credential store, stable across restarts. The Connect buttons write it into the client's configuration, so the user never handles it. A setting turns it off for clients that cannot send headers. Blender 0.12 runs without a token; we keep one, as the Unreal plug-in does, because this server can spend money and change scenes, and the Connect buttons remove the friction.
- Body limit 10 MiB, idle socket 60 s, tool time limit 120 s (170 s for `wait_for_job`, whose default wait is 45 s because some clients stop at 60 s).
- **Main thread**: each call is queued to Maya's main thread through the dispatcher (3.3). A call that has not started within its time limit returns "Maya is busy; the tool was not executed". A call that started is never interrupted; a timeout then means "unknown outcome, inspect before retrying". Calls that change the scene are not run while a modal dialog is open in Maya (Qt runs timers inside modal loops, so the dispatcher checks for an active modal widget first).
- Uploads by agents are limited to files the plug-in produced (captures, exports) or files the person chose in Maya this session.
- Errors are one line, `Type: message`, with no secrets and no paths outside the project.
- **Never `commandPort`.** Maya's command port has no authentication [verified]; the plug-in neither uses nor opens it, and the docs explain why.
- Lifetime: starts with the plug-in in GUI sessions (setting, on by default), stops with Maya; headless start is explicit (`mayapy -m scenario_maya.serve`, 3.5). A busy port moves to the next free one of the nine above, and the Connect buttons write the actual port.

### 8.3 Tool list (v1)

**Scene, read (always allowed)**

| Tool | Blender name | Purpose |
|---|---|---|
| `scene_summary` | same | Scene file and modified state, units, up axis, frame range and rate, selection, cameras, renderer, node counts by type, a paged list of top-level transforms, Scenario nodes in the scene |
| `object_detail` | same | One node: type, DAG path, transform, bounds in scene units and metres, shapes, face and vertex counts, UV sets, materials and textures, history, deformers, skin and joints, animation, references and namespaces, Scenario provenance |
| `screenshot_viewport` | same | The active viewport (GUI only) or a camera rendered offscreen, returned to the agent, with camera, size and renderer stated |
| `capture_views` | same | Offscreen labelled contact sheet of the selection or scene from several angles (works headless) |
| `render_still` | same | A still from a camera with Viewport 2.0 (default) or Arnold, written to the project's Scenario captures folder |
| `output_log` | (Unreal name) | Recent Maya warnings and errors from the Script Editor stream, filterable |
| `maya_api_help` | `blender_api_help` | Flags of a `maya.cmds` command or attributes of a node type, read from Maya itself, before writing Python |

**Scenario, read (always allowed)**

| Tool | Blender name | Purpose |
|---|---|---|
| `scenario_status` | (Unreal name) | Signed in or not, workspace, plug-in and Maya versions, permissions in force, online state |
| `list_models`, `model_schema`, `model_defaults` | same | Catalog by lane or capability (at most 40 rows, quick picks first); form parameters with accepted file kinds and price-moving fields; project LoRA defaults |
| `recommend_models` | (Unreal name) | Scenario's recommendation for a task |
| `estimate_cost` | same | Free dry run for a form; returns `quote_id`, `cu_cost_exact`, `cu_cost`, expiry, and the destination it was bound to |
| `estimate_prompt`, `read_prompt_result`, `read_model_text` | same | Prompt Spark price and results; full text results |
| `job_status`, `wait_for_job`, `inspect_result_previews` | same | Status with valid actions, delivery flags, results with file states and import units; result previews as images |
| `list_local_jobs`, `list_generations` | same | Ledger and cloud history |
| `list_workflows`, `workflow_schema`, `estimate_workflow`, `workflow_job_steps` | same | Workflows, their forms, prices and step states |
| `list_assets`, `search_assets`, `list_collections` | same | Scenario library |
| `reference_upload_status`, `list_reference_uploads` | same | Upload states |

**Scenario, spend and upload (quote contract, 7.2)**

| Tool | Blender name | Purpose |
|---|---|---|
| `generate` | same | Needs `quote_id` and `approved_cost` equal to the quote's exact string; saves intent; returns `job_id` |
| `approve_prompt`, `run_workflow`, `discard_workflow_estimate` | same | Prompt Spark and workflows, same contract |
| `capture_reference` | same | Viewport, camera, playblast range or selected meshes to a local file ready to upload (mesh exports as GLB or FBX with neutral names) |
| `upload_reference`, `recover_reference_upload` | same | Uploads a plug-in-produced or user-chosen file; returns a handle, then the `asset_id` |
| `recover_local_job`, `recover_cloud_job`, `cancel_prepared_job` | same | Resume, retry a download, search candidates for a Not confirmed job, adopt a finished cloud job, drop a prepared job that was never sent |

**Scene, change (Allow agents to change this scene)**

| Tool | Blender name | Purpose |
|---|---|---|
| `prepare_result_application` | same | Purpose (`import`, `mesh_edit`, `material`, `environment`, `image_plane`, `audio`, `video_first_frame`), target, `mesh_policy`, `mesh_placement`, `keep_original`, options; returns `application_id` and the review. Read-only |
| `apply_result_application` | same | Applies once, in one undo chunk; returns what changed and the import checks. With the switch off, returns `pending_approval` and shows a proposal card |
| `import_result` | same | Always refuses and explains the prepare and apply flow (kept for agents that guess the name) |
| `select_objects`, `set_frame` | same | Select nodes by path or name; set the current frame |
| `execute_python` | same | Python or MEL on the main thread, inside one undo chunk; separate switch, off by default; output and size capped |

That is 46 tools in v1 (Blender has 88, 38 of them for Film and Blockout). **v1.1 adds** `camera_path`, `decide_workflow_step`, `prepare_asset_organization`, `apply_asset_organization`, `asset_organization_status`, and the five Blockout tools.

### 8.4 Agent result vocabulary

`job_status.mesh_edit` and `apply_result_application` return, where relevant: `target` (DAG path and shape), `original` (kept copy), `policy`, `placement`, `result_to_source` (matrix), `fit_residual`, `surface_match` (method, counts), `parts` (paths), `rig` (joint count, skinCluster, max influences), `clips` (names, ranges, where they landed), `rest_correction_deg`, `frame_rate_mismatch`, `undo_available`, `nodes_created`, `nodes_modified`, `files_written`. Names follow the Blender plug-in's fields where the concept is the same.

### 8.5 Other ways in (adapters)

| Adapter | What | When |
|---|---|---|
| Python API `scenario_maya.api` | The same actions for studio scripts, shelf tools and other plug-ins. Paid calls still need a quote from the same session (`api.estimate(...)` then `api.generate(quote)`) | v1 |
| `mayapy -m scenario_maya.serve` | Headless agent server for CI and pipelines (3.5) | v1 |
| Command line | `mayapy -m scenario_maya.cli` for batch jobs (generate from a CSV, land results into scenes) with `SCENARIO_NO_SPEND` dry runs | v1.1 |
| Tool package for community Maya MCP frameworks | A thin package that exposes our actions inside those servers, so agents already connected there get Scenario with the same quote and approval rules | Later, if one framework becomes a standard |
| Autodesk LookdevX Generative Textures | Register Scenario image and material models as a provider in LookdevX's experimental generative texture API | Later; depends on Autodesk's API leaving its experimental state |
| Hosted Scenario MCP | Platform-wide work (training, usage, team administration, collection rename) | Already available; our server's instructions point to it |

### 8.6 Client setup ("Connect a client")

Connection > Agents shows the server state, URL and port, and one row per client found on the machine, with its status (last seen at `initialize`):
- **Claude Code**: runs `claude mcp add --transport http scenario-maya <url> --header "Authorization: Bearer <token>" --scope user`; falls back to editing `~/.claude.json` with a backup.
- **Codex**: `codex mcp add`, or `~/.codex/config.toml` with a backup.
- **Cursor**: `~/.cursor/mcp.json` with a backup.
- **Claude Desktop**: through a small stdio bridge run with Maya's own `mayapy` (so no Node or extra Python is needed), written into `claude_desktop_config.json` with a backup.
- **Copy setup** for anything else (JSON, TOML, one-line commands).

Each writer replaces only its own `scenario-maya` entry, keeps the file's permissions, leaves a file it cannot parse untouched and says so, and asks the user to reload the client. Hosted agents (web chat apps) cannot reach a loopback server; the panel says so.

### 8.7 Autodesk Marketplace requirements for the server

Autodesk's marketplace asks MCP servers in its listings for an MCP Tool Manifest (a JSON list of every tool), a Publisher Declaration Form, every external domain and every AI provider that receives data, HTTPS for every external connection, and user consent for data sent [verified: Autodesk MCP publisher guide]. So: the release build generates the manifest from the tool registry (CI fails if a tool changes without a manifest change), the tool list is frozen per release, and the declared domains are Scenario's (`mcp.scenario.com`, `api.cloud.scenario.com`, `app.scenario.com`, the asset CDN) plus the release check on GitHub. The model providers Scenario routes to are listed from Scenario's own provider list at submission time [to verify with Autodesk: whether a platform that routes to many providers declares itself or each provider].

---

## 9. Skills integration

The plug-in links to skills; it does not bundle them. Skills live in `scenario-labs/skills` and update on their own cadence; a bundled copy would drift.

**New skill `scenario-maya`** (in `scenario-labs/skills`, beside `scenario-blender`), written once the v1 tool list is frozen, about 1,200 to 1,500 words:
1. What the plug-in is, supported Maya versions and OS, where the docs live; credentials stay in the plug-in, never handled by the agent.
2. Setup: URL and port 9878 (not 9876 Blender, not 7001, the Maya expert skills' command port bridge), token written by Connect, loopback only, 401 means a stale token; headless `mayapy -m scenario_maya.serve`, and what fails headless (GUI viewport screenshots, dialogs).
3. Tool order: read the scene, pick and price, generate, wait, prepare, show the review, apply, check the read-back.
4. Money rules, verbatim from the Blender skill: fresh quote and the user's yes, single use, exact approved string, a price check never authorizes, unattended runs report and stop, never repeat a timed-out generate.
5. Placement rules: imports and edits wait for an approved destination; one undo chunk per apply; the scene is never saved by a tool.
6. Lane facts that differ in Maya: GLB is the native carrier and lands through the plug-in, never through `cmds.file`; scene units are centimetres by default and the plug-in converts; quads survive only as FBX; smoothness is inverted to roughness; HDRIs are scene-linear; MP3 is decoded to WAV.
7. A worked example: capture the selected mesh, UV unwrap it, apply UVs in place, then hand over to `scenario-maya-retopology-uv` and `scenario-maya-lookdev`.
8. Common mistakes: using the command port bridge and the plug-in at once, a `reference_id` in a file field, assuming Python is on, assuming the scene is saved.

**Updates to the existing Maya expert family** (11 skills, written before Maya was available for live runs, so their own status says their Maya calls are not yet run):

| Skill | Change |
|---|---|
| All 11 | Run the family's own probe and test suite in Maya 2027.2 and mark what passed as verified; remove personal names and build-machine paths from the public text |
| `scenario-maya-expert` | A "Live channel: Scenario for Maya" section (setup, quotes and placing belong to `scenario-maya`; this skill covers the `maya.cmds` side), one logical change per call so one undo reverts it, and a `references/scenario-result-intake.md` checklist |
| `scenario-maya-pipeline-scripting` | Procedure "Import a Scenario GLB or FBX": the importer traps found in this spec (6.7) and a before and after stats check |
| `scenario-maya-lookdev` | Scenario's texture role names, smoothness inversion, colour spaces from Maya's default config, openPBRSurface wiring |
| `scenario-maya-retopology-uv` | Generated-mesh intake: triangle GLB versus quad FBX, face caps of the unwrap models, when to use the Scenario edit versus Maya's own retopology and UV tools |
| `scenario-maya-rigging`, `-animation`, `-deformation` | Adopting a rig and clip from Scenario: joint naming, bind pose, influence count, HumanIK characterization for retargeting, Time Editor clips, a weight check pass |
| `scenario-3d`, `INSTALL.md` | Name `scenario-maya` beside `scenario-blender` as an in-DCC route |

The Connection tab shows the install command (`npx skills add scenario-labs/skills --skill scenario scenario-maya scenario-3d scenario-maya-expert ...`) with a Copy button; the plug-in never writes into an agent's configuration without a click. The plug-in's server does not serve skill resources in v1; its instructions name the skill.

---

## 10. Asset conventions and metadata

### 10.1 Files on disk

Everything lands inside the current Maya project, in the folders Maya's file rules name, so it travels with the project:

```
<project>/
  scenario/<YYYY-MM-DD>/<slug>_<tail>/      originals as delivered (GLB, FBX, OBJ, SPZ, PLY),
                                            scenario.json (provenance + SHA-256 receipts)
  sourceimages/scenario/<slug>_<tail>/      textures used by shading networks (PNG, EXR; WebP converted)
  sound/scenario/                           audio (WAV; MP3 decoded to WAV beside the original)
  movies/scenario/                          video (as delivered, plus a MOV rewrap when needed)
  images/scenario/captures/                 viewport and camera captures, playblasts, mesh exports sent
```

`<tail>` is the last six characters of the Scenario asset id, so names are unique and traceable. Folder pattern and root are project settings. When the scene uses Maya's default project, the destination line says so and suggests setting a project. Downloads never overwrite: an existing name gets a numeric suffix. Texture paths are written relative to the project where Maya keeps them relative [to verify: one test stored an absolute path after setting a relative one].

### 10.2 Names and namespaces

- Every landed asset gets one namespace, `scn_<slug>` (numbered if taken), so reimports never clash and the whole asset can be selected or removed at once. A project setting switches to name prefixes for studios that ban namespaces.
- Slugs are ASCII `[A-Za-z_][A-Za-z0-9_]*` from the prompt or the result's own names: Maya drops leading digits, turns other characters into `_` and non-ASCII into `?` [verified], so the plug-in slugifies first.
- Top group `scn_<slug>_grp`; meshes keep the result's node names, sanitized; materials `<slug>_mtl`, file nodes `<slug>_<role>_file`. Patterns are project settings.
- Edits keep the target's names: an applied UV or retexture never renames the user's nodes.

### 10.3 Provenance

Stored as attributes on the top node of each landed asset, on every material and file node the plug-in creates, and on a target edited in place:

| Attribute | Example |
|---|---|
| `scenario_asset_id`, `scenario_job_id` | `asset_...`, `job_...` |
| `scenario_model_id`, `scenario_model_name` | `model_meshy-7-1-img23d`, Meshy 7.1 Image to 3D |
| `scenario_prompt` | full prompt (left empty when the project setting says so) |
| `scenario_parameters` | compact JSON of non-file parameters |
| `scenario_input_asset_ids` | references used |
| `scenario_quoted_cu`, `scenario_charged_cu` | exact decimal strings |
| `scenario_created_utc` | ISO 8601 |
| `scenario_role` | `albedo`, `normal`, `roughness`... on file nodes |
| `scenario_apply` | `import`, `mesh_edit:uv`, `material`... and the date, for edits in place (a list, newest first) |
| `scenario_plugin_version`, `scenario_maya_version` | `0.1.0`, `2027.2` |

String attributes added with `addAttr`, in a Scenario category, so they show in the Attribute Editor's Extra Attributes and in the Scenario section, survive save, reference and duplicate, and need no plug-in node type: scenes open cleanly on machines without the plug-in. Whether they also travel through FBX export (as user properties) and USD export (when tagged for export) is checked in M3 [to verify]. A scene-level `fileInfo` key `scenario_scene_uuid` (random, no account data) lets jobs find the scene they came from.

"In this scene" lists every node carrying `scenario_asset_id`, grouped by asset, with Select, Show job, Reload settings and Open on Scenario.

### 10.4 Import defaults by kind

| Kind | Default |
|---|---|
| Scale | Real-world size kept: glTF metres are converted to the scene's linear unit (100x for centimetres) in positions, bind matrices, morph deltas and translation keys. A target size option (longest side, in scene units) scales the group uniformly |
| Axis | Y-up scenes need no change; in a Z-up scene the group gets a +90 degree X rotation |
| Placement | People: at the camera's centre of interest, bottom centre on the ground plane, or at the selection; agents: where the prepared review said |
| Selection | People: the new group is selected; agents: unchanged unless asked |
| Time | Playback range, current frame and frame rate are restored after any importer that changes them; clips at a different rate are reported (`frame_rate_mismatch`) |
| Materials | openPBRSurface where Maya has it (it is Maya 2027's default surface); standardSurface where it is missing [to verify which 2025 and 2026 updates ship it]; aiStandardSurface on request |
| Colour spaces | From Maya's default OCIO config names, `ignoreColorSpaceFileRules` set on every file node (6.8) |
| Importer options | Every FBX and USD option set explicitly before each import, then restored (6.7) |

---

## 11. Packaging and distribution

### 11.1 The module

One folder, the same for every Maya version and OS:

```
ScenarioForMaya/
  ScenarioForMaya.mod          (written by the installer into a modules folder, pointing here)
  plug-ins/scenario_for_maya.py
  scripts/scenario_maya/       (the package, 3.2)
  scripts/install_scenario.py  (drag-and-drop installer, also shipped beside the ZIP)
  vendor/                      (truststore; imported under a private name, never put first on sys.path)
  icons/
  docs/                        (PRIVACY, THIRD_PARTY_NOTICES, quick start)
  PackageContents.xml          (only in the Marketplace bundle)
```

`.mod` file, one entry for all versions and platforms [verified: Autodesk module format]:

```
+ ScenarioForMaya 0.1.0 /path/to/ScenarioForMaya
```

Maya adds the module's `plug-ins/`, `scripts/` and `icons/` folders to its paths by itself [verified]. Version-specific lines (`MAYAVERSION:2025`) are used only if the code has to diverge. The plug-in never edits `userSetup.py` (studios own it, and Maya 2027 warns when its hash changes [verified]) and never writes into Maya's own folders.

### 11.2 Channels

| Channel | Who | What | Updates |
|---|---|---|---|
| **GitHub releases** (v0.1) | Artists, TDs | ZIP with the module and `install_scenario.py`; `SHA256SUMS` and a build provenance attestation | "Update available" notice in the panel; never installs by itself |
| **Studio deployment** | Pipeline teams | Unzip the module on a shared path and add it to `MAYA_MODULE_PATH`; settings and the model allow-list through `scenario.json` in the Maya project; agent server and spending switches can be locked by an environment variable | Studio's own |
| **Autodesk Marketplace** (after v0.1) | Artists | Bundle with `PackageContents.xml` (`SeriesMin 2025`, `SeriesMax 2027`, `AutoLoadOnce="True"` so users can turn autoload off) | Through the Marketplace |
| OS installers (`.pkg`, `.msi`) | Studios that require them | Later; a macOS `.pkg` must be signed and notarized | |

Marketplace requirements [verified: Autodesk publisher guidelines and MCP publisher guide]: Maya 2027 support on every OS Maya 2027 supports, a shelf button or menu, a plug-in manifest, a privacy policy linked in the listing and inside the plug-in, one or more test accounts for reviewers (a Scenario account with credits), and for the agent server the MCP Tool Manifest and Publisher Declaration Form (8.7). Autodesk's installer shows Autodesk's fixed EULA; our license and privacy terms are shown at first run. Whether a free plug-in that needs a Scenario account passes review is the reviewer's call [to verify with Autodesk].

### 11.3 Install, uninstall, first load

- **Install**: drag `install_scenario.py` onto a Maya viewport. It copies the module to `<MAYA_APP_DIR>/modules/ScenarioForMaya/` (no admin rights), writes the `.mod` next to it, adds the paths for this session, loads the plug-in, sets it to autoload and opens the panel. Running it again upgrades in place, keeping the previous version as `ScenarioForMaya.previous/` until the next upgrade.
- **Secure plug-in loading**: Maya 2027 asks before loading plug-ins from locations it does not trust (on by default) [verified: preference exists]. Which locations count as trusted is not documented; whether users see an Allow prompt at first load is tested in M1 [to verify], and the quick start shows the prompt if it appears.
- **Uninstall**: Scenario > Help > Uninstall unloads the plug-in, removes its `.mod` and module folder, and leaves the ledger, credentials and downloaded files unless the user ticks "Also remove my Scenario data in Maya".
- **No signing needed** for the module: a quarantined `.py` file imports without a prompt on macOS [verified]; Gatekeeper applies to executables and installers, which v0.1 does not ship.

### 11.4 Versioning and release automation

- SemVer `0.x` until 1.0. Conventional Commits, release-please with tag `maya-plugin-vX.Y.Z`, same repo conventions as the other Scenario plug-ins (AGENTS.md, commit lint, PR template, issue forms, CODEOWNERS, SECURITY and SUPPORT files, scheduled contract check, link check, OpenSSF scorecard).
- CI on GitHub-hosted runners (Linux, macOS, Windows): lint and format, `core` unit tests on Python 3.11 and 3.13, MCP protocol tests against the fake backend, tool-size budget, manifest generation, docs site build and link check, weekly free contract check against Scenario with `SCENARIO_NO_SPEND=1`.
- Maya-in-the-loop tests need a licensed Maya, which GitHub runners do not have, so they run on the development Mac through `tools/test_maya.sh` (`mayapy`, headless) and a scripted GUI session (`tools/test_maya_gui.sh`), and their reports are committed under `tests/reports/`.
- Paid smoke run: manual only, never in CI.

---

## 12. Licensing

The Scenario Blender plug-in is GPL-3.0-or-later because Blender requires it for add-ons. **No code is copied from it.** This plug-in is a reimplementation: behaviours and contracts come from the shared Scenario specs, the Blender plug-in's public documentation and our own tests; the code is written fresh.

Maya imposes no license on plug-ins written against its Python API, and this plug-in ships no Autodesk code or devkit files. Options:

| License | For | Against |
|---|---|---|
| **MIT** | Same as the Godot, Unity and Unreal plug-ins and the skills repo; studios can modify it and keep it in proprietary pipelines; simplest notice | No explicit patent grant |
| Apache-2.0 | Explicit patent grant | NOTICE file; differs from the sibling plug-ins |
| GPL-3.0 | Same as Blender's | Not required by Maya; studios avoid GPL in pipeline code |
| Proprietary or source-available | Full control | Blocks contributions; studios cannot patch locally |

**Recommendation: MIT** (decision 1). Third-party material: `truststore` (MIT) is vendored; test fixtures from the Khronos glTF sample models keep their own licenses (CC BY 4.0 and others), listed in `THIRD_PARTY_NOTICES.md`; the Scenario mark is used under Scenario's brand terms. Autodesk's Publisher Agreement forbids putting Autodesk material under open-source terms [verified]; the repo contains none.

---

## 13. Test plan

Before any push, on a real Maya. Maya version, OS and hardware are stated in the report. Every Maya test runs with `MAYA_DISABLE_CER=1` so a crash never opens Autodesk's crash reporter.

| Layer | What | How | Spend |
|---|---|---|---|
| 1. Core unit tests | Backend client (JSON and SSE replies, session renewal, error kinds, retry allow-list), quotes and fingerprints, ledger state machine (intent, Not confirmed, candidates, link, restart), schema forms, naming and paths, OAuth helpers (PKCE vectors, callback parsing, state), credential stores, glTF parser on the fixtures, MCP protocol (Host, Origin, token, initialize, tools/list, tools/call, body limit, `null` arguments), tool-size budget | `pytest` on Python 3.11 and 3.13, any OS, recorded fixtures, fake backend | 0 CU |
| 2. Maya headless | Plug-in load and unload; dispatcher and pump; every landing from local fixtures (PNG, EXR, PBR set with DirectX and OpenGL normals, static GLB, PBR GLB, rigged and animated GLB, morph GLB, FBX, OBJ, WAV, MP3, MP4, MOV, 2:1 PNG and EXR panoramas, PLY splat); every apply mode on fixture meshes, including refusals (6.4); undo and redo of each; scene state preserved (units, up axis, playback range, current namespace, selection); provenance after save and reopen, reference and duplicate; MCP tools against the fake backend | `mayapy` 2027.2 (and 2025, 2026 when installed) | 0 CU |
| 3. Maya GUI | Panel docks and restores after restart; menu, shelf and runtime commands; composer over the viewport; Attribute Editor section; secure plug-in loading prompt; keychain prompts between Maya and `mayapy`; undo in the GUI for every landing and apply mode; no main-thread slice above 16 ms during polling and downloads; UI scale 100, 150, 200 percent; screenshots of every view and state | Scripted GUI session on the development Mac, driven by a test script, with screenshots | 0 CU |
| 4. Free contract check | Sign-in (API key and OAuth), workspace listing, every quick pick resolves its schema and prices, `recommend` per lane, `SCENARIO_NO_SPEND` refusal | Script against the live service | 0 CU |
| 5. Paid acceptance | One real generation per v1 lane and per 3D task with low-cost models and small settings: image; text to 3D; image to 3D; remesh, UV unwrap, retexture, rig, animate, parts, edit by prompt on a small test mesh; text to motion; material; environment; video (shortest, lowest resolution); audio; render image; render video; a splat; a workflow; Prompt Spark. Each result landed with its apply modes, checked by eye in the GUI, charge compared with quote | Live, ledger in `tests/live/LEDGER.md`; no single run above a few dollars of credits without asking first | Low-cost models, small settings |
| 6. Recovery | Quit Maya during a generation and during a download; relaunch; the job resumes, the download resumes, nothing is charged twice; kill Maya during an apply: the job shows Needs review. An injected transport failure on submit gives Not confirmed and blocks a resend | Live (one low-cost run) plus fake backend | One low-cost run |
| 7. Error paths | 401 (revoked token), 403 (blocked model), 429, offline, partial download, expired link, moderation, wrong mesh format for a model (refused before upload), over the face cap | Fake backend for most; revoked token and offline live | 0 CU |
| 8. Agent session | Connect Claude Code with the button; a real agent session reads the scene, quotes, generates an image and a mesh, prepares and applies with the switch off (proposal card) and on, runs one mesh edit with an apply mode, checks the read-back, and is refused when it tries to link a Not confirmed job or run Python with the switch off; the same through `mayapy -m scenario_maya.serve` | `claude -p` script plus the activity log | Two low-cost runs |
| 9. Install | Fresh user profile: drag-and-drop install, first generation timed (target under 2 minutes), upgrade over a previous version, uninstall; scene with Scenario nodes opens cleanly without the plug-in | GUI, timed | One low-cost run |

The test report lists versions, OS, hardware, what ran, what passed and failed, screenshots, the paid ledger, and known limitations, with verified and not verified kept apart. Then the push request.

---

## 14. Milestones

| Milestone | Content | Gate |
|---|---|---|
| M0 | This spec, approved | Done 2026-10-19 |
| M1 Foundations | Repo, CI, module skeleton, installer, plug-in load and unload (GUI and `mayapy`), dispatcher, `core` (backend client, API key and OAuth, credential stores, quotes, ledger, schema forms, catalog), fixtures, free contract check; first GUI checks (panel restore, secure loading prompt, keychain prompt) | Layers 1 and 4 green; GUI checks recorded |
| M2 First lane end to end | Panel, picker, price button, Image lane: generate, download, land (material, card, image plane), provenance, Jobs, restart recovery, sign-in and onboarding | First generation under 2 minutes from a fresh install, measured |
| M3 3D | GLB builder (static, PBR, skin, animation, morphs) and FBX path, import checks, Text, Image and Multi-view modes, mesh capture and export, Edit selection with every apply mode, Motion | Layers 2 and 3 green for 3D; paid acceptance for each 3D task |
| M4 Other v1 lanes | Materials, Environment, Video, Audio, Render image and video, Prompt Spark, LoRA, workflows, quick composer | Paid acceptance per lane |
| M5 Agents | MCP server, 46 tools, approvals, permission switches, Connect a client, activity log, headless server, manifest, `scenario-maya` skill draft | Layer 8 green |
| M6 Polish and report | Library, Results history, In this scene, Attribute Editor section, docs site and handbook, performance pass, 2025 and 2026 runs where installed, packaging, full test report | The push request |
| v1.1 | Blockout, marking menu, camera paths, workflow step decisions, library organizing, command line, splats with SPZ conversion, a HumanIK mapping UI for skeletons the automatic mapping does not know, Marketplace listing | |
| Later | LookdevX provider, community MCP adapter, USD stage landing, Bifrost and MASH recipes (scatter generated props), OS installers | |

---

## 15. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Scenario's GLBs use features our reader does not handle yet (Draco, meshopt, KTX2, texture transforms, second joint sets) | Missing or wrong geometry and materials | Check the first real outputs of every 3D model family in M3; the reader refuses what it does not handle with a clear message instead of landing it wrong; FBX conversion as fallback |
| Scenario's FBX conversion drops textures or animation (one test found an FBX with only 2 embedded images) | Fallback path loses data | GLB first; compare GLB and FBX of the same asset in M3; list per model what survives |
| Which mesh formats each edit model accepts is not in the catalog, and price checks do not validate it | A paid job fails on format | Per-model input table kept by the plug-in, checked before upload; GLB default, FBX where a model requires it; refused before spending |
| Undo and redo behave differently in the GUI than in `mayapy` | Broken undo for users | Layer 3 covers every landing and apply mode in the GUI |
| Scenario's edit results come back triangulated, split at seams or reordered | Exact apply modes refuse too often | The matcher of 6.4 (weld, triangle-in-face proof) built and tested on real results in M3; approximate paths with figures and a confirm |
| HumanIK has no official scripting reference | Retargeting breaks in a Maya update | Retarget tests on every supported version; exact-name and saved-map paths do not depend on it |
| Large imports block Maya | UI freezes | Parsing and decoding on workers; node creation in bulk from arrays; main-thread slices measured; very large meshes go through a progress line that stays responsive |
| macOS keychain prompts across Maya binaries | Confusing prompt at sign-in | `security -i` fallback (5.3), tested in M1 |
| Secure plug-in loading prompt at first load | Extra click, possible block in studios | Tested in M1; quick start shows it; studio deployment docs name the trusted-path setting |
| No Maya 2025 or 2026 installed here | Version bugs ship | Pure-Python compatibility rules, `compat` module, `pytest` on Python 3.11; mark untested versions in the report |
| No Windows or Linux machine | Platform bugs ship (credentials, paths, media codecs) | Platform code small and isolated, unit-tested on GitHub runners; marked untested in v0.1 |
| Hosted MCP replies change | Broken parsing | Defensive parsing, fixtures, weekly contract check, backend interface for a REST swap |
| OAuth edge cases (redirect ports, consent, device registration) | Sign-in fails for some users | API key path first-class; device code fallback |
| Studio pipelines ship other versions of the same Python packages | Import clashes | Only one vendored package, imported under a private name; no global `sys.path` prepend |
| Importers change scene-wide state (units, up axis, playback range, current namespace) | Silent damage to the user's scene | Every option set explicitly, scene state captured before and restored after, tested per importer |
| Autodesk Marketplace rejects a plug-in that needs an account, or asks for each AI provider | No store listing | GitHub channel first; early contact with Autodesk; offline features (provenance view, GLB import of any local file) |
| Agents report success on no-ops | Lost work | Read-back results; tests for each tool's effect |
| Test spend grows | Cost | Low-cost models and small settings, ledger per run, ask before anything above a few dollars |

---

## 16. Decisions and open questions

Decided on 2026-10-19: every recommendation below was accepted, with decision 7 amended (agents spend automatically, no cap, one rule for every Scenario plug-in) and decisions 3, 11 and 18 made precise.

| # | Topic | Decision | Alternatives considered |
|---|---|---|---|
| 1 | License | **MIT**, as the Godot, Unity and Unreal plug-ins and the skills repo (section 12) | Apache-2.0; proprietary |
| 2 | Names | Repository `scenario-labs/maya-plugin`, private until v0.1 is tested; product "Scenario for Maya"; module `ScenarioForMaya`; Python package `scenario_maya`; MCP server name `scenario-maya`; docs at `maya.scenario.com` in the style of `blender.scenario.com` | `scenario-labs/scenario-maya` |
| 3 | Maya versions | 2025, 2026 and 2027 from one code base; live tests on 2027.2 only for v0.1, with 2025 and 2026 covered by code rules and unit tests and marked "not tested live" in the report | 2027 only (simpler, but excludes studios that stay on a version for a production's length) |
| 4 | Sign-in | Browser OAuth with device code fallback, and API key, through the hosted Scenario MCP (as Unreal and Unity) | API key only for v0.1 |
| 5 | Agent server | Inside Maya, port 9878, bearer token on by default, written by Connect; adapters in section 8.5 later | No token (as Blender 0.12) |
| 6 | Agent permissions | "Allow agents to change this scene" and "Allow agents to run Python" both off by default | Scene changes on by default |
| 7 | Agent spending | Quote contract, approved automatically: an agent call with a valid server-issued quote spends with no prompt and no cap; every spend logged and shown. One rule for every Scenario plug-in | Ask in Maya for every paid agent call; automatic approval below a CU threshold |
| 8 | Machines | macOS (Apple Silicon) for live tests; Windows and Linux built and unit-tested on GitHub runners but marked untested in v0.1 | Borrow or rent a Windows machine with Maya for one test pass before release |
| 9 | Not confirmed submissions | Human-only resolution, as Blender (7.1), and align the Unreal, Unity and Godot specs on it | Automatic match of one candidate, as the Unreal spec |
| 10 | Distribution | GitHub release ZIP with the drag-and-drop installer for v0.1; Autodesk Marketplace after v0.1 (needs an Autodesk publisher account, a reviewer test account with credits, a public privacy policy URL, the MCP manifest and declaration form) | Marketplace from v0.1 |
| 11 | Test spend | A dedicated test API key in the existing test project, kept in the macOS Keychain only; low-cost models and small settings; no single run above a few dollars of credits without asking; every run in the ledger | |
| 12 | Telemetry | Opt-in, off by default, asked once; the client ships silent until Scenario names an endpoint for it (the Blender plug-in's relay is on its own domain) | No telemetry in v1 |
| 13 | Skills | After the plug-in is tested: a `scenario-maya` skill and the Maya family updates (section 9) in one pull request to `scenario-labs/skills`, including the public-text cleanup, shown before it is opened | Skill first, from the spec |
| 14 | Maya Creative | Not supported in v1; detected with a clear message; tested if a Creative install becomes available | Ship a Creative module file blind |
| 15 | Material default | openPBRSurface where available, aiStandardSurface on request (section 6.8) | aiStandardSurface everywhere (wider Arnold habits, less portable to USD) |
| 16 | Prompt storage | Prompts stored on nodes by default, with a project setting to leave them out | Off by default (more private, less useful) |
| 17 | LookdevX provider | Later, once Autodesk's generative texture API leaves its experimental state | v1.1 |
| 18 | Reviewer | The Scenario plug-in maintainer who reviews the Unreal plug-in is the code owner (`CODEOWNERS`) | |

Open questions for Scenario (not blocking the start, each with a test in the milestones):
- Conversion to GLB was free and kept skins and clips in a sibling plug-in's runs. What survives conversion to FBX (textures, blend shapes, multiple materials, UV sets)?
- Which mesh formats does each edit model accept beyond GLB, and could the catalog say so?
- Does Scenario refund a job that fails on input format after charging it (the failed job record keeps its price)?
- Prompt Spark: the free price check says 0, the docs say about 2.75 CU. Which is right?
- Can the hosted MCP's OAuth token read the team limits endpoint for the balance?
- Would Scenario add an idempotency key to model runs? It would let the plug-in resolve most Not confirmed submissions without asking the person.

---

## 17. Verified and assumed

**Verified on 2026-10-18**, live in headless `mayapy` 2027.2 on macOS (Apple Silicon), in Autodesk's documentation and Maya's own install, in the hosted Scenario MCP (free calls and dry runs only) and in the Scenario Blender plug-in's public documentation:
- Maya 2027.2 ships Python 3.13.9, PySide6 and Qt 6.8.3, Maya USD 0.37.0 on USD 25.11, MtoA 5.6.2 with Arnold 7.5.2, FBX plug-in 2020.3.9; no PyMEL; no glTF translator. Python and PySide versions of 2025 and 2026 from Autodesk's tables.
- Threading: `executeDeferred` never runs headless; `executeInMainThreadWithResult` deadlocks without an idle pump; a queue and Future dispatcher works; the default SSL context fails in macOS `mayapy` and `truststore` works.
- Local server prototype: token and Origin checks, main-thread dispatch, 8 parallel calls.
- Undo: `cmds.file(i=True)` flushes the queue; `FBXImport` records nothing; `mayaUSDImport` undoes once; the recording import command undoes and redoes exactly over two cycles for every apply mode; a redo that re-imports crashed.
- The glTF reader prototype on four Khronos samples, matched against Maya USD's import.
- On 2026-10-19: the plug-in's GLB builder inside its recording import command: one undo removes meshes, materials, file nodes, skin, blend shapes and the namespace; redo restores the same nodes (same UUIDs). `MQuaternion` products follow matrix order. Maya refuses to unload a plug-in while its command sits in the undo queue ("still in use"); the installer then replaces the files and asks for a restart.
- On 2026-10-19, in the hosted Scenario MCP (free reads and dry runs): a Meshy 7.1 Text-to-3D job lists seven assets, the GLB first (`mimeType` `model/gltf-binary`, `metadata.format` `glb`), then an OBJ (`model/obj`) and an MTL (`model/mtl`) whose `parentId` is the GLB, then textures; GLB and OBJ records carry `faceCount`, `vertexCount` and `dimensions` in metres, plus a thumbnail. Meshy 7.1 leaves `shouldRemesh` off by default; a 30,000 target polycount prices the same (120 CU). Meshy T2.5 Smart Topology prices 20 CU untextured and 60 CU textured.
- On 2026-10-19, in the Maya 2027.2 GUI with live models: Meshy 7.1 Text-to-3D with the 30,000-face preset delivered a GLB of 29,041 faces 109 s after Generate, charged as quoted (120 CU); its thumbnail appeared on the asset record 9 s after the asset.
- On 2026-10-19, uploads on the hosted Scenario MCP: `upload_asset` returns storage links that sign only the `host` header and carry `x-amz-checksum-crc32` and `x-id=UploadPart` in the query; the plug-in's own PUT (the link as given, the file's content type, no checksum header) was accepted and `upload_asset_complete` answered `imported` with the asset id. Image to 3D with that asset priced 120 CU (Meshy 7.1, 30,000 faces) and 220 CU (Tripo P2) in dry runs, and both runs charged those prices; their GLBs imported headless through the plug-in's builder. The run itself was sent through the Scenario MCP, not from the panel: the panel's Image mode is tested against the fake server and waits for a GUI session.
- Importer traps in 6.7; material recipe and colour space names in 6.8; image plane, sound, MP3 decoding, sky dome and splat behaviour in 6.9 to 6.12; headless capture in 6.13.
- macOS Keychain through ctypes from `mayapy`; `security -i` over stdin; `keyring` needs compiled code on Linux.
- Module format, default module paths on macOS, Autodesk bundle layout and `PackageContents.xml` fields from Autodesk's own installed bundles; Marketplace and MCP publisher rules from Autodesk's pages.
- Scenario: catalog counts, model inputs and options, dry-run prices, conversion formats, upload flow, job fields, signed link expiry, OAuth metadata, and the Blender plug-in's apply and recovery contracts (behaviour only).
- Apply modes in 6.4 and 6.5: method, exactness, refusals and undo for replace geometry, UVs, textures, attach rig, apply animation (including headless HumanIK retargeting), face shapes and parts, on fixtures; native retopology and UV tools headless.

**Not verified yet** (each has a test or a decision point):
- Anything in the Maya GUI: panel docking and restore, menus and shelf, the composer over the viewport, the Attribute Editor hook, undo in the GUI, secure plug-in loading prompt, keychain prompts between Maya and `mayapy`, UI scaling, sky dome and splat display in the viewport.
- Maya 2025 and 2026, Windows and Linux, Maya Creative.
- A full browser OAuth round trip from a desktop app; device code registration.
- The contents of Scenario's real GLB and FBX outputs (compression, texture formats, rigs, blend shape names, vertex order) and what Scenario's conversions keep; the apply modes on real results and on meshes above 100,000 vertices; the triangulation-tolerant matcher (to build).
- Rebinding over an existing skin; face shapes from a head-only result onto a combined body mesh; the abort path inside an apply's undo chunk.
- Which mesh formats each edit model accepts beyond GLB.
- Arnold renders with a licence; Viewport 2.0 captures with the ACES view on lit scenes.
- Provenance attributes through FBX and USD export; project-relative texture paths after save.
- Whether a free plug-in that needs an account passes Autodesk Marketplace review.
