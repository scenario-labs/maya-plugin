"""Scripted checks inside a real Maya GUI session (spec 13, layer 3). 0 CU: reads only.

Run by ``tools/test_maya_gui.sh``, which starts Maya with a throwaway prefs
folder and sets:
  SCENARIO_GUI_STAGE  install | restart | oauth
  SCENARIO_GUI_OUT    folder for results.json, screenshots and the log
  SCENARIO_GUI_REPO   repository root
Each stage drives Maya with a small step runner on a QTimer, so Maya's event
loop (and the plug-in's dispatcher) keeps running between steps. A watcher
records and screenshots every modal dialog Maya shows (for example a secure
plug-in loading prompt) and answers it the way a user installing the plug-in
would. Maya quits at the end of each stage.
"""

import faulthandler
import importlib
import importlib.util
import json
import os
import subprocess
import time
import traceback

from maya import cmds
from PySide6 import QtCore, QtWidgets

STAGE = os.environ["SCENARIO_GUI_STAGE"]
OUT = os.environ["SCENARIO_GUI_OUT"]
REPO = os.environ["SCENARIO_GUI_REPO"]
APP_DIR = os.environ["MAYA_APP_DIR"]
PLUGIN = "scenario_for_maya"
CONTROL = "ScenarioPanelWorkspaceControl"
results = {"stage": STAGE, "maya": cmds.about(version=True), "checks": [], "modals": [], "started": time.time()}
_secret = {"value": ""}
_seen_modals = set()
_quit = {"requested": 0.0, "dump": None}


