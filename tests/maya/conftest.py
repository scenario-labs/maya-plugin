"""Maya-in-the-loop tests: run with ``tools/test_maya.sh`` (``mayapy``, headless, 0 CU).

Maya starts once per test run. Each test gets the shared private home from
``tests/conftest.py``; the plug-in is unloaded after every test so the next one
starts from a fresh import.
"""

import importlib
import os
import sys

import pytest

maya_standalone = pytest.importorskip("maya.standalone", reason="needs mayapy")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULE = os.path.join(ROOT, "ScenarioForMaya")
PLUGIN_PATH = os.path.join(MODULE, "plug-ins", "scenario_for_maya.py")
PLUGIN = "scenario_for_maya"


@pytest.fixture(scope="session", autouse=True)
def maya_session():
    maya_standalone.initialize(name="python")
    yield
    # uninitialize() is left to process exit: Maya 2027 can stall in it after Qt use.


@pytest.fixture
def cmds():
    from maya import cmds as maya_cmds

    return maya_cmds


@pytest.fixture
def plugin(cmds):
    """Loads the plug-in from the repository and unloads it afterwards."""
    cmds.loadPlugin(PLUGIN_PATH)
    yield fresh
    if cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN)


def fresh(name):
    """The current module object (the plug-in re-imports the package on every load)."""
    return importlib.import_module(name)


def pump_until(predicate, timeout=10.0):
    runtime = fresh("scenario_maya.maya.runtime").get()
    assert runtime.dispatcher.pump(until=predicate, timeout=timeout), "timed out pumping the main thread"


@pytest.fixture
def scripts_on_path():
    scripts = os.path.join(MODULE, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return scripts
