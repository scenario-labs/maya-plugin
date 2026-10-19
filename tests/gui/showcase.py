"""README media from a real Maya GUI session: screenshots, a recorded 3D generation and a turntable.

Run by ``tools/readme_media.sh``, which starts Maya with a signed-in throwaway
prefs folder and sets ``SCENARIO_SHOW_OUT`` and ``SCENARIO_SHOW_REPO``. Spends
one cheap image and one 3D generation (Meshy 7.1, game polycount) in the
project named ``SCENARIO_SHOW_PROJECT`` (default "Maya Plugin Tests"). The
team and project names are replaced by a neutral label in every capture.
Frames are written as they are taken; the shell script turns them into videos
and GIFs once Maya has quit.

A widget grab of Maya's Metal viewport is noise, so every full-window frame is
the window grab with a playblast of the viewport painted over it.
"""

import importlib
import json
import os
import pwd
import sys
import time
import traceback

from maya import OpenMayaUI as omui1
from maya import cmds, mel
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import wrapInstance

OUT = os.environ["SCENARIO_SHOW_OUT"]
REPO = os.environ["SCENARIO_SHOW_REPO"]
PROJECT = os.environ.get("SCENARIO_SHOW_PROJECT", "Maya Plugin Tests")
MASK = "My Team / My Project  ▾"
SHOTS = os.path.join(OUT, "shots")
FRAMES = os.path.join(OUT, "frames")
TURN = os.path.join(OUT, "turntable")
IMAGE_PROMPT = "a mossy stone well, stylized, hand-painted"
MODEL_PROMPT = "weathered brass ship lantern, game prop"
MESHY = "model_meshy-7-1-txt23d"
STAGE = os.environ.get("SCENARIO_SHOW_STAGE", "all")  # "turntable": rebuild the turntable only, 0 CU
WIDTH = 1600  # full-window frames are scaled to this width
results = {"checks": [], "shots": {}, "frames": [], "modals": [], "started": time.time()}


def record(name, ok, detail=""):
    results["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:600]})
    print(f"[scenario-show] {'PASS' if ok else 'FAIL'} {name} {detail}")


def save():
    results["finished"] = time.time()
    with open(os.path.join(OUT, "showcase.json"), "w") as handle:
        json.dump(results, handle, indent=1)


def panel_module():
    return importlib.import_module("scenario_maya.ui.panel")


def runtime_now():
    return importlib.import_module("scenario_maya.maya.runtime").current()


def main_window():
    return wrapInstance(int(omui1.MQtUtil.mainWindow()), QtWidgets.QWidget)


# -- capture -------------------------------------------------------------------


ACCOUNT_WORDS = tuple(word for word in (pwd.getpwuid(os.getuid()).pw_gecos or "").split() if len(word) >= 3)


def mask():
    """Neutral labels for the Scenario workspace and for the account name in Maya's status line."""
    panel = panel_module().current()
    if panel is not None and panel.workspace_button.text() != MASK:
        panel.workspace_button.setText(MASK)
    if not ACCOUNT_WORDS:
        return
    for kind in (QtWidgets.QAbstractButton, QtWidgets.QLabel):
        for widget in main_window().findChildren(kind):
            text = widget.text()
            if text and text.startswith(ACCOUNT_WORDS):
                widget.setText("Artist")
                results.setdefault("masked", []).append(type(widget).__name__)


def view_panel():
    for name in cmds.getPanel(visiblePanels=True) or []:
        if cmds.getPanel(typeOf=name) == "modelPanel":
            return name
    return "modelPanel4"


def view_camera():
    return cmds.modelPanel(view_panel(), query=True, camera=True)


def view_widget():
    view = omui1.M3dView()
    omui1.M3dView.getM3dViewFromModelPanel(view_panel(), view)
    return wrapInstance(int(view.widget()), QtWidgets.QWidget)


def view_rect():
    widget = view_widget()
    return QtCore.QRect(widget.mapTo(main_window(), QtCore.QPoint(0, 0)), widget.size())


def playblast(path, ornaments=True):
    """The viewport at its on-screen size in physical pixels, as JPG: a PNG playblast has a transparent background."""
    rect = view_rect()
    ratio = main_window().devicePixelRatioF()
    made = cmds.playblast(
        frame=[cmds.currentTime(query=True)],
        format="image",
        compression="jpg",
        quality=100,
        completeFilename=path,
        viewer=False,
        showOrnaments=ornaments,
        widthHeight=(int(rect.width() * ratio), int(rect.height() * ratio)),
        percent=100,
        forceOverwrite=True,
        offScreen=True,
    )
    return made or path


_view = {"image": None}


def refresh_view():
    """Playblasts the viewport and keeps it for the following frames (the viewport only changes when the script changes it)."""
    cmds.refresh(force=True)
    _view["image"] = QtGui.QImage(playblast(os.path.join(OUT, "view_cache.jpg")))


def window_image():
    mask()
    pixmap = main_window().grab()
    image = _view["image"]
    if image is not None and not image.isNull():
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QtCore.QRectF(view_rect()), image)
        painter.end()
    return pixmap.toImage().scaledToWidth(WIDTH, QtCore.Qt.TransformationMode.SmoothTransformation)