def record(name, ok, detail=""):
    results["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:800]})
    print(f"[scenario-gui] {'PASS' if ok else 'FAIL'} {name} {detail}")


def save():
    results["finished"] = time.time()
    with open(os.path.join(OUT, f"results_{STAGE}.json"), "w") as handle:
        json.dump(results, handle, indent=1)


def main_window():
    from maya import OpenMayaUI as omui1
    from shiboken6 import wrapInstance

    return wrapInstance(int(omui1.MQtUtil.mainWindow()), QtWidgets.QWidget)


def shot(name, widget=None):
    widget = widget or main_window()
    path = os.path.join(OUT, f"{STAGE}_{name}.png")
    widget.grab().save(path)
    return path


def fresh(name):
    return importlib.import_module(name)


def test_secret():
    if not _secret["value"]:
        spec = importlib.util.spec_from_file_location("scn_test_credentials", os.path.join(REPO, "tools", "test_credentials.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _secret["key"], _secret["value"] = module.load()
    return _secret.get("key", ""), _secret["value"]


def files_containing(text, root):
    hits = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            try:
                with open(path, "rb") as handle:
                    if text.encode() in handle.read():
                        hits.append(os.path.relpath(path, root))
            except OSError:
                pass
    return hits


def keychain_has(account):
    return subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "Scenario for Maya", "-a", account], capture_output=True).returncode == 0


# -- modal watcher -----------------------------------------------------------

ALLOW_WORDS = ("Allow", "Allow All", "Load", "Load Once", "Trust", "Yes", "OK", "Continue")


def watch_modals():
    app = QtWidgets.QApplication.instance()
    modal = app.activeModalWidget()
    if modal is None:
        return
    from shiboken6 import getCppPointer

    identity = int(getCppPointer(modal)[0])  # Python wrappers change; the C++ object does not
    if identity in _seen_modals:
        return
    _seen_modals.add(identity)
    texts = [label.text() for label in modal.findChildren(QtWidgets.QLabel) if label.text()]
    buttons = [button.text() for button in modal.findChildren(QtWidgets.QAbstractButton) if button.isVisible()]
    index = len(results["modals"]) + 1
    entry = {"title": modal.windowTitle(), "class": type(modal).__name__, "texts": texts[:12], "buttons": buttons, "screenshot": shot(f"modal{index}", modal), "answered": ""}
    if _quit["requested"]:
        entry["after_checks"] = f"{time.time() - _quit['requested']:.1f} s after the quit request"
    results["modals"].append(entry)
    print(f"[scenario-gui] modal: {entry['title']!r} {texts[:3]} {buttons}")
    if type(modal).__name__ == "WorkspaceDialog":
        pick_test_project(modal)
        entry["answered"] = "picked test project"
        return
    for word in ALLOW_WORDS:
        for button in modal.findChildren(QtWidgets.QAbstractButton):
            if button.isVisible() and button.text().replace("&", "") == word:
                entry["answered"] = word
                QtCore.QTimer.singleShot(400, button.click)
                if _quit["requested"]:
                    save()
                return
    if _quit["requested"]:
        save()


def pick_test_project(dialog):
    for t in range(dialog.team_box.count()):
        dialog.team_box.setCurrentIndex(t)
        for p in range(dialog.project_box.count()):
            if dialog.project_box.itemText(p) == "Maya Plugin Tests":
                dialog.project_box.setCurrentIndex(p)
                QtCore.QTimer.singleShot(400, dialog.accept)
                return
    QtCore.QTimer.singleShot(400, dialog.reject)


# -- step runner -------------------------------------------------------------


class Runner:
    """Runs a generator of steps. ``yield 1.5`` waits; ``yield (predicate, timeout)`` waits for a condition."""

    def __init__(self, steps):
        self.steps = steps
        self.wait_until = 0.0
        self.predicate = None
        self.deadline = 0.0
        self.timer = QtCore.QTimer()
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.watcher = QtCore.QTimer()
        self.watcher.setInterval(250)
        self.watcher.timeout.connect(watch_modals)

    def start(self):
        self.watcher.start()
        self.timer.start()

    def tick(self):
        now = time.time()
        if now < self.wait_until:
            return
        if self.predicate is not None:
            try:
                done = bool(self.predicate())
            except Exception:  # noqa: BLE001
                done = False
            if not done and now < self.deadline:
                return
            if not done:
                record("wait timed out", False, getattr(self.predicate, "__name__", "condition"))
            self.predicate = None
        try:
            step = next(self.steps)
        except StopIteration:
            self.finish()
            return
        except Exception:  # noqa: BLE001
            record("stage crashed", False, traceback.format_exc())
            self.finish()
            return
        if isinstance(step, tuple):
            self.predicate, timeout = step
            self.deadline = now + timeout
        else:
            self.wait_until = now + float(step or 0)

    def finish(self):
        self.timer.stop()
        save()
        print("[scenario-gui] stage done; quitting Maya")
        try:
            cmds.savePrefs(general=True, plugins=True, uiLayout=True)
        except Exception:  # noqa: BLE001
            record("save prefs", False, traceback.format_exc())
            save()
        # The modal watcher keeps running: a dialog Maya shows while quitting would
        # otherwise wait forever. If Maya is still alive 20 s later, every Python
        # thread's stack and the open windows go to quit_<stage>.txt.
        _quit["requested"] = time.time()
        _quit["dump"] = open(os.path.join(OUT, f"quit_{STAGE}.txt"), "w")
        faulthandler.dump_traceback_later(20, file=_quit["dump"])
        QtCore.QTimer.singleShot(10000, describe_windows)
        QtCore.QTimer.singleShot(500, lambda: cmds.quit(force=True))


def describe_windows():
    app = QtWidgets.QApplication.instance()
    lines = [f"still running {time.time() - _quit['requested']:.1f} s after the quit request", f"active modal: {app.activeModalWidget()!r}"]
    for widget in app.topLevelWidgets():
        if widget.isVisible():
            lines.append(f"window: {type(widget).__name__} {widget.objectName()!r} {widget.windowTitle()!r}")
    _quit["dump"].write("\n".join(lines) + "\n\n")
    _quit["dump"].flush()


# -- stages ------------------------------------------------------------------


def panel_module():
    return fresh("scenario_maya.ui.panel")


def runtime_now():
    return fresh("scenario_maya.maya.runtime").current()


def stage_install():
    yield 3.0
    shot("before_install")
    spec = importlib.util.spec_from_file_location("install_scenario", os.path.join(REPO, "ScenarioForMaya", "scripts", "install_scenario.py"))
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    started = time.time()
    try:
        installer.onMayaDroppedPythonFile()
        record("install by drop handler", True, f"{time.time() - started:.1f} s")
    except Exception:  # noqa: BLE001
        record("install by drop handler", False, traceback.format_exc())
        return
    yield 2.0
    loaded_from = cmds.pluginInfo(PLUGIN, query=True, path=True) if cmds.pluginInfo(PLUGIN, query=True, loaded=True) else ""
    record("plug-in loaded from the modules folder", loaded_from.startswith(os.path.join(APP_DIR, "modules")), loaded_from)
    record("autoload on", cmds.pluginInfo(PLUGIN, query=True, autoload=True))
    record("panel exists", panel_module().current() is not None)
    record("panel docked", cmds.workspaceControl(CONTROL, exists=True) and not cmds.workspaceControl(CONTROL, query=True, floating=True))
    record("panel tab in front", cmds.workspaceControl(CONTROL, query=True, visible=True))
    items = [cmds.menuItem(item, query=True, label=True) for item in (cmds.menu("ScenarioMainMenu", query=True, itemArray=True) or []) if not cmds.menuItem(item, query=True, divider=True)]
    record("Scenario menu", items[:3] == ["Scenario Panel", "Jobs", "Import GLB..."] and "Sign In..." in items, items)
    record("runtime commands", all(cmds.runTimeCommand(n, exists=True) for n in ("ScenarioOpenPanel", "ScenarioShowJobs")))
    shot("panel_after_install")
    shot("panel_signin_page", panel_module().current())

    key, secret = test_secret()
    record("test key available", bool(key and secret), key[:8] + "..." if key else "none")
    if not secret:
        return
    signin = fresh("scenario_maya.ui.signin")
    panel = panel_module().current()
    dialog = signin.ApiKeyDialog(runtime_now(), panel)
    dialog.show()
    dialog.key.setText(key[:8] + "..." + key[-4:])  # the screenshot never shows the full key id
    dialog.secret.setText(secret)
    yield 0.5
    shot("api_key_dialog", dialog)
    dialog.key.setText(key)
    started = time.time()
    dialog._submit()
    yield (lambda: dialog.result() == QtWidgets.QDialog.DialogCode.Accepted or dialog.buttons.isEnabled()), 60
    record("API key sign-in (live, free)", dialog.result() == QtWidgets.QDialog.DialogCode.Accepted, f"{time.time() - started:.1f} s; {dialog.status.text()}")
    if dialog.result() != QtWidgets.QDialog.DialogCode.Accepted:
        shot("api_key_error", dialog)
        return
    panel.signin._done()
    yield (lambda: "/" in panel.workspace_button.text()), 30
    record("workspace shown", "Maya Plugin Tests" in panel.workspace_button.text(), panel.workspace_button.text())
    yield 1.0
    shot("panel_signed_in", panel)
    shot("main_signed_in")
    runtime = runtime_now()
    status = runtime.session.status()
    record("credential store is the Keychain", status["credential_store"] == "macOS Keychain", status["credential_store"])
    record("secret stored in Keychain", keychain_has(f"api_secret:{key}"))
    diag = fresh("scenario_maya.core.diagnostics").report(runtime.session, runtime.dispatcher)
    with open(os.path.join(OUT, "install_diagnostics.txt"), "w") as handle:
        handle.write(diag)
    record("diagnostics without secret", secret not in diag)
    # The 16 ms budget is for polling and downloads (checked in the generate stage); a
    # reaction to a click only has to stay under the 100 ms people notice.
    name, took = runtime.dispatcher.longest_call
    record(
        "sign-in reactions under 100 ms on the main thread",
        runtime.dispatcher.longest_slice_ms < 100.0,
        f"{runtime.dispatcher.longest_slice_ms:.1f} ms over {runtime.dispatcher.slices}; slowest {name} {took:.1f} ms",
    )


def stage_restart():
    yield (lambda: cmds.pluginInfo(PLUGIN, query=True, loaded=True)), 60
    record("plug-in autoloaded at startup", cmds.pluginInfo(PLUGIN, query=True, loaded=True))
    yield (lambda: panel_module().current() is not None), 30
    panel = panel_module().current()
    record("panel restored with the layout", panel is not None)
    record("panel docked after restart", cmds.workspaceControl(CONTROL, exists=True) and not cmds.workspaceControl(CONTROL, query=True, floating=True))
    yield 2.0
    shot("main_after_restart")
    runtime = runtime_now()
    record("still signed in from the Keychain", runtime is not None and runtime.session.signed_in, runtime.session.status()["method"] if runtime else "")
    if panel is not None:
        shot("panel_after_restart", panel)
    key, secret = test_secret()
    if secret:
        hits = files_containing(secret, APP_DIR)
        record("secret absent from Maya prefs and scenario folder", not hits, hits)
    if runtime is None or not runtime.session.signed_in:
        return
    done = []
    runtime.background(runtime.session.sign_out, on_done=lambda _r: done.append(True), on_error=lambda e: done.append(e))
    yield (lambda: done), 30
    record("sign out", done == [True], done)
    record("secret removed from Keychain", not keychain_has(f"api_secret:{key}"))
    yield 1.0
    if panel is not None:
        record("sign-in page after sign out", panel.pages.currentWidget() is panel.signin)
        shot("panel_signed_out", panel)


def stage_oauth():
    yield (lambda: panel_module().current() is not None and runtime_now() is not None), 60
    panel = panel_module().current()
    runtime = runtime_now()
    if runtime.session.signed_in:
        record("starts signed out", False, runtime.session.status()["method"])
        return
    started = time.time()
    panel.signin.sign_in_browser()
    yield 1.0
    shot("oauth_waiting", panel)
    yield (lambda: runtime.session.signed_in), 300
    record("browser sign-in (OAuth PKCE, live)", runtime.session.signed_in, f"{time.time() - started:.0f} s")
    if not runtime.session.signed_in:
        panel.signin.cancel()
        return
    yield (lambda: runtime.session.settings.get("project_id")), 120
    status = runtime.session.status()
    record("workspace chosen", bool(status["project"]["id"]), f"{status['team']['name']} / {status['project']['name']}")
    found = []
    runtime.background(lambda: runtime.session.backend().models(limit=5), on_done=lambda r: found.append(len(r[0])), on_error=lambda e: found.append(str(e)))
    yield (lambda: found), 60
    record("catalog read with the OAuth token and workspace", found and isinstance(found[0], int) and found[0] > 0, found)
    yield 1.0
    shot("oauth_signed_in", panel)
    record("refresh token in Keychain", keychain_has("oauth_refresh_token"))
    done = []
    runtime.background(runtime.session.sign_out, on_done=lambda _r: done.append(True), on_error=lambda e: done.append(e))
    yield (lambda: done), 30
    record("sign out revokes and forgets", done == [True] and not keychain_has("oauth_refresh_token"), done)


def viewport_shot(name):
    """Viewport 2.0 through a playblast (a widget grab of the Metal viewport is noise)."""
    path = os.path.join(OUT, f"{STAGE}_{name}")
    cmds.refresh(force=True)
    return cmds.playblast(
        frame=[cmds.currentTime(query=True)],
        format="image",
        compression="png",
        completeFilename=path + ".png",
        viewer=False,
        showOrnaments=False,
        widthHeight=(960, 540),
        percent=100,
        forceOverwrite=True,
    )


def card_button(card, text):
    for index in range(card.actions.count()):
        widget = card.actions.itemAt(index).widget()
        if widget is not None and widget.text() == text:
            return widget
    return None


def stage_generate():
    """One live generation with a cheap model (paid), clicked through the panel."""
    yield (lambda: panel_module().current() is not None and runtime_now() is not None and runtime_now().session.signed_in), 60
    panel = panel_module().current()
    runtime = runtime_now()
    lane = panel.lane
    record("panel opens on the Image lane", lane.lane.id == "image", lane.model_name.text())
    yield (lambda: lane.generate_button.isEnabled()), 60
    record("price on the button", lane.generate_button.text().startswith("Generate . "), lane.generate_button.text())
    shot("panel_priced", panel)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    project = os.path.join(OUT, "project")  # never the project the copied prefs last opened
    os.makedirs(project, exist_ok=True)
    cmds.workspace(project, openWorkspace=True)
    yield (lambda: lane.generate_button.isEnabled()), 30
    before = set(lane.cards)
    runtime.dispatcher.reset_timing()
    started = time.time()
    lane.generate_button.click()
    yield (lambda: any(card.row.get("state") in ("ready", "failed", "download_failed", "uncertain") for key, card in lane.cards.items() if key not in before)), 300
    card = next((card for key, card in lane.cards.items() if key not in before), None)
    state = card.row.get("state") if card else "no card"
    record("generation ready in Maya", state == "ready", f"{time.time() - started:.1f} s from the click; {state}; {card.note.text() if card else ''}")
    name, took = runtime.dispatcher.longest_call
    record(
        "main-thread slices under 16 ms while polling and downloading",
        runtime.dispatcher.longest_slice_ms < 16.0,
        f"{runtime.dispatcher.longest_slice_ms:.1f} ms over {runtime.dispatcher.slices}; slowest {name} {took:.1f} ms",
    )
    if state != "ready":
        shot("panel_failed", panel)
        return
    row = card.row
    record("charged as quoted", row.get("charged_exact") == row.get("cost_exact"), f"quoted {row.get('cost_exact')}, charged {row.get('charged_exact')}")
    path = row["result"]["files"][0]["path"]
    record("file in the project's sourceimages/scenario", os.sep + os.path.join("sourceimages", "scenario") + os.sep in path, os.path.basename(path))
    yield 1.5
    shot("panel_result", panel)
    card_button(card, "Card").click()
    yield 0.5
    cards = cmds.ls("*.scenario_asset_id", recursive=True, objectsOnly=True) or []
    record("Card lands with provenance", bool(cards), cards[:3])
    landed_step = cmds.undoInfo(query=True, undoName=True)
    viewport_shot("viewport_card")
    shot_step = cmds.undoInfo(query=True, undoName=True)
    cmds.undo()
    left = cmds.ls("*.scenario_asset_id", recursive=True, objectsOnly=True) or []
    record("one undo removes the card", not left, f"undo step after landing {landed_step!r}, after the playblast {shot_step!r}; left {left[:3]}")
    cube = cmds.polyCube(name="userCrate")[0]
    cmds.select(cube)
    card_button(card, "Material").click()
    yield 0.5
    shape = cmds.listRelatives(cube, shapes=True)[0]
    engine = (cmds.listConnections(shape, type="shadingEngine") or [""])[0]
    record("Material on the selected mesh", engine.startswith("scn_"), engine)
    card_button(card, "Image plane").click()
    yield 0.5
    planes = cmds.ls(type="imagePlane") or []
    record("Image plane on the camera", bool(planes), planes)
    cmds.viewFit(cube)
    viewport_shot("viewport_material_and_plane")
    shot("panel_after_landing", panel)


STAGES = {"install": stage_install, "generate": stage_generate, "restart": stage_restart, "oauth": stage_oauth}
os.makedirs(OUT, exist_ok=True)
_runner = Runner(STAGES[STAGE]())
# runpy drops this module's namespace when it returns: keep the runner alive.
import builtins  # noqa: E402

builtins.__scenario_gui_runner__ = _runner
QtCore.QTimer.singleShot(1500, _runner.start)
