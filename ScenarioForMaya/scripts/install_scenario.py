"""Install Scenario for Maya: drag this file onto a Maya viewport.

It copies the ``ScenarioForMaya`` module into your Maya modules folder (no
admin rights), writes ``ScenarioForMaya.mod`` next to it, loads the plug-in for
this session, turns on autoload and opens the Scenario panel. No restart and no
``userSetup.py`` edit. Running it again upgrades in place and keeps the
previous version as ``ScenarioForMaya.previous`` until the next upgrade.

From a script: ``install_scenario.install()``; ``uninstall()`` reverses it.
This file stands alone (the package is not on Maya's path yet when it runs).
"""

import os
import re
import shutil
import sys

MODULE = "ScenarioForMaya"
PLUGIN = "scenario_for_maya"


def find_source(start=None):
    """The ``ScenarioForMaya`` folder this installer came with."""
    here = os.path.dirname(os.path.realpath(start or __file__))
    for candidate in (os.path.join(here, MODULE), os.path.dirname(here), here):
        if os.path.isfile(os.path.join(candidate, "plug-ins", PLUGIN + ".py")) and os.path.isdir(os.path.join(candidate, "scripts", "scenario_maya")):
            return candidate
    raise RuntimeError("Could not find the ScenarioForMaya folder next to install_scenario.py. Unzip the whole download first.")


def read_version(source):
    with open(os.path.join(source, "scripts", "scenario_maya", "__init__.py"), encoding="utf-8") as handle:
        found = re.search(r'__version__\s*=\s*"([^"]+)"', handle.read())
    return found.group(1) if found else "0.0.0"


def modules_dir(app_dir=None):
    if not app_dir:
        from maya import cmds

        app_dir = cmds.internalVar(userAppDir=True)
    return os.path.join(app_dir, "modules")


def _prepend_env(name, value):
    parts = [p for p in os.environ.get(name, "").split(os.pathsep) if p]
    if value not in parts:
        os.environ[name] = os.pathsep.join([value] + parts)


def _unload():
    """Unloads the plug-in; False when Maya keeps it in use.

    Maya refuses while the undo queue holds one of the plug-in's import
    steps. The files can still be replaced; the new version loads at the
    next start.
    """
    from maya import cmds

    if cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        try:
            cmds.unloadPlugin(PLUGIN)
        except RuntimeError as error:
            if "in use" not in str(error):
                raise
            return False
    return True


def install(source=None, app_dir=None, load=True, open_panel=True, link=False):
    """Copies (or, with ``link``, points the module file at) ``source``. Returns what was done."""
    from maya import cmds

    source = os.path.realpath(source or find_source())
    modules = modules_dir(app_dir)
    os.makedirs(modules, exist_ok=True)
    dest = os.path.join(modules, MODULE)
    version = read_version(source)
    unloaded = _unload()
    previous = ""
    if link or os.path.realpath(dest) == source:
        target = source
    else:
        if os.path.isdir(dest):
            previous = dest + ".previous"
            if os.path.isdir(previous):
                shutil.rmtree(previous)
            os.replace(dest, previous)
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        target = dest
    mod_file = os.path.join(modules, MODULE + ".mod")
    with open(mod_file, "w", encoding="utf-8") as handle:
        handle.write(f"+ {MODULE} {version} {target}\n")

    scripts = os.path.join(target, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    _prepend_env("MAYA_PLUG_IN_PATH", os.path.join(target, "plug-ins"))
    icons = os.path.join(target, "icons")
    _prepend_env("XBMLANGPATH", os.path.join(icons, "%B") if sys.platform.startswith("linux") else icons)

    if load and not unloaded:
        cmds.pluginInfo(PLUGIN, edit=True, autoload=True)
        return {"version": version, "module": target, "mod_file": mod_file, "previous": previous, "linked": target == source and not os.path.realpath(dest) == source, "restart_needed": True}
    if load:
        cmds.loadPlugin(os.path.join(target, "plug-ins", PLUGIN + ".py"))
        cmds.pluginInfo(PLUGIN, edit=True, autoload=True)
        if open_panel and not cmds.about(batch=True):
            import scenario_maya.ui.panel as panel

            panel.show()
    return {"version": version, "module": target, "mod_file": mod_file, "previous": previous, "linked": target == source and not os.path.realpath(dest) == source}


def uninstall(app_dir=None):
    """Unloads the plug-in, turns autoload off and removes the module file and copied module.

    A module linked to a source checkout is never deleted, only unlinked. The
    job ledger, settings, downloads and stored credentials stay.
    """
    from maya import cmds

    modules = modules_dir(app_dir)
    _unload()
    try:
        cmds.pluginInfo(PLUGIN, edit=True, autoload=False)
    except RuntimeError:
        pass
    removed = []
    mod_file = os.path.join(modules, MODULE + ".mod")
    if os.path.isfile(mod_file):
        os.remove(mod_file)
        removed.append(mod_file)
    for folder in (os.path.join(modules, MODULE), os.path.join(modules, MODULE + ".previous")):
        if os.path.isdir(folder) and not os.path.islink(folder):
            shutil.rmtree(folder)
            removed.append(folder)
    return removed


def onMayaDroppedPythonFile(*_args):
    from maya.api import OpenMaya as om

    try:
        result = install()
    except Exception as error:
        om.MGlobal.displayError(f"Scenario for Maya was not installed: {error}")
        raise
    if result.get("restart_needed"):
        om.MGlobal.displayWarning(f"Scenario for Maya {result['version']} is installed. Restart Maya to use it: Scenario imports in the undo history keep the previous version in use until then.")
        return
    om.MGlobal.displayInfo(f"Scenario for Maya {result['version']} installed in {result['module']}. It loads automatically from now on.")
