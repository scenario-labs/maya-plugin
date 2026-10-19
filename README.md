# Scenario for Maya

Every Scenario model inside Autodesk Maya, for artists and for agents.

Scenario for Maya is a Maya plug-in for Maya 2025, 2026 and 2027 on macOS,
Windows and Linux. It prices and runs Scenario's image, video, 3D, material,
audio and environment models from a dockable panel, lands the results in the
open scene, and applies 3D edits (remesh, UV unwrap, retexture, rig, animate,
split into parts) to your own meshes as undoable steps. Agents such as Claude
Code, Codex or Cursor drive the same actions through a local Scenario MCP
server inside Maya.

**Status:** in development, not released. In place: sign-in (browser,
another device or API key), the Scenario panel, the job list and its crash
recovery, the installer, and the Image lane (generate, download, land as a
card, a material or an image plane). The other lanes, 3D edits and the agent
server follow. Tested on Maya 2027.2 on macOS.

## Install from a checkout

1. Clone this repository.
2. Drag `ScenarioForMaya/scripts/install_scenario.py` onto a Maya viewport. It
   copies the module into your Maya modules folder, loads the plug-in, turns
   on autoload and opens the Scenario panel. No restart and no `userSetup.py`
   edit.
3. Maya 2027 asks whether to load a plug-in from a location it does not trust
   yet. Choose **Allow**; tick "Apply to all plugins in this location" to stop
   it asking again.

For development, point Maya at the checkout instead of copying it. Either run
this once in the Script Editor (Python), which links the checkout, loads the
plug-in and turns on autoload; run it again to reload after a change:

```python
import sys

sys.path.insert(0, "/path/to/maya-plugin/ScenarioForMaya/scripts")
import install_scenario

install_scenario.install(link=True)
```

or set `MAYA_MODULE_PATH=/path/to/maya-plugin` (the repository's
`ScenarioForMaya.mod` uses a relative path) and load `scenario_for_maya` in
Windows > Settings/Preferences > Plug-in Manager.

## Generate an image

The panel opens on the Image lane with a fast, low-cost model and a starter
prompt. The Generate button shows the exact price once Scenario has checked
it (free); one click sends the request. The result card then offers **Card**
(a textured plane facing the camera), **Material** (on the selected meshes or
faces) and **Image plane** (on the current camera). One Ctrl+Z removes what
was added. Files go to `sourceimages/scenario/` in the current Maya project.

## Sign in

Open the Scenario panel (Scenario > Scenario Panel) and choose **Sign in with
Scenario**: your browser opens, you approve, and Maya picks up the session.
"Sign in on another device" shows a code to enter on any device; "Use an API
key" takes a key and secret from Scenario's web app. Secrets go to the system
keychain (macOS Keychain, Windows Credential Manager or Secret Service), never
to the scene or Maya's preferences. For scripts and CI, `SCENARIO_API_KEY` and
`SCENARIO_API_SECRET` are read from the environment.

Nothing is sent to Scenario until you press Generate or allow an agent to.
What the plug-in sends and stores is in [docs/PRIVACY.md](docs/PRIVACY.md).

## More

- Design and decisions: [docs/spec/SPEC.md](docs/spec/SPEC.md)
- Contributing and the repository rules: [CONTRIBUTING.md](CONTRIBUTING.md), [AGENTS.md](AGENTS.md)
- Help: [SUPPORT.md](SUPPORT.md); security reports: [SECURITY.md](SECURITY.md)
- License: [MIT](LICENSE)
