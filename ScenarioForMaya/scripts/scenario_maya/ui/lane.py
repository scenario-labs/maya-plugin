"""A lane in the panel (spec 4.2): Model, Prompt, Settings, destination line,
Generate with its price, then Results.

The price check runs 0.7 s after the last edit (a free dry run); Generate is
enabled only with a current quote for exactly this form and spends it with
one click. Results update from the runtime's ``job`` events, never by
polling the ledger. Network and file reads run on workers. Lanes that are
modes of one tab (3D: Text, Image) show the same results.
"""

from __future__ import annotations

import dataclasses
import os
import time

from ..core import edits, errors, lanes, motion, provenance
from ..core.jsonutil import cu_display
from ..core.session import no_spend
from ..core.status import status_tone, status_word
from ..maya import landing, scene
from .common import TONE_COLORS, copy_text, error_text, message_label, open_url, show_message
from .fields import FieldsForm
from .inputs import ImageInputs, ViewInputs
from .jobs import job_details
from .mesh_input import MeshInput
from .qt import QtCore, QtGui, QtWidgets, dpi

PRICE_DELAY_MS = 700
REPRICE_BEFORE_EXPIRY_S = 20
RESULTS_SHOWN = 6
_THUMBS: dict = {}


def _bold(widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    font = widget.font()
    font.setBold(True)
    widget.setFont(font)
    return widget


def _muted(label: QtWidgets.QLabel) -> QtWidgets.QLabel:
    label.setEnabled(False)  # Maya's style greys disabled labels: secondary text without a colour of our own
    label.setWordWrap(True)
    return label


def model_facts(files: list) -> str:
    """``GLB . 39,691 faces . 1.70 x 1.06 x 1.30 m`` from the downloaded file's record, before any import."""
    if not files:
        return ""
    item = files[0]
    parts = [str(item.get("format") or "").upper()]
    if item.get("faces"):
        parts.append(f"{item['faces']:,} faces")
    if item.get("size_m"):
        parts.append(" x ".join(f"{value:.2f}" for value in item["size_m"]) + " m")
    return "  .  ".join(part for part in parts if part)


def _count(number: int, word: str) -> str:
    return f"{number:,} {word}{'' if number == 1 else 's'}"


def checks_line(checks: dict) -> str:
    """The import checks in one line (spec 6.7): size, materials, and anything to look at."""
    if not checks:
        return ""
    parts = []
    if checks.get("size_metres"):
        parts.append(" x ".join(f"{value:.2f}" for value in checks["size_metres"]) + " m")
    parts.append(f"{_count(checks.get('materials', 0), 'material')}, {_count(checks.get('textures', 0), 'texture')}")
    if checks.get("missing_textures"):
        parts.append(_count(len(checks["missing_textures"]), "missing texture"))
    if checks.get("non_manifold_edges"):
        parts.append(_count(checks["non_manifold_edges"], "non-manifold edge"))
    if checks.get("collapsed_triangles"):
        parts.append(_count(checks["collapsed_triangles"], "collapsed triangle") + " left out")
    if checks.get("clip"):
        parts.append(f"clip {checks['clip'].get('name') or ''} keyed".replace("  ", " "))
    parts.extend(checks.get("notes") or [])
    return "; ".join(parts)


class ResultCard(QtWidgets.QFrame):
    """One job of this lane: thumbnail, status, price, and the actions valid now."""

    def __init__(self, lane_page: LanePage, row: dict) -> None:
        super().__init__()
        self.page = lane_page
        self.runtime = lane_page.runtime
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.thumb = QtWidgets.QLabel()
        self.thumb.setFixedSize(dpi(72), dpi(72))
        self.thumb.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.title = QtWidgets.QLabel()
        self.title.setWordWrap(True)
        self.state = QtWidgets.QLabel()
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(dpi(4))
        self.note = _muted(QtWidgets.QLabel())
        self.actions = QtWidgets.QHBoxLayout()
        self.actions.setSpacing(dpi(4))
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(dpi(2))
        text.addWidget(self.title)
        text.addWidget(self.state)
        text.addWidget(self.progress)
        text.addWidget(self.note)
        text.addLayout(self.actions)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpi(6), dpi(6), dpi(6), dpi(6))
        layout.addWidget(self.thumb, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text, 1)
        self.row: dict = {}
        self.update_row(row)

    def update_row(self, row: dict, note: str = "", progress: float | None = None) -> None:
        changed_state = row.get("state") != self.row.get("state")
        changed_thumb = (row.get("result") or {}).get("thumbnail") != (self.row.get("result") or {}).get("thumbnail")
        self.row = row
        prompt = str((row.get("params") or {}).get("prompt") or row.get("label") or "")
        self.title.setText(prompt if len(prompt) < 90 else prompt[:87] + "...")
        self.title.setToolTip(prompt)
        cost = row.get("charged_exact") or row.get("cost_exact")
        word = status_word(row) if progress is None or row.get("state") != "downloading" else f"Downloading {int(progress * 100)}%"
        self.state.setText(f"{word}  .  {cu_display(cost)}" if cost else word)
        color = TONE_COLORS.get(status_tone(row))
        self.state.setStyleSheet(f"color: {color};" if color else "")
        running = row.get("state") in ("submitting", "remote", "succeeded", "downloading")
        self.progress.setVisible(running)
        value = progress if progress is not None else (row.get("result") or {}).get("progress")
        try:
            number = float(value)
            self.progress.setRange(0, 100)
            self.progress.setValue(int(number * 100 if number <= 1 else number))
        except (TypeError, ValueError):
            self.progress.setRange(0, 0)  # busy until Scenario reports progress
        message = note if note and not note.startswith(("Sent", "Ready")) else ""
        if row.get("state") in ("failed", "download_failed", "apply_failed", "uncertain") or (row.get("hint") or "").startswith("Delivery paused"):
            message = " ".join(part for part in (row.get("error"), row.get("hint")) if part) or message
        elif not message and self.page.lane.results == "model":
            message = model_facts(self._files())
        self.note.setText(message)
        self.note.setVisible(bool(message))
        if changed_state:
            self._build_actions()
        if changed_state or changed_thumb:
            self._load_thumb()

    def _files(self) -> list:
        return (self.row.get("result") or {}).get("files") or []

    def _button(self, text: str, tip: str, slot) -> None:
        button = QtWidgets.QPushButton(text)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        self.actions.addWidget(button)

    def _build_actions(self) -> None:
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        state = self.row.get("state")
        edit = ((self.row.get("origin") or {}).get("edit") or {}).get("task") or ""
        if state in ("ready", "applied", "apply_failed") and self._files() and self.page.lane.results == "model":
            self._button(
                "Import",
                "Import as a new group fitted over the mesh it came from. The mesh is not changed. One Ctrl+Z removes it."
                if edit
                else "Import as a new group at real-world size, on the ground at the camera's centre of interest. One Ctrl+Z removes it.",
                lambda: self.page.land(self.row, "model"),
            )
            if edit in APPLY_TIPS:
                self._button("Apply...", APPLY_TIPS[edit], lambda: self.page.review_apply(self.row))
        elif state in ("ready", "applied", "apply_failed") and self._files():
            self._button("Card", "Import as a textured card at the camera's centre of interest. One Ctrl+Z removes it.", lambda: self.page.land(self.row, "card"))
            self._button("Material", "Put the image as base colour of a new material on the selected meshes or faces.", lambda: self.page.land(self.row, "material"))
            self._button("Image plane", "Add the image as an image plane on the current camera.", lambda: self.page.land(self.row, "image_plane"))
        if state == "download_failed":
            self._button("Retry download", "Download the result again with a fresh link, from where it stopped.", lambda: self.runtime.jobs.track(self.row["local_id"]))
        more = QtWidgets.QToolButton()
        more.setText("...")
        more.setAutoRaise(True)
        more.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QtWidgets.QMenu(more)
        files = self._files()
        if files:
            menu.addAction("Show file", lambda: open_url(QtCore.QUrl.fromLocalFile(os.path.dirname(files[0]["path"])).toString()))
            session = self.runtime.session
            menu.addAction(
                "Open on Scenario",
                lambda: open_url(provenance.web_url(files[0].get("asset_id", ""), session.settings.get("team_id"), session.settings.get("project_id"))),
            )
        if files and self.page.lane.results == "image" and files[0].get("asset_id"):
            menu.addAction("Make a 3D model from this image", lambda: self.page.image_to_3d.emit(self.row))
        menu.addAction("Re-run settings", lambda: self.page.reuse(self.row))
        menu.addAction("Copy details", lambda: copy_text(self.page.details(self.row)))
        more.setMenu(menu)
        self.actions.addStretch(1)
        self.actions.addWidget(more)

    def _load_thumb(self) -> None:
        files = self._files()
        path = (self.row.get("result") or {}).get("thumbnail") or (files[0].get("path", "") if files else "")
        placeholder = "3D" if files and self.page.lane.results == "model" else ""
        if not path or not os.path.exists(path) or path.lower().endswith((".glb", ".gltf", ".fbx", ".obj")):
            self.thumb.clear()  # setPixmap would clear the text again
            self.thumb.setText(placeholder)
            return
        if self.thumb.pixmap().isNull():
            self.thumb.setText(placeholder)  # until the picture is decoded, or if it cannot be
        size = dpi(72)
        if path in _THUMBS:
            self.thumb.setPixmap(_THUMBS[path])
            return

        def decode():  # QImage decodes off the main thread; QPixmap is made on it
            return QtGui.QImage(path).scaled(size, size, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)

        def show(image):
            if image.isNull():
                return
            _THUMBS[path] = QtGui.QPixmap.fromImage(image)
            try:
                self.thumb.setPixmap(_THUMBS[path])
            except RuntimeError:
                pass  # the card was closed meanwhile

        self.runtime.background(decode, on_done=show)


