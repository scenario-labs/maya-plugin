"""Scenario for Maya: the Scenario platform inside Autodesk Maya.

The package has four layers:

- ``core``: no Maya import. Scenario client, sign-in, credentials, quotes, job
  ledger, schema forms, catalog. Unit-tested with plain Python.
- ``maya``: the Maya side. Main-thread dispatcher, actions, importers, apply modes.
- ``ui``: PySide6 panel, Studio and dialogs.
- ``agent``: the local MCP server for agents.
"""

__version__ = "0.1.0"
