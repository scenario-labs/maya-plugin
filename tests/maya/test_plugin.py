"""Plug-in lifecycle, main-thread dispatch, recovery and sign-in inside mayapy (0 CU)."""

import os
import subprocess
import sys
import threading

from tests.fake_backend import API_KEY, API_SECRET
from tests.maya.conftest import MODULE, PLUGIN, ROOT, fresh, pump_until


def test_load_and_unload(cmds, plugin):
    assert cmds.pluginInfo(PLUGIN, query=True, loaded=True)
    assert cmds.pluginInfo(PLUGIN, query=True, version=True) == fresh("scenario_maya").__version__
    runtime = fresh("scenario_maya.maya.runtime").get()
    assert runtime.gui is False
    assert not cmds.menu("ScenarioMainMenu", exists=True), "no UI in batch"
    assert "Maya 2027" in fresh("scenario_maya.core.http").user_agent()
    cmds.unloadPlugin(PLUGIN)
    assert not any(name == "scenario_maya" or name.startswith("scenario_maya.") for name in sys.modules)


def test_reload_imports_fresh_code(cmds, plugin):
    first = fresh("scenario_maya.maya.runtime")
    cmds.unloadPlugin(PLUGIN)
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    second = fresh("scenario_maya.maya.runtime")
    assert first is not second and second.current() is not None


def test_worker_reaches_the_scene_only_through_the_main_thread(cmds, plugin):
    runtime = fresh("scenario_maya.maya.runtime").get()
    seen = {}

    def on_main():
        seen["main"] = threading.current_thread() is threading.main_thread()
        return cmds.polyCube(name="scnDispatchCube")[0]

    worker = runtime.dispatcher.run_in_worker(lambda: runtime.dispatcher.call_on_main(on_main).result(timeout=10))
    pump_until(worker.done)
    assert worker.result() == "scnDispatchCube" and seen["main"]
    assert runtime.dispatcher.longest_slice_ms < 1000


def test_background_delivers_results_on_the_main_thread(plugin):
    runtime = fresh("scenario_maya.maya.runtime").get()
    delivered = []
    runtime.background(lambda: 41 + 1, on_done=lambda value: delivered.append((value, threading.current_thread() is threading.main_thread())))
    runtime.background(lambda: 1 / 0, on_error=lambda error: delivered.append((type(error).__name__, threading.current_thread() is threading.main_thread())))
    pump_until(lambda: len(delivered) == 2)
    assert sorted(delivered, key=str) == sorted([(42, True), ("ZeroDivisionError", True)], key=str)


def test_load_recovers_a_request_cut_off_by_a_crash(cmds, private_home):
    from scenario_maya.core.ledger import Ledger

    crashed = Ledger(session_id="crashed-maya")
    row = crashed.prepare(kind="model", target_id="m", workspace="w", payload_hash="h", params={}, cost_exact="5")
    crashed.claim(row["local_id"])
    crashed.close()
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    try:
        runtime = fresh("scenario_maya.maya.runtime").get()
        assert runtime.recovered["not_confirmed"] == [row["local_id"]]
        assert runtime.ledger.get(row["local_id"])["state"] == "uncertain"
    finally:
        cmds.unloadPlugin(PLUGIN)


def test_api_key_sign_in_through_the_runtime(fake, monkeypatch, cmds):
    monkeypatch.setenv("SCENARIO_MCP_URL", fake.endpoint)
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    try:
        runtime = fresh("scenario_maya.maya.runtime").get()
        events = []
        runtime.subscribe(lambda event, data: events.append((event, threading.current_thread() is threading.main_thread())))
        runtime.background(lambda: runtime.session.sign_in_api_key(API_KEY, API_SECRET))
        pump_until(lambda: ("signed_in", True) in events)
        assert runtime.session.status()["project"]["name"] == "Test project"
        assert not fake.state.paid_runs()
    finally:
        cmds.unloadPlugin(PLUGIN)