def shot_window(name):
    path = os.path.join(SHOTS, f"{name}.png")
    window_image().save(path)
    results["shots"][name] = path
    return path


def shot_widget(name, widget):
    mask()
    path = os.path.join(SHOTS, f"{name}.png")
    widget.grab().save(path)
    results["shots"][name] = path
    return path


class Recorder:
    """Full-window frames on a timer; each frame carries its phase so the video can speed up waits."""

    def __init__(self):
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.take)
        self.phase = ""
        self.busy = False

    def run(self, phase, interval):
        self.phase = phase
        self.timer.start(int(interval * 1000))

    def stop(self):
        self.timer.stop()

    def take(self):
        if self.busy:
            return
        self.busy = True
        try:
            path = os.path.join(FRAMES, f"f{len(results['frames']):05d}.jpg")
            window_image().save(path, "JPG", 90)
            results["frames"].append({"path": path, "t": time.time(), "phase": self.phase})
        except Exception:  # noqa: BLE001
            record("frame capture", False, traceback.format_exc())
            self.stop()
        finally:
            self.busy = False


recorder = Recorder()


def watch_modals():
    """Any dialog that opens on its own is recorded and closed, so the session never waits on it."""
    modal = QtWidgets.QApplication.instance().activeModalWidget()
    if modal is None or modal.property("scenario_show_seen"):
        return
    modal.setProperty("scenario_show_seen", True)
    texts = [label.text() for label in modal.findChildren(QtWidgets.QLabel) if label.text()]
    results["modals"].append({"title": modal.windowTitle(), "class": type(modal).__name__, "texts": texts[:6]})
    print(f"[scenario-show] modal: {modal.windowTitle()!r} {texts[:3]}")
    if hasattr(modal, "reject"):
        modal.reject()


# -- helpers ------------------------------------------------------------------


def card_button(card, text):
    for index in range(card.actions.count()):
        widget = card.actions.itemAt(index).widget()
        if widget is not None and widget.text() == text:
            return widget
    return None


def new_card(lane, before):
    return next((card for key, card in lane.cards.items() if key not in before), None)


def finished(card):
    return card is not None and card.row.get("state") in ("ready", "failed", "download_failed", "uncertain")


def priced(lane):
    return lane.generate_button.isEnabled() and lane.generate_button.text().startswith("Generate")


def landed_tops():
    return cmds.ls("*.scenario_job_id", recursive=True, objectsOnly=True) or []


def fit(nodes, factor):
    cmds.select(nodes)
    cmds.viewFit(view_camera(), fitFactor=factor)
    cmds.select(clear=True)


def check_undo(label):
    """One Ctrl+Z right after a landing removes all of it and redo restores it. Nothing is done in
    between: a playblast or a selection change is an undo step of its own."""
    name = cmds.undoInfo(query=True, undoName=True) or ""
    landed = landed_tops()
    cmds.undo()
    left = landed_tops()
    cmds.redo()
    back = landed_tops()
    ok = name.startswith("Scenario:") and bool(landed) and not left and sorted(back) == sorted(landed)
    record(f"one undo removes the {label}, redo restores it (GUI)", ok, f"next undo {name!r}; {len(landed)} nodes, {len(left)} after undo, {len(back)} after redo")


