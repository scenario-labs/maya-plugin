"""The mesh row of the 3D tab's Edit selection mode (spec 4.2, 6.3), and the
character row of its Motion mode (6.5).

Edit selection: a task (Remesh, UV unwrap, Retexture) and the mesh it works
on. Use selection writes the selected mesh as a GLB (main thread, a fraction
of a second for a game mesh), checks it against the chosen model's limits,
and sends it to Scenario on a worker; that click is the explicit action spec
7.1 point 8 asks for. The same unchanged mesh gives the same bytes, so it is
not sent twice in a session. This version edits one mesh at a time.

Motion (``character=True``): no task; the selected meshes (a character is
often several) go as one GLB, and only to a model that takes a character.
"""

from __future__ import annotations

from ..core import edits, motion, uploads
from .common import error_text
from .qt import QtCore, QtWidgets, dpi


class MeshInput(QtWidgets.QWidget):
    """``item`` is ``{record, asset_id, state, name, problems}`` or None; ``changed`` fires when it changes."""

    changed = QtCore.Signal()
    task_changed = QtCore.Signal(str)

    def __init__(self, runtime, parent=None, *, character: bool = False) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.character = character
        self.item: dict | None = None
        self.model_id = ""
        self.model_name = ""
        self.takes_mesh = not character  # a Motion model takes a character when it has a 3D input
        self.task = edits.TASKS[0]

        self.task_label = QtWidgets.QLabel("Task")
        self.task_buttons = QtWidgets.QButtonGroup(self)
        self.task_buttons.setExclusive(True)
        self.task_button: dict = {}
        tasks = QtWidgets.QHBoxLayout()
        tasks.setSpacing(dpi(4))
        tasks.addWidget(self.task_label)
        for task in edits.TASKS:
            button = QtWidgets.QPushButton(task.label)
            button.setCheckable(True)
            button.setToolTip(task.hint)
            button.clicked.connect(lambda _=False, task_id=task.id: self.set_task(task_id, emit=True))
            self.task_buttons.addButton(button)
            self.task_button[task.id] = button
            tasks.addWidget(button)
        tasks.addStretch(1)

        self.title = QtWidgets.QLabel("Character" if character else "Mesh")
        self.mesh_line = QtWidgets.QLabel("Nothing captured yet.")
        self.mesh_line.setWordWrap(True)
        self.use_button = QtWidgets.QPushButton("Use selection")
        if character:
            self.use_button.setToolTip("Write the selected meshes as one GLB (neutral names, no scene paths) and send it to Scenario as the character to rig and animate.")
        else:
            self.use_button.setToolTip("Write the selected mesh as a GLB (neutral names, no scene paths) and send it to Scenario for this task.")
        self.use_button.clicked.connect(self.use_selection)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.mesh_line, 1)
        row.addWidget(self.use_button)
        self.note = QtWidgets.QLabel()
        self.note.setEnabled(False)  # Maya greys disabled labels: secondary text
        self.note.setWordWrap(True)
        self.note.hide()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpi(4))
        if character:
            self.task_label.hide()
            for button in self.task_button.values():
                button.hide()
        else:
            layout.addLayout(tasks)
        layout.addWidget(self.title)
        layout.addLayout(row)
        layout.addWidget(self.note)
        self.set_task(self.task.id)

    # -- what the page reads ---------------------------------------------------

    def asset_id(self) -> str:
        item = self.item
        return item["asset_id"] if item and item["state"] == "ready" and not item["problems"] else ""

    def busy(self) -> bool:
        return bool(self.item) and self.item["state"] == "uploading"

    def problems(self) -> list:
        return list(self.item["problems"]) if self.item else []

    def name(self) -> str:
        return self.item["name"] if self.item else ""

    def target(self) -> str:
        """The node a job names as its target: the meshes' shared group for a character in parts, else the first mesh."""
        if not self.item:
            return ""
        nodes = [item["node"] for item in self.item["record"]["meshes"]]
        parents = {node.rsplit("|", 1)[0] for node in nodes}
        return parents.pop() if self.character and len(nodes) > 1 and len(parents) == 1 and "" not in parents else nodes[0]

    def described(self) -> dict:
        """What the job keeps locally about its input (spec 6.3): enough to find the mesh and fit the result."""
        if not self.item:
            return {}
        record = self.item["record"]
        return {
            "task": "" if self.character else self.task.id,
            "name": self.item["name"],
            "box": record.get("box"),
            "asset_id": self.item["asset_id"],
            "path": record["path"],
            "sha256": record["sha256"],
            "format": record["format"],
            "triangles": record["triangles"],
            "faces": record["faces"],
            "up_axis": record["up_axis"],
            "names": record["names"],
            "meshes": record["meshes"],
        }

    # -- task and model ----------------------------------------------------------

    def set_task(self, task_id: str, emit: bool = False) -> None:
        self.task = edits.BY_TASK.get(task_id, edits.TASKS[0])
        self.task_button[self.task.id].setChecked(True)
        if emit:
            self.task_changed.emit(self.task.id)

    def set_model(self, model_id: str, model_name: str, takes_mesh: bool = True) -> None:
        """The page changed model: check the captured mesh against it, and send it if it now fits."""
        self.model_id, self.model_name = model_id, model_name
        if self.character:
            self.takes_mesh = takes_mesh
            self.use_button.setEnabled(takes_mesh)
        else:
            known = edits.task_for_model(model_id)
            if known is not None and known.id != self.task.id:
                self.set_task(known.id)
        if self.item:
            self.item["problems"] = self._check(self.item["record"])
            if not self.item["problems"] and self.item["state"] == "checked":
                self._send()
        self._refresh()
        self.changed.emit()

    def rule(self) -> str:
        """Motion: whether the current model needs, takes or ignores a character (core/motion.py)."""
        return motion.character_rule(self.model_id, self.takes_mesh)

    def _check(self, record: dict) -> list:
        if self.character:
            return []  # motion models document no mesh limits; the price check refuses what they cannot take
        return edits.check(self.model_id, self.model_name, record) if self.model_id else []

    # -- capture -------------------------------------------------------------------

    def use_selection(self) -> None:
        from ..maya import mesh_export

        selected = mesh_export.selected_meshes(below=self.character)
        if not selected:
            self._say("Select your character's meshes in the scene first." if self.character else "Select a mesh in the scene first.")
            return
        if len(selected) > 1 and not self.character:
            self._say(f"{len(selected)} meshes are selected. This version edits one mesh at a time: select one.")
            return
        try:
            record = mesh_export.export(selected)
        except (RuntimeError, ValueError) as error:  # Maya reports problems as RuntimeError
            self._say(f"The mesh could not be written: {error}")
            return
        self.set_record(record)

    def set_record(self, record: dict, asset_id: str = "") -> None:
        name = record.get("name") or record["meshes"][0]["node"].split("|")[-1]
        if self.character and len(record["meshes"]) > 1 and not record.get("name"):
            parents = {item["node"].rsplit("|", 1)[0] for item in record["meshes"]}
            group = parents.pop().split("|")[-1] if len(parents) == 1 else ""
            name = group or f"{name} and {len(record['meshes']) - 1} more"  # a character's group names it
        problems = self._check(record)
        self.item = {"record": record, "asset_id": asset_id, "state": "ready" if asset_id else "checked", "name": name, "problems": problems}
        if not asset_id and not problems:
            self._send()
        self._refresh()
        self.changed.emit()

    def restore(self, described: dict) -> None:
        """Re-run: the mesh a job recorded, already on Scenario; nothing is sent."""
        if not described or not str(described.get("asset_id") or "").startswith("asset_"):
            return
        if described.get("task"):
            self.set_task(described["task"])
        self.set_record(dict(described), asset_id=described["asset_id"])

    def clear(self) -> None:
        self.item = None
        self._refresh()
        self.changed.emit()

    def _send(self) -> None:
        item = self.item
        item["state"] = "uploading"
        session = self.runtime.session
        path = item["record"]["path"]

        def done(result):
            if self.item is not item:
                return
            item.update(asset_id=result["asset_id"], state="ready")
            self._refresh()
            self.changed.emit()

        def failed(error):
            if self.item is item:
                self.item = None
            self._refresh()
            self._say(f"{item['name']} was not sent: {error_text(error)}")
            self.changed.emit()

        self.runtime.background(lambda: uploads.upload_file(session, path, kind="3d"), on_done=done, on_error=failed)

    # -- drawing -------------------------------------------------------------------

    def _say(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _hint(self) -> str:
        return motion.hint(self.model_id, self.takes_mesh) if self.character else self.task.hint

    def _refresh(self) -> None:
        item = self.item
        if self.character:
            self.title.setText({motion.REQUIRED: "Character", motion.OPTIONAL: "Character (optional)"}.get(self.rule(), "Character (made by the model)"))
        if not item:
            self.mesh_line.setText("None: the model makes its own." if self.character and self.rule() != motion.REQUIRED else "Nothing captured yet.")
            self._say(self._hint())
            return
        record = item["record"]
        self.mesh_line.setText(f"{item['name']}  .  {record['triangles']:,} triangles")
        if item["state"] == "uploading":
            self._say(f"Sending {item['name']} to Scenario...")
        elif item["problems"]:
            self._say(" ".join(item["problems"]))
        elif self.character and self.rule() == motion.NONE:
            self._say(f"{item['name']} is kept for a model that takes a character. " + self._hint())
        else:
            self._say("; ".join(record.get("notes") or []) or self._hint())
