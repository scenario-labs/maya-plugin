# Security Policy

## Reporting a vulnerability

Do not report security vulnerabilities through public GitHub issues or pull
requests. Public reports can expose other users before a fix is available, and
copies may remain accessible after deletion.

Report privately through any of these channels:

- [Open a private vulnerability report](https://github.com/scenario-labs/maya-plugin/security/advisories/new)
  from this repository's Security tab.
- Email [support@scenario.com](mailto:support@scenario.com) with "security" in the subject.
- Use in-app support at [app.scenario.com](https://app.scenario.com).

Include the affected surface (the Maya plug-in, its local agent server, or the
Scenario platform), the Maya and plug-in versions, your operating system,
reproduction steps and the impact you observe. The plug-in version is
`__version__` in `ScenarioForMaya/scripts/scenario_maya/__init__.py`; it is
shown in Windows > Settings/Preferences > Plug-in Manager (scenario_for_maya)
and in Scenario > Help > About Scenario for Maya. Use synthetic credentials and
minimal sample scenes where possible. Scenario support routes reports to the
appropriate team and follows up through the same private channel.

## Scope

This repository ships Scenario for Maya, an Autodesk Maya plug-in for Maya
2025, 2026 and 2027, written in pure Python. It signs in to Scenario with
OAuth or an API key and secret, calls the Scenario MCP server at
`mcp.scenario.com`, downloads generated files into the current Maya project,
lands them in the scene or applies them to your meshes as undoable commands,
and runs a local MCP server so agents can drive Maya. Relevant reports
include:

- Unexpected exposure of tokens, keys or secrets in the scene (`fileInfo`, node
  attributes, provenance), Maya preferences (`userPrefs.mel`, optionVars),
  `<MAYA_APP_DIR>/scenario/settings.json`, the project's `scenario.json`, logs,
  error messages, or network requests to hosts other than Scenario's. Secrets
  belong in the macOS Keychain, Windows Credential Manager or Linux Secret
  Service, or, where none exists, in an owner-only file,
  `<MAYA_APP_DIR>/scenario/credentials.json`; `SCENARIO_API_KEY` and
  `SCENARIO_API_SECRET` are read from the environment when set.
- The local agent server (`127.0.0.1:9878` by default, or the next of nine
  ports), including the headless server started with
  `mayapy -m scenario_maya.serve`: requests accepted without the bearer token
  (on by default), from a non-loopback Host, from a web page Origin, or that
  reach another interface; any use of Maya's `commandPort`; actions an agent
  can run beyond what the "allow scene changes" and "allow Python" switches in
  Scenario Preferences and Studio > Connection > Agents permit.
- Paid requests sent twice, sent without a matching single-use quote, or sent
  while `SCENARIO_NO_SPEND=1` is set. Agents spend automatically with a
  single-use quote from the plug-in, without an approval prompt.
- Unsafe downloads, uploads or imports of images, 3D models, audio, video or
  other generated content, including files written outside the project's
  `scenario/`, `sourceimages/scenario/`, `sound/scenario/`, `movies/scenario/`
  and `images/scenario/captures/` folders, or credentials sent to hosts other
  than Scenario's.
- Files the "Connect a client" buttons write into agent configurations (Claude
  Code, Codex, Cursor, Claude Desktop) outside the documented entries.
- The repository's CI and release supply chain: how the release ZIP is built
  and published, and what it contains, including `install_scenario.py`.

Platform vulnerabilities involving `app.scenario.com`, `api.cloud.scenario.com`
or `mcp.scenario.com` use the same private channels above, not this
repository's public issue tracker.

## Supported versions

Security fixes target the [latest release](https://github.com/scenario-labs/maya-plugin/releases).
Report suspected vulnerabilities promptly even if you cannot update or
reproduce them on the latest version. Older releases have no support branch.

## Secrets in issues and pull requests

API keys and secrets, OAuth tokens, the agent server token and signed asset
URLs are credentials. Never commit them or paste them into public issues or
pull requests. Check screenshots, Script Editor and log excerpts, Copy
Diagnostics output (it leaves secrets out but includes paths) and sample scenes
before sharing them. If a secret is already exposed, report it privately
instead of pointing to it in a public issue, revoke the key in Scenario, and
replace the agent token in Studio > Connection > Agents.