def light_rig():
    """A key and a fill light in place of the viewport's default headlight."""
    key = cmds.directionalLight(name="key_light", intensity=1.3)
    cmds.setAttr(cmds.listRelatives(key, parent=True)[0] + ".rotate", -42, 38, 0, type="double3")
    try:
        cmds.setAttr(key + ".useDepthMapShadows", 1)
    except RuntimeError:
        pass
    cmds.ambientLight(name="fill_light", intensity=0.4)
    cmds.modelEditor(view_panel(), edit=True, displayLights="all", shadows=True)


def style_viewport():
    panel = view_panel()
    cmds.modelEditor(panel, edit=True, displayAppearance="smoothShaded", displayTextures=True, grid=True, wireframeOnShaded=False, headsUpDisplay=False)
    for attr, value in (("multiSampleEnable", 1), ("multiSampleCount", 8), ("ssaoEnable", 1), ("ssaoAmount", 0.7)):
        try:
            cmds.setAttr(f"hardwareRenderingGlobals.{attr}", value)
        except RuntimeError:
            pass
    cmds.grid(size=300, spacing=50, divisions=5)


def find_workspace(runtime):
    """The team and project named PROJECT, read on a worker (no ids in this file)."""
    backend = runtime.session.backend()
    for team in backend.teams():
        team_id = team.get("id") or team.get("teamId") or ""
        for project in backend.projects(team_id):
            if project.get("name") == PROJECT:
                return team_id, project.get("id") or "", team.get("name") or "", project.get("name") or ""
    return None


def hero_and_turntable(runtime, top, shots):
    """The new lantern beside an earlier 3D result, framed (hero shots), then a turntable."""
    tops = [top]
    earlier = [
        row
        for row in runtime.ledger.list(limit=40)
        if (row.get("origin") or {}).get("lane") == "3d"
        and row["state"] in ("ready", "applied")
        and (row.get("params") or {}).get("prompt") != MODEL_PROMPT  # an earlier run's lantern is not a second model
    ]
    for row in earlier[:1]:
        try:
            made = runtime.jobs.land(row["local_id"], "model", select=False)
            box = cmds.exactWorldBoundingBox(top)
            other = cmds.exactWorldBoundingBox(made["meshes"])
            cmds.move((box[3] - other[0]) + 25, 0, (box[2] + box[5]) / 2 - (other[2] + other[5]) / 2, made["top"], relative=True, worldSpace=True)
            tops.append(made["top"])
        except Exception:  # noqa: BLE001
            record("second model", False, traceback.format_exc())
    camera = view_camera()
    cmds.setAttr(camera + ".rotate", -14, 32, 0, type="double3")
    fit(tops, 0.75)
    if shots:
        refresh_view()
        yield 1.0
        shot_window("hero")
        playblast(os.path.join(SHOTS, "hero_viewport.jpg"), ornaments=False)

    # The models turn, the camera stays: the hero framing is kept.
    spin = cmds.group(tops, name="turntable")
    box = cmds.exactWorldBoundingBox(spin)
    cmds.xform(spin, worldSpace=True, pivots=((box[0] + box[3]) / 2.0, box[1], (box[2] + box[5]) / 2.0))
    cmds.setKeyframe(spin, attribute="rotateY", time=1, value=0)
    cmds.setKeyframe(spin, attribute="rotateY", time=97, value=360)
    cmds.keyTangent(spin, attribute="rotateY", inTangentType="linear", outTangentType="linear")
    cmds.playbackOptions(minTime=1, maxTime=96)
    cmds.select(clear=True)  # group selects the new group, and a selection draws as a wireframe
    os.makedirs(TURN, exist_ok=True)
    for frame in range(1, 97):
        cmds.currentTime(frame)
        playblast(os.path.join(TURN, f"t{frame:04d}.jpg"), ornaments=False)
        if frame % 12 == 0:
            yield 0.0
    record("turntable frames", True, "96 frames")


