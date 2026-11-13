# Privacy: Scenario for Maya

Scenario for Maya connects Autodesk Maya to the Scenario platform. This page
says what leaves your computer, when, where it goes, and what stays on your
machine. Scenario's own handling of the data it receives follows Scenario's
Terms of Service and Privacy Policy, and its [Trust Portal](https://trust.scenario.com).

## What is sent to Scenario, and when

Nothing is sent before you sign in. After that, the plug-in talks to Scenario
(`api.cloud.scenario.com`, `clerk.scenario.com` for sign-in, and Scenario's
file storage) only for these actions:

| Action | What is sent |
|---|---|
| Opening the panel, the picker or the workspace menu | Requests for the model catalog and your teams and projects |
| Editing a request | The request (model, prompt, settings, the ids of files already sent) for a free price check, 0.7 s after you stop typing |
| Generate | The same request, as a paid request |
| Adding an image (a file, a viewport capture, views captured around an object) | The picture, uploaded to your Scenario project when you add it |
| Use selection, for a mesh edit or a character to animate | The selected meshes as one GLB: geometry, UVs, normals and base colour textures. Object, material, scene and path names are replaced by neutral names |
| Jobs and results | Requests for the status of your jobs and their result files |

Not sent: the rest of your scene, file paths, node names, your Maya project's
contents, or anything from other open scenes.

Result files are downloaded through signed links from Scenario's storage,
which carry their own authorization, never your Scenario credentials.

## What is stored on your computer

| Item | Where |
|---|---|
| Sign-in token or API secret | Your operating system's credential store (macOS Keychain, Windows Credential Manager, Secret Service on Linux). If none is available, a file readable only by your user account |
| Settings, model catalog cache, job list, logs | `scenario/` in Maya's user folder (`MAYA_APP_DIR`) |
| Results, captures and the meshes sent for an edit | Your Maya project, in `scenario/`, `sourceimages/scenario/` and `images/scenario/` |
| Provenance (model, prompt, price, job and asset ids) | Attributes on the nodes the plug-in creates, saved inside your `.ma` or `.mb` file |

Secrets are never written into scenes, Maya preferences, `Maya.env`, project
files, settings or logs.

Provenance travels with your scene file: anyone you send the scene to can
read the prompts and ids stored on its nodes. Setting `store_prompts_on_nodes`
to `false` in `settings.json` leaves the prompts out.

The plug-in sends nothing else: no usage data, no update check.

## Your controls

- **Sign out** asks Scenario to revoke the session and removes the secret
  from your credential store.
- **API keys** can be revoked at any time from your team page on
  [app.scenario.com](https://app.scenario.com/team).
- **Offline mode** (`SCENARIO_MAYA_OFFLINE=1`) stops all network access from
  the plug-in; importing a local GLB still works.
- **No spending** (`SCENARIO_NO_SPEND=1`) refuses every paid request from the
  plug-in.
- **Uninstall** (in Maya's Script Editor, Python:
  `import install_scenario; install_scenario.uninstall()`) removes the
  plug-in and keeps your settings, job list and results; delete `scenario/` in Maya's user
  folder to remove them, and sign out first to remove the stored secret.

## Contact

Security issues: see [SECURITY.md](../SECURITY.md). Other questions:
support@scenario.com.
