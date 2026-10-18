# Support

Scenario for Maya is an open-source Maya plug-in maintained by Scenario. This
page says where to look and whom to ask.

## Using the plug-in

- Start with the [README](README.md) and the [docs](docs/) folder: what the
  plug-in sends and stores is in [PRIVACY](docs/PRIVACY.md), and the design is
  in the [specification](docs/spec/SPEC.md). The local Scenario MCP server for
  agents is described in both.
- For models, Creative Units and account settings, see the
  [Scenario Knowledge Base](https://help.scenario.com).
- For release changes, read the [changelog](CHANGELOG.md) and the
  [releases](https://github.com/scenario-labs/maya-plugin/releases);
  the open [Bug issues](https://github.com/scenario-labs/maya-plugin/issues?q=is%3Aissue%20is%3Aopen%20type%3ABug) list current limitations.

## Bugs, change requests and questions

Use the [issue chooser](https://github.com/scenario-labs/maya-plugin/issues/new/choose).
Search the [existing issues](https://github.com/scenario-labs/maya-plugin/issues)
first. For a question, open a blank issue with a title starting with "Question:".

Before filing a bug, collect:

- The Maya version (Help > About Maya, for example "2027.2") and your operating
  system.
- The plug-in version from Windows > Settings/Preferences > Plug-in Manager
  (scenario_for_maya) or Scenario > Help > About Scenario for Maya, and whether
  you installed it from a GitHub release ZIP, a studio deployment on a shared
  module path or a source checkout.
- The lane or workflow, model and steps to reproduce, what you expected and
  what happened.
- Relevant lines from the Script Editor or from
  `<MAYA_APP_DIR>/scenario/logs/scenario.log`, and the output of Scenario >
  Help > Copy Diagnostics. It copies versions, paths and state without secrets;
  check the paths for your username before you paste it.

Public issues and attachments are visible to everyone. Never include an API
key, an API secret, an OAuth or agent token, a signed download URL or
confidential project files.

## Account, billing, credits, API keys and security

Keep these matters out of public issues. Write to
[support@scenario.com](mailto:support@scenario.com) or use in-app support at
[app.scenario.com](https://app.scenario.com). Report security vulnerabilities as
described in [SECURITY.md](SECURITY.md).

## What to expect

Plugin issues are handled on a best-effort basis, without a response-time
commitment. Support for your Scenario account or subscription goes through the
Scenario channels above.
