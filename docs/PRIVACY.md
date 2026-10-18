# Privacy: Scenario for Maya

Status: **draft, 2026-10-18**, written with the spec before any code. It describes what the plug-in will do; every statement is checked against the built plug-in before release.

Scenario for Maya connects Autodesk Maya to the Scenario platform. This page says what leaves your computer, when, where it goes, and what stays on your machine. Scenario's own handling of the data it receives follows Scenario's Terms of Service, Privacy Policy and [Trust Portal](https://trust.scenario.com) [links to confirm before release].

## What is sent to Scenario, and when

Nothing is sent before you sign in. After that, the plug-in sends data to Scenario (`mcp.scenario.com`, `api.cloud.scenario.com` and Scenario's file storage) only for these actions:

| Action | What is sent |
|---|---|
| Opening the panel | Requests for the model catalog, your teams and projects, and your project's credit balance |
| Editing a form | The form's content (model, prompt, settings, the ids of files already uploaded) for a free price check, about 0.7 s after you stop typing |
| Generate, Run workflow, Approve (Prompt Spark) | The same form, as a paid request |
| Adding a reference (image file, viewport or camera capture, playblast, selected meshes) | The file, uploaded to your Scenario project when you add it to a form |
| Mesh edits | An export of the meshes you selected: geometry, UVs, normals, materials and their textures, and the skin and skeleton when the task needs them. Node and material names are replaced by neutral names by default; the mapping stays on your computer |
| Jobs, results, library | Requests for job status, result files, your project's history and library |

Not sent: the rest of your scene, file paths, node names (unless you turn off neutral names), your Maya project contents, or anything from other open scenes.

Signed storage transfers use the link's own authorization; they do not carry your Scenario credentials.

## Agents

The plug-in can run a local server for AI agents (Claude Code, Codex, Cursor, Claude Desktop and others). It listens only on your own computer (`127.0.0.1`) and asks for a token that the plug-in writes into the agent's settings when you press Connect.

What an agent reads through it (scene summaries, node details, screenshots, job results) goes to that agent's own model provider, under your agreement with that provider, not to Scenario. Agents cannot change your scene unless you turn on **Allow agents to change this scene**, and cannot run Python unless you also turn on **Allow agents to run Python**. These switches are not a sandbox: once on, an agent acts with your rights in Maya. Connect only agents you trust with those actions.

Every agent call that spends credits or changes the scene is listed in the Agents activity log.

## What is stored on your computer

| Item | Where |
|---|---|
| Sign-in token or API secret, agent server token | Your operating system's credential store (macOS Keychain, Windows Credential Manager, Linux Secret Service). If none is available, a file readable only by your user account, and the plug-in tells you so |
| Settings, model catalog cache, job ledger, logs | `<Maya user folder>/scenario/` |
| Downloaded results, captures and mesh exports | Your Maya project, in `scenario/`, `sourceimages/scenario/`, `sound/scenario/`, `movies/scenario/` and `images/scenario/` |
| Provenance (model, prompt, cost, job and asset ids) | Attributes on the nodes the plug-in creates or edits, saved inside your `.ma` or `.mb` file |

Secrets are never written into scenes, Maya preferences (`userPrefs.mel`), `Maya.env`, project files or logs. If you put credentials in `Maya.env` yourself, the plug-in warns you that it is a plain text file.

Provenance travels with your scene file: anyone you send the scene to can read the prompts and ids stored on its nodes. A project setting leaves prompts out.

## Other network requests

- **Update check**: once a day the plug-in asks GitHub for the latest release number. No account or scene data is sent. You can turn it off.
- **Usage data**: off by default. The plug-in asks once. If you agree, it sends anonymous events (plug-in and Maya versions, OS, which features were used, error types) to Scenario; never prompts, files, scene content or credentials. The list of fields is published in the docs before the feature is turned on.

## Your controls

- **Sign out** removes the token from your credential store and asks Scenario to revoke it.
- **API keys** can be revoked at any time from your team page on [app.scenario.com](https://app.scenario.com/team).
- **Offline mode** (`SCENARIO_MAYA_OFFLINE=1`) stops all network access from the plug-in.
- **No spending** (`SCENARIO_NO_SPEND=1`) refuses every paid request and upload from the plug-in.
- **Uninstall** removes the plug-in; ticking "Also remove my Scenario data in Maya" also removes the settings, ledger and stored credentials.

## Contact

Security issues: see [SECURITY.md](../SECURITY.md). Other questions: Scenario support [contact to confirm before release].
