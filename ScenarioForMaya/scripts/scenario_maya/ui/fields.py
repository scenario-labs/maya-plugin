"""Settings widgets built from a model's schema (spec 4.2: Settings, More settings).

Fields that change the price or are required show first; the rest sit under
"More settings (N)". The prompt and file inputs are drawn by the lane, not
here. A field left at "Default" is not sent, so Scenario applies its own.
"""

from __future__ import annotations

from ..core.schema import Field, ModelForm
from .qt import QtCore, QtWidgets, dpi

DEFAULT = "Default"


class _Number(QtWidgets.QDoubleSpinBox):
    """A spin box whose lowest position means "not set" when the field is optional."""

    def __init__(self, field: Field) -> None:
        super().__init__()
        integer = field.type == "integer" or (field.step or 0) >= 1
        self.setDecimals(0 if integer else 3)
        step = field.step or (1.0 if integer else 0.1)
        self.setSingleStep(step)
        low = field.minimum if field.minimum is not None else -1e9
        high = field.maximum if field.maximum is not None else 1e9
        self.optional = not field.required and field.default is None
        self.setRange(low - step if self.optional else low, high)
        if self.optional:
            self.setSpecialValueText(DEFAULT)
            self.setValue(self.minimum())
        elif field.default is not None:
            self.setValue(float(field.default))
        self.integer = integer
        self.setKeyboardTracking(False)

    def current(self):
        if self.optional and self.value() == self.minimum():
            return None
        return int(self.value()) if self.integer else round(self.value(), 6)


class FieldsForm(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, form: ModelForm, values: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.form = form
        self.widgets: dict = {}
        main = QtWidgets.QFormLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        more = QtWidgets.QFormLayout()
        more.setContentsMargins(0, 0, 0, 0)
        hidden = 0
        for field in form.fields:
            if field.is_prompt or field.is_file or field.name == "prompt":
                continue
            widget = self._widget(field)
            if widget is None:
                continue
            widget.setToolTip(field.description[:400])
            self.widgets[field.name] = widget
            if field.group == "options":
                main.addRow(field.label, widget)
            else:
                more.addRow(field.label, widget)
                hidden += 1
        self.more_button = QtWidgets.QToolButton()
        self.more_button.setText(f"More settings ({hidden})")
        self.more_button.setCheckable(True)
        self.more_button.setAutoRaise(True)
        self.more_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more_button.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self.more_button.setVisible(hidden > 0)
        self.more_box = QtWidgets.QWidget()
        self.more_box.setLayout(more)
        self.more_box.setVisible(False)
        self.more_button.toggled.connect(self._toggle_more)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpi(4))
        layout.addLayout(main)
        layout.addWidget(self.more_button, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.more_box)
        self.set_values(values or {})

    def _toggle_more(self, shown: bool) -> None:
        self.more_box.setVisible(shown)
        self.more_button.setArrowType(QtCore.Qt.ArrowType.DownArrow if shown else QtCore.Qt.ArrowType.RightArrow)

    def _widget(self, field: Field):
        if field.allowed_values and not field.is_array:
            box = QtWidgets.QComboBox()
            if not field.required:
                default = f"{DEFAULT} ({field.default})" if field.default is not None else DEFAULT
                box.addItem(default, None)
            for value in field.allowed_values:
                box.addItem(str(value), value)
            box.currentIndexChanged.connect(lambda *_: self.changed.emit())
            return box
        if field.type in ("number", "integer"):
            spin = _Number(field)
            spin.valueChanged.connect(lambda *_: self.changed.emit())
            return spin
        if field.type == "boolean":
            box = QtWidgets.QComboBox()
            if not field.required:
                box.addItem(f"{DEFAULT} ({'on' if field.default else 'off'})" if field.default is not None else DEFAULT, None)
            box.addItem("On", True)
            box.addItem("Off", False)
            box.currentIndexChanged.connect(lambda *_: self.changed.emit())
            return box
        if field.type == "string" and not field.is_array:
            line = QtWidgets.QLineEdit()
            if field.default not in (None, ""):
                line.setPlaceholderText(str(field.default))
            if field.max_length:
                line.setMaxLength(field.max_length)
            line.textChanged.connect(lambda *_: self.changed.emit())
            return line
        return None

    def values(self) -> dict:
        out = {}
        for name, widget in self.widgets.items():
            if isinstance(widget, _Number):
                value = widget.current()
            elif isinstance(widget, QtWidgets.QComboBox):
                value = widget.currentData()
            else:
                value = widget.text().strip() or None
            if value is not None:
                out[name] = value
        return out

    def set_values(self, values: dict) -> None:
        for name, value in values.items():
            widget = self.widgets.get(name)
            if widget is None or value is None:
                continue
            widget.blockSignals(True)
            try:
                if isinstance(widget, _Number):
                    widget.setValue(float(value))
                elif isinstance(widget, QtWidgets.QComboBox):
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                else:
                    widget.setText(str(value))
            finally:
                widget.blockSignals(False)