def test_runtime_commands_are_defaults_tied_to_the_plugin(cmds, plugin):
    commands = fresh("scenario_maya.ui.commands")
    commands.install()
    commands.install()  # a second load leaves the existing default commands alone
    assert cmds.runTimeCommand("ScenarioOpenPanel", query=True, category=True) == "Scenario"
    assert cmds.runTimeCommand("ScenarioOpenPanel", query=True, plugin=True) == PLUGIN
    assert cmds.runTimeCommand("ScenarioOpenPanel", query=True, default=True)


def test_installer_copies_upgrades_and_uninstalls(cmds, tmp_path, scripts_on_path):
    import importlib

    installer = importlib.import_module("install_scenario")
    app_dir = str(tmp_path / "maya_app")
    copied = installer.install(source=MODULE, app_dir=app_dir, load=False)
    dest = os.path.join(app_dir, "modules", "ScenarioForMaya")
    assert not any("__pycache__" in parts for parts, _dirs, _files in os.walk(dest)), "caches are not copied"
    first = installer.install(source=MODULE, app_dir=app_dir, open_panel=False)
    assert not copied["previous"] and first["previous"] and first["version"] == copied["version"]
    assert first["module"] == os.path.realpath(dest) or first["module"] == dest
    assert open(first["mod_file"]).read().strip() == f"+ ScenarioForMaya {first['version']} {first['module']}"
    assert os.path.realpath(cmds.pluginInfo(PLUGIN, query=True, path=True)).startswith(os.path.realpath(dest))
    second = installer.install(source=MODULE, app_dir=app_dir, open_panel=False)
    assert second["previous"] and os.path.isdir(second["previous"])
    removed = installer.uninstall(app_dir=app_dir)
    assert not cmds.pluginInfo(PLUGIN, query=True, loaded=True)
    assert not os.path.exists(dest) and not os.path.exists(first["mod_file"]) and len(removed) == 3


def test_upgrade_while_an_import_is_in_the_undo_queue_asks_for_a_restart(cmds, tmp_path, scripts_on_path):
    import importlib

    from tests import glb_samples

    installer = importlib.import_module("install_scenario")
    app_dir = str(tmp_path / "maya_app")
    installer.install(source=MODULE, app_dir=app_dir, open_panel=False)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    fresh("scenario_maya.maya.landing").land_model(glb_samples.textured_quad(str(tmp_path / "crate.glb")), {}, texture_folder=str(tmp_path / "tex"))
    again = installer.install(source=MODULE, app_dir=app_dir, open_panel=False)
    assert again["restart_needed"] and cmds.pluginInfo(PLUGIN, query=True, loaded=True), "files replaced, old version stays loaded"
    assert os.path.isdir(os.path.join(app_dir, "modules", "ScenarioForMaya"))
    cmds.flushUndo()
    cmds.file(new=True, force=True)
    installer.uninstall(app_dir=app_dir)
    assert not cmds.pluginInfo(PLUGIN, query=True, loaded=True)


def test_repository_module_file_resolves_relative_path(tmp_path):
    """A fresh mayapy finds the module through the relative path in ScenarioForMaya.mod."""
    env = dict(os.environ, MAYA_MODULE_PATH=ROOT, MAYA_APP_DIR=str(tmp_path / "app"), MAYA_DISABLE_CER="1")
    code = (
        "import maya.standalone; maya.standalone.initialize(name='python'); from maya import cmds; "
        "print('PATH=' + cmds.moduleInfo(path=True, moduleName='ScenarioForMaya')); "
        "cmds.loadPlugin('scenario_for_maya'); print('LOADED=' + str(cmds.pluginInfo('scenario_for_maya', q=True, loaded=True))); "
        "import sys, os; sys.stdout.flush(); os._exit(0)"
    )
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=240)
    assert f"PATH={MODULE}\n" in result.stdout, result.stdout + result.stderr[-2000:]
    assert "LOADED=True" in result.stdout