def turntable_again(runtime, panel):
    """Stage ``turntable``: the turntable from an earlier capture's lantern, without generating (0 CU)."""
    cmds.file(new=True, force=True)
    style_viewport()
    yield 3.0
    light_rig()
    panel.select_lane("3d")
    rows = runtime.ledger.list(limit=40)
    lantern = next((row for row in rows if (row.get("params") or {}).get("prompt") == MODEL_PROMPT and row["state"] in ("ready", "applied")), None)
    if lantern is None:
        record("a lantern from an earlier capture", False, "none in the ledger")
        return
    top = runtime.jobs.land(lantern["local_id"], "model", select=False)["top"]
    yield 1.0
    yield from hero_and_turntable(runtime, top, shots=False)


# -- the session --------------------------------------------------------------


def steps():
    sys.path.insert(0, os.path.join(REPO, "ScenarioForMaya", "scripts"))
    import install_scenario

    install_scenario.install(link=True)
    yield (lambda: runtime_now() is not None and runtime_now().session.signed_in), 60
    runtime = runtime_now()
    main = main_window()
    main.showNormal()
    screen = main.screen().availableGeometry()
    main.setGeometry(screen.x(), screen.y(), min(1600, screen.width()), min(1000, screen.height()))
    mel.eval('setNamedPanelLayout "Single Perspective View"')
    project = os.path.join(OUT, "project")
    os.makedirs(project, exist_ok=True)
    cmds.workspace(project, openWorkspace=True)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    style_viewport()
    yield 3.0  # Maya finishes a new scene on idle; an undo step made before then can be lost

    found = []
    runtime.background(lambda: find_workspace(runtime), on_done=found.append, on_error=found.append)
    yield (lambda: found), 120
    if found and isinstance(found[0], tuple):
        runtime.session.set_workspace(*found[0])
        record("workspace is the test project", True)
    else:
        record("workspace is the test project", False, f"kept the saved workspace: {found[:1]}")
    panel = panel_module().show()
    yield 2.0
    cmds.workspaceControl(panel_module().CONTROL, edit=True, resizeWidth=440)
    panel = panel_module().current()
    panel.refresh()
    yield 1.0
    if STAGE == "turntable":
        yield from turntable_again(runtime, panel)
        return

    # Sign-in page, as a first-time user sees it (signed out, no workspace).
    panel.workspace_button.hide()
    panel.pages.setCurrentWidget(panel.signin)
    yield 0.5
    shot_widget("panel_signin", panel)
    panel.workspace_button.show()
    panel.pages.setCurrentWidget(panel.home)
    yield 0.5

    # Image lane: price, generate, land as a card (one undo removes it) and as a material.
    panel.select_lane("image")
    lane = panel.lane
    lane.prompt.setPlainText(IMAGE_PROMPT)
    refresh_view()
    yield (lambda: priced(lane)), 60
    yield 1.0
    shot_widget("panel_image_priced", panel)
    recorder.run("image", 0.5)
    before = set(lane.cards)
    lane.generate_button.click()
    yield (lambda: new_card(lane, before) is not None), 60
    recorder.run("image_wait", 1.0)
    yield (lambda: finished(new_card(lane, before))), 300
    card = new_card(lane, before)
    record("image ready", card is not None and card.row.get("state") == "ready", card and card.row.get("state"))
    if card is None or card.row.get("state") != "ready":
        return
    recorder.run("image", 0.5)
    yield 2.0
    shot_widget("panel_image_ready", panel)
    card_button(card, "Card").click()
    yield 1.0  # the panel's own events run, as after a person's click
    check_undo("card")
    refresh_view()
    yield 1.5
    shot_window("image_card")
    cmds.delete([node for node in landed_tops() if cmds.objectType(node) == "transform"])
    crate = cmds.polyCube(name="crate", width=60, height=60, depth=60)[0]
    cmds.move(0, 30, 0, crate)
    cmds.select(crate)
    card_button(card, "Material").click()
    yield 0.5
    fit([crate], 0.55)
    refresh_view()
    yield 1.5
    shot_window("image_material")
    recorder.stop()

    # 3D lane: the picker, then one generation recorded from prompt to import.
    cmds.file(new=True, force=True)
    style_viewport()
    yield 3.0
    light_rig()
    panel.select_lane("3d")
    lane = panel.lane
    lane.set_model(MESHY)
    yield (lambda: lane.fields is not None), 60
    from scenario_maya.ui.picker import ModelPicker

    picker = ModelPicker(runtime, lane.lane, current=MESHY, parent=panel)
    picker.resize(760, 460)
    picker.show()
    yield (lambda: picker.list.count() > 3), 60
    yield 1.0
    shot_widget("picker_3d", picker)
    picker.close()
    lane.prompt.setPlainText("")
    refresh_view()
    recorder.run("model_type", 0.25)
    yield 1.0
    for index in range(len(MODEL_PROMPT)):
        lane.prompt.setPlainText(MODEL_PROMPT[: index + 1])
        lane.prompt.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        yield 0.06
    yield (lambda: priced(lane)), 60
    yield 1.5
    shot_widget("panel_3d_priced", panel)
    before = set(lane.cards)
    started = time.time()
    lane.generate_button.click()
    yield (lambda: new_card(lane, before) is not None), 60
    yield 1.0
    recorder.run("model_wait", 1.5)
    yield 25.0
    shot_widget("panel_3d_generating", panel)
    yield (lambda: finished(new_card(lane, before))), 900
    card = new_card(lane, before)
    state = card.row.get("state") if card is not None else None
    record("3D result ready (Meshy 7.1)", state == "ready", f"{time.time() - started:.0f} s from the click; {state}; {card and card.note.text()}")
    if state != "ready":
        recorder.stop()
        return
    record("charged as quoted", card.row.get("charged_exact") in (None, "", card.row.get("cost_exact")), f"{card.row.get('cost_exact')} / {card.row.get('charged_exact')}")
    yield (lambda: (card.row.get("result") or {}).get("thumbnail")), 30
    record("the card gets Scenario's preview after the download", bool((card.row.get("result") or {}).get("thumbnail")), f"{time.time() - started:.0f} s from the click")
    recorder.run("model_import", 0.25)
    yield 2.0
    shot_widget("panel_3d_ready", panel)
    card_button(card, "Import").click()
    yield 1.0
    check_undo("3D import")
    local_id = card.row["local_id"]
    top = ((runtime.ledger.get(local_id).get("result") or {}).get("landed") or [{}])[0].get("top") or ""
    record("lantern imported with provenance", bool(top) and cmds.objExists(top) and cmds.attributeQuery("scenario_job_id", node=top, exists=True), top)
    fit([top], 0.6)
    refresh_view()
    yield 3.0
    shot_widget("panel_3d_imported", panel)
    shot_window("model_imported")
    recorder.stop()

    yield from hero_and_turntable(runtime, top, shots=True)


