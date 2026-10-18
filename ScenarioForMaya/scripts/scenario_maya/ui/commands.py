"""Runtime commands (Hotkey Editor, category "Scenario").

They are ``default`` commands, so Maya never saves them to the user's
preferences, and tied to the plug-in, so a hotkey loads it on first use.
Maya refuses to delete or edit a default runtime command, so each one is
created once per Maya session and left in place on unload; its command is a
one-line import, so a reloaded plug-in runs the fresh code.
"""

from __future__ import annotations

from maya import cmds

PLUGIN = "scenario_for_maya"

COMMANDS = (
    ("ScenarioOpenPanel", "Open or focus the Scenario panel.", "import scenario_maya.ui.panel as _scn; _scn.show()"),
    ("ScenarioShowJobs", "Show Scenario jobs in the Scenario panel.", "import scenario_maya.ui.panel as _scn; _scn.show(page='jobs')"),
)


def install() -> None:
    for name, annotation, command in COMMANDS:
        if not cmds.runTimeCommand(name, exists=True):
            cmds.runTimeCommand(name, default=True, annotation=annotation, category="Scenario", command=command, commandLanguage="python", plugin=PLUGIN)
