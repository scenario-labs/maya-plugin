"""The image rows of a lane (spec 4.2: Model, inputs, Prompt, Settings...).

Images come from a file, a capture of the viewport, or a result of the Image
tab. A file or a capture is sent to Scenario when it is added, which is the
explicit action spec 7.1 point 8 asks for; an Image result is already on
Scenario and is used as it is. The row fills the model's first image field
and offers as many images as that field takes (one for Tripo P2, four for
Meshy 7.1). ``ViewInputs`` is the Multi-view row: one slot per named view of
the model (front, left, back, right...), filled one by one or all at once by
capturing the selection from each side.
"""

from __future__ import annotations

import os

from ..core import lanes, uploads
from ..core.schema import Field, view_of
from .common import error_text, open_url
from .qt import QtCore, QtGui, QtWidgets, dpi

THUMB = 52
FILE_FILTER = "Images (*.png *.jpg *.jpeg *.webp)"


class ImageInputs(QtWidgets.QWidget):
    """``items`` hold ``{asset_id, name, path, source, state}``; ``changed`` fires when the usable images change."""

    changed = QtCore.Signal()

    def __init__(self, runtime, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.items: list = []
        self.field: Field | None = None
        self.title = QtWidgets.QLabel("Image")
        self.chips = QtWidgets.QHBoxLayout()
        self.chips.setSpacing(dpi(4))
        self.chips.addStretch(1)
        self.file_button = QtWidgets.QPushButton("File...")
        self.file_button.setToolTip("Add a PNG, JPEG or WebP image. It is sent to Scenario when you add it.")
        self.file_button.clicked.connect(self.choose_files)
        self.viewport_button = QtWidgets.QPushButton("Viewport")
        self.viewport_button.setToolTip("Capture the viewport you look through (no grid, no selection highlight) and send it to Scenario.")
        self.viewport_button.clicked.connect(self.capture_viewport)
        self.results_button = QtWidgets.QPushButton("Image results")
        self.results_button.setToolTip("Use an image generated in the Image tab. It is already on Scenario, so nothing is sent again.")
        self.results_menu = QtWidgets.QMenu(self.results_button)
        self.results_menu.aboutToShow.connect(self._fill_results)
        self.results_button.setMenu(self.results_menu)
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(dpi(4))
        buttons.addWidget(self.file_button)
        buttons.addWidget(self.viewport_button)
        buttons.addWidget(self.results_button)
        buttons.addStretch(1)
        self.note = QtWidgets.QLabel()
        self.note.setEnabled(False)  # Maya greys disabled labels: secondary text
        self.note.setWordWrap(True)
        self.note.hide()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpi(4))
        layout.addWidget(self.title)
        layout.addLayout(self.chips)
        layout.addLayout(buttons)
        layout.addWidget(self.note)
        self._refresh()

    # -- what the form reads ------------------------------------------------

    @property
    def limit(self) -> int:
        if self.field is None:
            return 0
        return (self.field.max_items or 4) if self.field.is_array else 1

    def set_field(self, field: Field | None) -> None:
        self.field = field
        self.setVisible(field is not None)
        if field is not None:
            self.title.setText("Image" if field.name in ("image", "images") else field.label)
        self._refresh()

    def asset_ids(self) -> list:
        ready = [item["asset_id"] for item in self.items if item["state"] == "ready"]
        return ready[: self.limit] if self.limit else ready  # no limit known before the model's form loads

    def busy(self) -> bool:
        return any(item["state"] == "uploading" for item in self.items)

    def described(self) -> list:
        """What the job records about its inputs (local only): asset id, name, local file."""
        return [{"asset_id": item["asset_id"], "name": item["name"], "path": item["path"], "source": item["source"]} for item in self.items if item["state"] == "ready"][: self.limit]

    def names(self) -> list:
        return [item["name"] for item in self.described()]

    # -- adding -------------------------------------------------------------

    def choose_files(self) -> None:
        from maya import cmds

        from ..maya import scene

        start = os.path.join(scene.project_root(), "sourceimages")
        chosen = cmds.fileDialog2(fileFilter=FILE_FILTER, dialogStyle=2, fileMode=4, caption="Add images", startingDirectory=start if os.path.isdir(start) else scene.project_root())
        for path in chosen or []:
            self.add_file(path)

    def capture_viewport(self) -> None:
        from ..maya import capture

        try:
            made = capture.capture_viewport()
        except Exception as error:  # noqa: BLE001 - Maya reports capture problems as RuntimeError
            self._say(f"The viewport could not be captured: {error}")
            return
        self.add_file(made["path"], source="viewport")

    def add_file(self, path: str, source: str = "file") -> None:
        """Adds a local image and sends it to Scenario on a worker."""
        if len(self.items) >= max(self.limit, 1) and self.limit:
            self._say(f"This model takes {self.limit} image{'s' if self.limit > 1 else ''}. Remove one first.")
            return
        item = {"asset_id": "", "name": os.path.basename(path), "path": path, "source": source, "state": "uploading"}
        self.items.append(item)
        self._refresh()
        session = self.runtime.session

        def done(result):
            if item not in self.items:
                return
            item.update(asset_id=result["asset_id"], state="ready")
            self._refresh()
            self.changed.emit()

        def failed(error):
            if item in self.items:
                self.items.remove(item)
            self._refresh()
            self._say(f"{item['name']} was not sent: {error_text(error)}")
            self.changed.emit()

        self.runtime.background(lambda: uploads.upload_file(session, path), on_done=done, on_error=failed)
        self.changed.emit()

    def add_asset(self, asset_id: str, name: str, path: str = "", source: str = "result") -> None:
        """An image already on Scenario (an Image result, a re-run): nothing is sent."""
        if any(item["asset_id"] == asset_id for item in self.items):
            return
        if self.limit and len(self.items) >= self.limit:
            self.items = self.items[: self.limit - 1]
        self.items.append({"asset_id": asset_id, "name": name or asset_id, "path": path, "source": source, "state": "ready"})
        self._refresh()
        self.changed.emit()

    def set_items(self, described: list) -> None:
        """Re-run: the inputs a job recorded, as they were."""
        self.items = [dict(entry, state="ready") for entry in described if str(entry.get("asset_id") or "").startswith("asset_")]
        self._refresh()
        self.changed.emit()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.items):
            self.items.pop(index)
            self._refresh()
            self.changed.emit()

    # -- drawing ------------------------------------------------------------

    def _say(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _refresh(self) -> None:
        while self.chips.count() > 1:
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, entry in enumerate(self.items):
            self.chips.insertWidget(index, self._chip(index, entry))
        full = bool(self.limit) and len(self.items) >= self.limit
        for button in (self.file_button, self.viewport_button):
            button.setEnabled(not full)
        uploading = [entry["name"] for entry in self.items if entry["state"] == "uploading"]
        extra = len(self.items) - self.limit if self.limit else 0
        if uploading:
            self._say("Sending " + ", ".join(uploading) + " to Scenario...")
        elif extra > 0:
            self._say(f"This model takes {self.limit} image{'s' if self.limit > 1 else ''}: only the first {'is' if self.limit == 1 else 'are'} used.")
        elif not self.items and self.field is not None:
            views = f" Up to {self.limit} views of the same object also work." if self.limit > 1 else ""
            self._say("One clear image of one object works best." + views)
        else:
            self._say("")

    def _chip(self, index: int, entry: dict) -> QtWidgets.QToolButton:
        chip = QtWidgets.QToolButton()
        chip.setAutoRaise(True)
        chip.setIconSize(QtCore.QSize(dpi(THUMB), dpi(THUMB)))
        chip.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        tip = entry["name"] + ("  (sending...)" if entry["state"] == "uploading" else "")
        chip.setToolTip(tip)
        chip.setText(entry["name"][:10])
        if entry.get("path") and os.path.exists(entry["path"]):
            self._load_icon(chip, entry["path"])
        else:
            chip.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        if entry["state"] == "uploading":
            chip.setEnabled(False)
        menu = QtWidgets.QMenu(chip)
        menu.addAction("Remove", lambda: self.remove(index))
        if entry.get("path"):
            menu.addAction("Show file", lambda: open_url(QtCore.QUrl.fromLocalFile(os.path.dirname(entry["path"])).toString()))
        chip.setMenu(menu)
        chip.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        return chip

    def _load_icon(self, chip: QtWidgets.QToolButton, path: str) -> None:
        load_thumbnail(self.runtime, chip, path)

    def _fill_results(self) -> None:
        fill_results_menu(self.results_menu, self.image_results(), self.use_result)

    def image_results(self) -> list:
        return image_results(self.runtime)

    def use_result(self, row: dict) -> None:
        item = row["result"]["files"][0]
        self.add_asset(item["asset_id"], os.path.basename(item.get("path") or "") or item["asset_id"], item.get("path") or "", source="result")


VIEW_LABELS = {"front": "Front", "left": "Left", "back": "Back", "right": "Right", "top": "Top", "bottom": "Bottom", "leftFront": "Left front", "rightFront": "Right front"}


class ViewInputs(QtWidgets.QWidget):
    """One slot per named view of a multi-view model; ``slots`` hold ``{asset_id, name, path, source, state}`` by view."""

    changed = QtCore.Signal()

    def __init__(self, runtime, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.fields: list = []
        self.slots: dict = {}
        self.capture_record: dict = {}  # where the last capture was taken (box, up axis), for Import
        self.title = QtWidgets.QLabel("Views")
        self.grid = QtWidgets.QGridLayout()
        self.grid.setSpacing(dpi(4))
        self.buttons: dict = {}
        self.capture_button = QtWidgets.QPushButton("Capture views")
        self.capture_button.setToolTip(
            "Render the selected objects from each side this model takes (front, left, back, right...) with temporary cameras, "
            "and send the images to Scenario. Nothing stays in the scene or the undo queue."
        )
        self.capture_button.clicked.connect(self.capture)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.capture_button)
        row.addStretch(1)
        self.note = QtWidgets.QLabel()
        self.note.setEnabled(False)  # Maya greys disabled labels: secondary text
        self.note.setWordWrap(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpi(4))
        layout.addWidget(self.title)
        layout.addLayout(self.grid)
        layout.addLayout(row)
        layout.addWidget(self.note)
        self.set_fields([])

    # -- what the form reads ------------------------------------------------

    def views(self) -> list:
        return [view_of(field.name) for field in self.fields]

    def values(self) -> dict:
        return {field.name: self.slots[view]["asset_id"] for field, view in zip(self.fields, self.views(), strict=True) if self._ready(view)}

    def busy(self) -> bool:
        return any(item["state"] == "uploading" for item in self.slots.values())

    def problem(self) -> str:
        """Why Generate cannot run yet, or ""."""
        if not self.fields:
            return ""
        for field, view in zip(self.fields, self.views(), strict=True):
            if field.required and not self._ready(view):
                return f"Add a {VIEW_LABELS[view].lower()} view"
        if len(self.fields) > 1 and sum(self._ready(view) for view in self.views()) < 2:
            return "Add one more view"
        return ""

    def described(self) -> list:
        """What the job records about its views (local only), for Re-run."""
        return [dict(self._public(self.slots[view]), view=view) for view in self.views() if self._ready(view)]

    def names(self) -> list:
        return [self.slots[view]["name"] for view in self.views() if self._ready(view)]

    def set_fields(self, fields: list) -> None:
        self.fields = list(fields)
        self.setVisible(True)
        self._refresh()

    # -- adding -------------------------------------------------------------

    def capture(self) -> None:
        from maya import cmds

        from ..maya import capture

        if not self.views():
            self._say("This model takes no named views. Pick a multi-view model, or use the Image mode.")
            return
        try:
            made = capture.capture_views(cmds.ls(selection=True, long=True, objectsOnly=True) or [], self.views())
        except Exception as error:  # noqa: BLE001 - Maya reports capture problems as RuntimeError
            self._say(f"The views could not be captured: {error}")
            return
        self.capture_record = {"box": made["box"], "up_axis": made["up_axis"], "name": made["name"]}
        for view, path in made["views"].items():
            self.add_file(view, path, source="capture")

    def choose_file(self, view: str) -> None:
        from maya import cmds

        from ..maya import scene

        start = os.path.join(scene.project_root(), "sourceimages")
        chosen = cmds.fileDialog2(fileFilter=FILE_FILTER, dialogStyle=2, fileMode=1, caption=f"{VIEW_LABELS[view]} view", startingDirectory=start if os.path.isdir(start) else scene.project_root())
        if chosen:
            self.add_file(view, chosen[0])

    def add_file(self, view: str, path: str, source: str = "file") -> None:
        """Puts a local image in a view's slot and sends it to Scenario on a worker."""
        item = {"asset_id": "", "name": os.path.basename(path), "path": path, "source": source, "state": "uploading"}
        self.slots[view] = item
        self._refresh()
        session = self.runtime.session

        def done(result):
            if self.slots.get(view) is not item:
                return
            item.update(asset_id=result["asset_id"], state="ready")
            self._refresh()
            self.changed.emit()

        def failed(error):
            if self.slots.get(view) is item:
                self.slots.pop(view)
            self._refresh()
            self._say(f"{item['name']} was not sent: {error_text(error)}")
            self.changed.emit()

        self.runtime.background(lambda: uploads.upload_file(session, path), on_done=done, on_error=failed)
        self.changed.emit()

    def add_asset(self, view: str, asset_id: str, name: str, path: str = "", source: str = "result") -> None:
        """An image already on Scenario (an Image result, a re-run): nothing is sent."""
        self.slots[view] = {"asset_id": asset_id, "name": name or asset_id, "path": path, "source": source, "state": "ready"}
        self._refresh()
        self.changed.emit()

    def set_items(self, described: list) -> None:
        """Re-run: the views a job recorded, as they were."""
        self.slots = {entry["view"]: self._public(entry) | {"state": "ready"} for entry in described if entry.get("view") and str(entry.get("asset_id") or "").startswith("asset_")}
        self._refresh()
        self.changed.emit()

    def clear(self, view: str) -> None:
        if self.slots.pop(view, None) is not None:
            self._refresh()
            self.changed.emit()

    # -- drawing ------------------------------------------------------------

    def _ready(self, view: str) -> bool:
        return (self.slots.get(view) or {}).get("state") == "ready"

    @staticmethod
    def _public(entry: dict) -> dict:
        return {key: entry.get(key, "") for key in ("asset_id", "name", "path", "source")}

    def _say(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.buttons = {}
        for index, (field, view) in enumerate(zip(self.fields, self.views(), strict=True)):
            button = self._slot(field, view)
            self.buttons[view] = button
            self.grid.addWidget(button, index // 4, index % 4)
        self.capture_button.setEnabled(bool(self.fields) and not self.busy())
        uploading = [item["name"] for item in self.slots.values() if item["state"] == "uploading"]
        if uploading:
            self._say(f"Sending {len(uploading)} view{'s' if len(uploading) > 1 else ''} to Scenario...")
        elif not self.fields:
            self._say("This model takes no named views. Pick a multi-view model, or use the Image mode.")
        elif not any(self._ready(view) for view in self.views()):
            self._say("Select one object and press Capture views, or click a view to add an image.")
        else:
            self._say("")

    def _slot(self, field: Field, view: str) -> QtWidgets.QToolButton:
        entry = self.slots.get(view)
        slot = QtWidgets.QToolButton()
        slot.setIconSize(QtCore.QSize(dpi(THUMB), dpi(THUMB)))
        slot.setMinimumSize(dpi(THUMB + 8), dpi(THUMB + 22))
        slot.setText(VIEW_LABELS[view])
        slot.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        state = "" if entry is None else ("  (sending...)" if entry["state"] == "uploading" else f": {entry['name']}")
        slot.setToolTip(f"{VIEW_LABELS[view]} view{' (needed)' if field.required else ''}{state}")
        if entry is not None and entry.get("path") and os.path.exists(entry["path"]):
            load_thumbnail(self.runtime, slot, entry["path"])
        if entry is not None and entry["state"] == "uploading":
            slot.setEnabled(False)
        menu = QtWidgets.QMenu(slot)
        menu.addAction("File...", lambda: self.choose_file(view))
        results = menu.addMenu("Image results")
        results.aboutToShow.connect(lambda: fill_results_menu(results, image_results(self.runtime), lambda row: self.use_result(view, row)))
        if entry is not None:
            menu.addAction("Clear", lambda: self.clear(view))
        slot.setMenu(menu)
        slot.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        return slot

    def use_result(self, view: str, row: dict) -> None:
        item = row["result"]["files"][0]
        self.add_asset(view, item["asset_id"], os.path.basename(item.get("path") or "") or item["asset_id"], item.get("path") or "")


def load_thumbnail(runtime, button: QtWidgets.QToolButton, path: str) -> None:
    size = dpi(THUMB)

    def decode():  # QImage decodes off the main thread; the icon is made on it
        return QtGui.QImage(path).scaled(size, size, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)

    def show(image):
        if image.isNull():
            return
        try:
            button.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(image)))
        except RuntimeError:
            pass  # the button was replaced meanwhile

    runtime.background(decode, on_done=show)


def fill_results_menu(menu: QtWidgets.QMenu, rows: list, use) -> None:
    menu.clear()
    if not rows:
        action = menu.addAction("No Image results yet")
        action.setEnabled(False)
        return
    for row in rows:
        files = row["result"]["files"]
        label = str((row.get("params") or {}).get("prompt") or row.get("label") or files[0]["asset_id"])
        text = label if len(label) < 48 else label[:46] + "..."
        menu.addAction(text, lambda row=row: use(row))


def image_results(runtime) -> list:
    """Ready results of the Image tab in this workspace, newest first."""
    session = runtime.session
    if not session.signed_in:
        return []
    rows = runtime.ledger.list(limit=40, workspace=session.workspace())
    out = []
    for row in rows:
        files = (row.get("result") or {}).get("files") or []
        lane = lanes.BY_ID.get((row.get("origin") or {}).get("lane") or "", lanes.IMAGE)  # as the job runner reads it
        if lane.results == "image" and row.get("state") in ("ready", "applied", "apply_failed") and files and files[0].get("asset_id"):
            out.append(row)
    return out[:12]