class Runner:
    """Runs the step generator on a QTimer so Maya's event loop keeps running between steps."""

    def __init__(self, generator):
        self.steps = generator
        self.wait_until = 0.0
        self.predicate = None
        self.deadline = 0.0
        self.busy = False
        self.timer = QtCore.QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)

    def tick(self):
        if self.busy:
            return  # a step that pumps events must not re-enter the generator
        watch_modals()
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
        self.busy = True
        try:
            step = next(self.steps)
        except StopIteration:
            self.finish()
            return
        except Exception:  # noqa: BLE001
            record("showcase crashed", False, traceback.format_exc())
            self.finish()
            return
        finally:
            self.busy = False
        if isinstance(step, tuple):
            self.predicate, timeout = step
            self.deadline = now + timeout
        else:
            self.wait_until = time.time() + float(step or 0)

    def finish(self):
        self.timer.stop()
        recorder.stop()
        save()
        print("[scenario-show] done; quitting Maya")
        QtCore.QTimer.singleShot(1000, lambda: cmds.quit(force=True))


for folder in (SHOTS, FRAMES, TURN):
    os.makedirs(folder, exist_ok=True)
_runner = Runner(steps())
import builtins  # noqa: E402

builtins.__scenario_show_runner__ = _runner  # runpy drops this module's namespace when it returns
QtCore.QTimer.singleShot(3000, _runner.timer.start)