APPLY_TIPS = {
    "uv": "Write these UVs into the mesh they came from; its current UV set is kept as a backup. Shows what changes first; one Ctrl+Z undoes it.",
    "retexture": "Put the result's textures on the mesh it came from, as a new material. Shows what changes first; one Ctrl+Z undoes it.",
    "remesh": "Replace the geometry of the mesh it came from; the old shape stays, hidden. Shows what changes first; one Ctrl+Z undoes it.",
}


def _same_tab(row: dict, lane: lanes.Lane) -> bool:
    other = lanes.BY_ID.get((row.get("origin") or {}).get("lane") or "")
    return other is not None and other.tab_id == lane.tab_id


class LanePage(QtWidgets.QWidget):
    image_to_3d = QtCore.Signal(dict)  # an Image result to send to the 3D tab's Image mode
    show_lane = QtCore.Signal(str, dict)  # re-run of a job from another mode of this tab

    def __init__(self, runtime, lane: lanes.Lane = lanes.IMAGE, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.session = runtime.session
        self.lane = lane
        self.form = None
        self.fields: FieldsForm | None = None
        self.quote = None
        self._price_seq = 0
        self._busy = False
        self._forms: dict = {}
        self.cards: dict = {}
        self.review_dialog = None  # the last Apply review shown

        self.model_name = _bold(QtWidgets.QLabel())
        self.model_line = _muted(QtWidgets.QLabel())
        self.change = QtWidgets.QPushButton("Change")
        self.change.setToolTip("Choose another model for this lane.")
        self.change.clicked.connect(self.pick_model)
        model_row = QtWidgets.QHBoxLayout()
        model_row.addWidget(self.model_name, 1)
        model_row.addWidget(self.change)

        self.inputs = None
        if lane.inputs == "images":
            self.inputs = ImageInputs(runtime)
            self.inputs.changed.connect(self._edited)
            self.inputs.set_field(None)
        self.views = None
        if lane.inputs == "views":
            self.views = ViewInputs(runtime)
            self.views.changed.connect(self._edited)
        self.mesh = None
        if lane.inputs == "mesh":
            self.mesh = MeshInput(runtime)
            self.mesh.set_task(self.session.settings.get(f"lane_{lane.id}_task") or edits.TASKS[0].id)
            self.mesh.changed.connect(self._edited)
            self.mesh.task_changed.connect(self._task_changed)
        elif lane.inputs == "character":
            self.mesh = MeshInput(runtime, character=True)
            self.mesh.changed.connect(self._edited)
        self.prompt_label = QtWidgets.QLabel("Prompt")
        self.prompt = QtWidgets.QPlainTextEdit()
        self.prompt.setPlaceholderText("Describe what you need")
        self.prompt.setTabChangesFocus(True)
        self.prompt.setFixedHeight(dpi(70))
        self.prompt.textChanged.connect(self._edited)

        self.fields_box = QtWidgets.QVBoxLayout()
        self.fields_box.setContentsMargins(0, 0, 0, 0)
        self.destination = _muted(QtWidgets.QLabel(lane.destination))

        self.generate_button = _bold(QtWidgets.QPushButton("Checking price..."))
        self.generate_button.setMinimumHeight(dpi(34))
        self.generate_button.setToolTip("Send this request to Scenario. It spends the price shown on the button.")
        self.generate_button.clicked.connect(self.generate)
        self.message = message_label()

        self.results_title = _bold(QtWidgets.QLabel("Results"))
        self.results_box = QtWidgets.QVBoxLayout()
        self.results_box.setSpacing(dpi(4))
        self.empty = _muted(QtWidgets.QLabel(lane.empty_hint))
        self.examples = QtWidgets.QVBoxLayout()  # stacked: a row of prompts would widen a narrow panel
        self.examples.setSpacing(0)
        for example in lane.examples:
            chip = QtWidgets.QPushButton(example if len(example) < 28 else example[:26] + "...")
            chip.setToolTip(f"Use this prompt: {example}")
            chip.setFlat(True)
            chip.clicked.connect(lambda _=False, text=example: self.prompt.setPlainText(text))
            self.examples.addWidget(chip, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpi(6))
        layout.addLayout(model_row)
        layout.addWidget(self.model_line)
        if self.inputs is not None:
            layout.addWidget(self.inputs)
        if self.views is not None:
            layout.addWidget(self.views)
        if self.mesh is not None:
            layout.addWidget(self.mesh)
        layout.addWidget(self.prompt_label)
        layout.addWidget(self.prompt)
        layout.addLayout(self.fields_box)
        layout.addWidget(self.destination)
        layout.addWidget(self.generate_button)
        layout.addWidget(self.message)
        layout.addSpacing(dpi(6))
        layout.addWidget(self.results_title)
        layout.addWidget(self.empty)
        layout.addLayout(self.examples)
        layout.addLayout(self.results_box)

        shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self)
        shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.generate)
        self.price_timer = QtCore.QTimer(self)
        self.price_timer.setSingleShot(True)
        self.price_timer.timeout.connect(self.check_price)
        self.expiry_timer = QtCore.QTimer(self)
        self.expiry_timer.setSingleShot(True)
        self.expiry_timer.timeout.connect(self.check_price)

        settings = self.session.settings
        # Each lane starts with its own example until something is sent from it; a prompt cleared later stays cleared.
        prompt = settings.get(f"lane_{lane.id}_prompt")
        if prompt is None:
            prompt = lane.starter_prompt
        self.prompt.blockSignals(True)
        self.prompt.setPlainText(prompt)
        self.prompt.blockSignals(False)
        self.set_model(self._saved_model(), save=False)
        self.reload_results()

    # -- model and form ----------------------------------------------------

    @property
    def model_id(self) -> str:
        return self._model_id

    def _saved_model(self) -> str:
        settings = self.session.settings
        if self._edit_mesh():  # Edit selection remembers a model per task
            return settings.get(f"lane_{self.lane.id}_model_{self.mesh.task.id}") or self.mesh.task.quick_picks[0]
        return settings.get(f"lane_{self.lane.id}_model") or self.lane.quick_picks[0]

    def _edit_mesh(self) -> bool:
        return self.mesh is not None and not self.mesh.character

    def _task_changed(self, task_id: str) -> None:
        self.session.settings.update(**{f"lane_{self.lane.id}_task": task_id})
        self.set_model(self._saved_model(), save=False)

    def set_model(self, model_id: str, save: bool = True) -> None:
        self._model_id = model_id
        row = self.runtime.catalog.get(self.session.workspace(), model_id) if self.session.signed_in else None
        self.model_name.setText((row or {}).get("name") or model_id.replace("model_", ""))
        self.model_line.setText((row or {}).get("shortDescription") or "")
        self.model_line.setVisible(bool(self.model_line.text()))
        if save:
            key = f"lane_{self.lane.id}_model"
            task = edits.task_for_model(model_id) if self._edit_mesh() else None
            if task is not None:
                key += f"_{task.id}"
            self.session.settings.update(**{key: model_id})
        self._set_fields(None)
        self._button("Loading model...", False)
        if not self.session.signed_in:
            self._button("Sign in to generate", False)
            return
        if model_id in self._forms:
            self._form_loaded(model_id, self._forms[model_id])
            return
        backend = self.session.backend()
        self.runtime.background(lambda: backend.model_form(model_id), on_done=lambda form: self._form_loaded(model_id, form), on_error=self._form_failed)

    def _form_loaded(self, model_id: str, form) -> None:
        if model_id != self._model_id:
            return
        self._forms[model_id] = form
        if not self.model_name.text() or self.model_name.text() == model_id.replace("model_", ""):
            self.model_name.setText(form.name or self.model_name.text())
        saved = self.session.settings.get(f"lane_{self.lane.id}_values_{model_id}") or dict(self.lane.presets.get(model_id) or {})
        if self.lane.inputs == "character":  # a motion model's frame rate starts at the scene's
            saved = dict(saved, **motion.scene_rate_values(form, scene.fps(), saved))
        self._set_fields(FieldsForm(form, saved))
        self.form = form
        self._show_prompt(form.prompt_field)
        if self.inputs is not None:
            self.inputs.set_field(form.image_fields[0] if form.image_fields else None)
        if self.views is not None:
            self.views.set_fields(form.view_fields)
        if self.mesh is not None:
            self.mesh.set_model(model_id, self.model_name.text(), takes_mesh=bool(form.mesh_fields))
            self._show_prompt(form.prompt_field)
        self._edited()

    def _show_prompt(self, field) -> None:
        """The prompt box follows the model: hidden when it takes none, marked optional when it may."""
        self.prompt_label.setVisible(field is not None)
        self.prompt.setVisible(field is not None)
        if field is not None:
            needed = field.required or field.name == "prompt" or (self._edit_mesh() and self.mesh.task.needs_prompt)
            self.prompt_label.setText("Prompt" if needed else f"{field.label} (optional)")

    def _form_failed(self, error) -> None:
        self._button("Price unavailable (Retry)", True)
        show_message(self.message, "Could not load the model: " + error_text(error), "error")

    def _set_fields(self, fields: FieldsForm | None) -> None:
        if self.fields is not None:
            self.fields.setParent(None)
            self.fields.deleteLater()
        self.fields = fields
        self.form = None if fields is None else fields.form
        if fields is not None:
            fields.changed.connect(self._edited)
            self.fields_box.addWidget(fields)

    def pick_model(self) -> None:
        from .picker import ModelPicker

        if not self.session.signed_in:
            return
        lane = dataclasses.replace(self.lane, quick_picks=self.mesh.task.quick_picks) if self._edit_mesh() else self.lane
        dialog = ModelPicker(self.runtime, lane, current=self._model_id, parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and dialog.chosen:
            self.set_model(dialog.chosen)

    # -- price -------------------------------------------------------------

    def values(self) -> dict:
        out = dict(self.fields.values()) if self.fields is not None else {}
        prompt_field = self.form.prompt_field if self.form is not None else None
        prompt = self.prompt.toPlainText().strip()
        if prompt and (prompt_field is not None or self.form is None):
            out[prompt_field.name if prompt_field is not None else "prompt"] = prompt
        if self.inputs is not None and self.inputs.field is not None:
            ids = self.inputs.asset_ids()
            if ids:
                out[self.inputs.field.name] = ids if self.inputs.field.is_array else ids[0]
        if self.views is not None:
            out.update(self.views.values())
        if self.mesh is not None and self.form is not None and self.form.mesh_fields and self.mesh.asset_id():
            field = self.form.mesh_fields[0]
            out[field.name] = [self.mesh.asset_id()] if field.is_array else self.mesh.asset_id()
        return out

    def origin(self) -> dict:
        out = {"scene_uuid": scene.scene_uuid(create=False), "scene_path": scene.scene_path(), "target": "", "lane": self.lane.id}
        if self.inputs is not None:
            out["inputs"] = self.inputs.described()  # local record only, for Re-run
        if self.views is not None:
            out["inputs"] = self.views.described()
            if self.views.capture_record:
                out["views_capture"] = dict(self.views.capture_record)  # where the views were taken
        if self._edit_mesh() and self.mesh.item:
            out["edit"] = self.mesh.described()  # local record: what was sent, to fit and apply the result
            out["target"] = out["edit"]["meshes"][0]["node"]
        if self.mesh is not None and self.mesh.character and self._sends_character():
            out["character"] = self.mesh.described()  # local record: the result lands over it
            out["target"] = self.mesh.target()
        return out

    def _sends_character(self) -> bool:
        return bool(self.form is not None and self.form.mesh_fields and self.mesh.asset_id())

    def label(self, params: dict) -> str:
        """The job's name: its prompt, else the names of its images."""
        prompt_field = self.form.prompt_field if self.form is not None else None
        text = str(params.get(prompt_field.name if prompt_field is not None else "prompt") or "")
        if not text and self.inputs is not None:
            text = ", ".join(os.path.splitext(name)[0] for name in self.inputs.names())
        if not text and self.views is not None:
            captured = self.views.capture_record.get("name") if self.views.capture_record else ""
            text = f"Views of {captured}" if captured else ", ".join(os.path.splitext(name)[0] for name in self.views.names())
        if not text and self._edit_mesh():
            text = f"{self.mesh.task.label} {self.mesh.name()}"
        return text

    def _button(self, text: str, enabled: bool) -> None:
        self.generate_button.setText(text)
        self.generate_button.setEnabled(enabled)

    def _edited(self) -> None:
        self.quote = None
        self.expiry_timer.stop()
        if self._busy:
            return
        if not self.session.signed_in:
            self._button("Sign in to generate", False)
            return
        if self.form is None:
            return
        if self.inputs is not None and self.inputs.busy():
            self.price_timer.stop()
            self._button("Sending the image...", False)
            return
        if self.views is not None and (self.views.busy() or self.views.problem()):
            self.price_timer.stop()
            self._button("Sending the views..." if self.views.busy() else self.views.problem(), False)
            return
        if self.mesh is not None:
            blocked = self._mesh_blocked()
            if blocked:
                self.price_timer.stop()
                self._button(blocked, False)
                return
        problems = self.form.problems(self.values())
        if problems:
            self.price_timer.stop()
            self._button(problems[0], False)
            return
        self._button("Checking price...", False)
        self.price_timer.start(PRICE_DELAY_MS)

    def _mesh_blocked(self) -> str:
        """The Generate button's word when the edit's mesh or the needed character is not ready (spec 4.2)."""
        mesh = self.mesh
        if mesh.character:
            return self._character_blocked()
        if mesh.busy():
            return "Sending the mesh..."
        if not mesh.item:
            self.destination.setText(self.lane.destination)
            return "Select a mesh to edit"
        self.destination.setText(f"Saved under scenario/<date>. Import places the result over {mesh.name()}, fitted to it, as a new group; {mesh.name()} is not changed.")
        if mesh.problems():
            return "Mesh not accepted by this model"
        if mesh.task.needs_prompt and not self.prompt.toPlainText().strip():
            return "Needs a prompt"
        return ""

    def _character_blocked(self) -> str:
        mesh, rule = self.mesh, self.mesh.rule()
        self.destination.setText(self.lane.destination)
        if rule == motion.NONE:
            return ""
        if mesh.busy():
            return "Sending the character..."
        if not mesh.item:
            return "Select your character" if rule == motion.REQUIRED else ""
        if mesh.problems():
            return "Character not accepted by this model"
        name = mesh.name()
        self.destination.setText(f"Saved under scenario/<date>. Import places the result over {name}, at its size, as a new character with joints, skin and clip; {name} is not changed.")
        return ""

    def check_price(self) -> None:
        if self.form is None or not self.session.signed_in or self._busy:
            return
        values = self.values()
        if self.form.problems(values):
            self._edited()
            return
        params = self.form.build_params(values)
        origin = self.origin()
        model_id = self._model_id
        self._price_seq += 1
        seq = self._price_seq
        self._button("Checking price...", False)

        def done(quote):
            if seq != self._price_seq:
                return
            self.quote = (quote, params, origin)
            if no_spend():
                self._button(f"Spending off . {quote.cu_cost_display()}", False)
            else:
                self._button(f"Generate . {quote.cu_cost_display()}", True)
            self.generate_button.setToolTip(f"Send this request to Scenario for {quote.cu_cost_display()}. Ctrl+Enter.")
            self.expiry_timer.start(int(max(1.0, quote.seconds_left() - REPRICE_BEFORE_EXPIRY_S) * 1000))
            show_message(self.message, "")

        def failed(error):
            if seq != self._price_seq:
                return
            self._button("Price unavailable (Retry)", True)
            show_message(self.message, error_text(error), "error")

        self.runtime.background(lambda: self.session.price(model_id, params, origin=origin), on_done=done, on_error=failed)

    # -- generate ----------------------------------------------------------

    def generate(self) -> None:
        if self.generate_button.text().startswith("Price unavailable") or (self.quote is None and self.form is not None and not self._busy):
            self.check_price()
            return
        if self.quote is None or self._busy or not self.generate_button.isEnabled():
            return
        quote, params, origin = self.quote
        threshold = float(self.session.settings.get("confirm_above_cu") or 0)
        if threshold and float(quote.cu_cost_exact) > threshold:
            answer = QtWidgets.QMessageBox.question(self, "Generate", f"Send this request for {quote.cu_cost_display()}?")
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.quote = None
        self._busy = True
        self._button("Waiting for Scenario...", False)
        settings = self.session.settings
        settings.update(**{f"lane_{self.lane.id}_prompt": self.prompt.toPlainText().strip(), f"lane_{self.lane.id}_values_{self._model_id}": self.fields.values() if self.fields else {}})
        label = self.label(params)
        started = time.monotonic()

        def sent(row):
            self.reload_results()
            show_message(self.message, "")
            QtCore.QTimer.singleShot(max(0, int(2000 - (time.monotonic() - started) * 1000)), self._unbusy)

        def failed(error):
            self._unbusy()
            tone = "warning" if isinstance(error, errors.NotConfirmed) else "error"
            show_message(self.message, error_text(error), tone)
            self.reload_results()

        self.runtime.jobs.generate(
            quote.quote_id,
            approved_cost=quote.cu_cost_exact,
            params=params,
            origin=origin,
            model_name=self.model_name.text(),
            label=label,
            on_sent=sent,
            on_error=failed,
        )

    def _unbusy(self) -> None:
        self._busy = False
        self._edited()

    # -- results -----------------------------------------------------------

    def _lane_rows(self) -> list:
        if not self.session.signed_in:
            return []
        rows = self.runtime.ledger.list(limit=40, workspace=self.session.workspace())
        return [row for row in rows if _same_tab(row, self.lane)][:RESULTS_SHOWN]

    def reload_results(self) -> None:
        rows = self._lane_rows()
        keep = {row["local_id"] for row in rows}
        for local_id in list(self.cards):
            if local_id not in keep:
                self.cards.pop(local_id).deleteLater()
        for index, row in enumerate(rows):
            card = self.cards.get(row["local_id"])
            if card is None:
                card = ResultCard(self, row)
                self.cards[row["local_id"]] = card
            else:
                card.update_row(row)
            self.results_box.removeWidget(card)
            self.results_box.insertWidget(index, card)
        self.empty.setVisible(not rows)
        for index in range(self.examples.count()):
            widget = self.examples.itemAt(index).widget()
            if widget:
                widget.setVisible(not rows)

    def on_job(self, data: dict) -> None:
        row = data.get("row") or {}
        if not _same_tab(row, self.lane):
            return
        card = self.cards.get(row.get("local_id"))
        if card is None:
            self.reload_results()
            return
        card.update_row(row, data.get("note") or "", data.get("progress"))

    def land(self, row: dict, mode: str) -> None:
        try:
            made = self.runtime.jobs.land(row["local_id"], mode)
        except landing.LandingError as error:
            show_message(self.message, str(error), "warning")
            return
        except errors.ScenarioError as error:
            show_message(self.message, error_text(error), "error")
            return
        note = " Textured display turned on in the viewport (key 6)." if made.get("textures_turned_on") else ""
        checks = made.get("checks") or {}
        if checks:
            note = f" {checks_line(checks)}." + note
        attention = checks.get("missing_textures") or checks.get("notes")
        show_message(self.message, f"{made.get('summary', 'Done')}. One Ctrl+Z removes it.{note}", "warning" if attention else "ok")

    def review_apply(self, row: dict) -> None:
        """Apply... on an edit result: proves the result against the mesh, then shows the review (spec 4.7)."""
        from .apply_review import ApplyReview

        def show(review) -> None:
            show_message(self.message, "")
            dialog = ApplyReview(review, parent=self)
            self.review_dialog = dialog
            dialog.accepted.connect(lambda: self.apply_review(row, review))
            dialog.open()

        def failed(error) -> None:
            show_message(self.message, error.args[0] if isinstance(error, landing.LandingError) and error.args else error_text(error), "error")

        try:
            self.runtime.jobs.review_apply(row["local_id"], on_done=show, on_error=failed)
        except landing.LandingError as error:
            show_message(self.message, str(error), "warning")
            return
        show_message(self.message, "Checking the result against the mesh...")

    def apply_review(self, row: dict, review) -> None:
        try:
            made = self.runtime.jobs.apply_edit(row["local_id"], review)
        except landing.LandingError as error:
            show_message(self.message, str(error), "warning")
            return
        except errors.ScenarioError as error:
            show_message(self.message, error_text(error), "error")
            return
        show_message(self.message, f"{made['summary']}. One Ctrl+Z undoes it.", "ok")

    def reuse(self, row: dict) -> None:
        """Re-run: fills the form with that job's settings. Sends nothing."""
        lane_id = (row.get("origin") or {}).get("lane") or self.lane.id
        if lane_id != self.lane.id:
            self.show_lane.emit(lane_id, row)  # the panel switches mode and re-runs there
            return
        params = dict(row.get("params") or {})
        form = self._forms.get(row.get("target_id") or self._model_id) or self.form
        prompt_field = form.prompt_field if form is not None else None
        if self.inputs is not None:
            self.inputs.set_items((row.get("origin") or {}).get("inputs") or [])
        if self.views is not None:
            self.views.capture_record = dict((row.get("origin") or {}).get("views_capture") or {})
            self.views.set_items((row.get("origin") or {}).get("inputs") or [])
        if self.mesh is not None:
            self.mesh.restore((row.get("origin") or {}).get("edit") or (row.get("origin") or {}).get("character") or {})
        if row.get("target_id") and row["target_id"] != self._model_id:
            self.session.settings.update(**{f"lane_{self.lane.id}_values_{row['target_id']}": {k: v for k, v in params.items() if k != "prompt"}})
            self.set_model(row["target_id"])
        elif self.fields is not None:
            self.fields.set_values(params)
        self.prompt.setPlainText(str(params.get(prompt_field.name if prompt_field is not None else "prompt") or ""))

    def details(self, row: dict) -> str:
        return job_details(row)

    def refresh(self) -> None:
        """After sign-in, sign-out or a workspace change."""
        self._forms.clear()
        self.set_model(self._model_id, save=False)
        self.reload_results()
