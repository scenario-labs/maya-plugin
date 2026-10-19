"""Model forms from ``model_schema_get``.

Turns Scenario's parameter list into typed fields the panel renders and the
agent tools validate against, and builds the ``parameters`` object for a run.
Unchanged optional fields are left out, so Scenario applies its own defaults
and the payload (and its hash) stays small and stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import errors

FILE_TYPES = ("file", "file_array")
_PRIMARY_NAMES = ("prompt", "text", "image", "images", "model", "video", "audio")


@dataclass
class Field:
    name: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None
    allowed_values: tuple = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    max_length: int | None = None
    max_items: int | None = None
    kind: str = ""  # image, 3d, audio, video for file fields
    is_prompt: bool = False
    prompt_spark: bool = False
    cost_impact: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def is_file(self) -> bool:
        return self.type in FILE_TYPES

    @property
    def is_array(self) -> bool:
        return self.type in ("file_array", "array") or bool(self.raw.get("array"))

    @property
    def label(self) -> str:
        words, current = [], ""
        for char in self.name:
            if char.isupper() and current:
                words.append(current)
                current = char.lower()
            else:
                current += char
        if current:
            words.append(current)
        text = " ".join(words).replace("_", " ").strip()
        return text[:1].upper() + text[1:]

    @property
    def group(self) -> str:
        if self.is_prompt or self.is_file or self.name in _PRIMARY_NAMES:
            return "main"
        if self.cost_impact or self.required:
            return "options"
        return "advanced"

    def public(self) -> dict:
        out = {"name": self.name, "type": self.type, "required": self.required}
        for key, value in (
            ("default", self.default),
            ("allowed_values", list(self.allowed_values) or None),
            ("min", self.minimum),
            ("max", self.maximum),
            ("max_length", self.max_length),
            ("max_items", self.max_items),
            ("kind", self.kind or None),
            ("cost_impact", self.cost_impact or None),
            ("prompt_spark", self.prompt_spark or None),
        ):
            if value is not None and value != "":
                out[key] = value
        if self.description:
            out["description"] = self.description[:300]
        return out


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return value is True or value == "true"


def parse_field(data: dict) -> Field:
    allowed = data.get("allowed_values") or data.get("allowedValues") or data.get("enum") or ()
    if isinstance(allowed, list):
        allowed = tuple(item.get("value") if isinstance(item, dict) and "value" in item else item for item in allowed)
    else:
        allowed = ()
    kind_type = str(data.get("type") or "string")
    if _truthy(data.get("array")) and kind_type == "file":
        kind_type = "file_array"
    max_length = data.get("max_length", data.get("maxLength"))
    max_items = data.get("max_items", data.get("maxItems"))
    if kind_type == "file_array" and max_items is None:
        max_items, max_length = max_length, None  # Scenario gives a file list's limit as max_length
    return Field(
        name=str(data.get("name") or ""),
        type=kind_type,
        description=str(data.get("description") or ""),
        required=_truthy(data.get("required")),
        default=data.get("default"),
        allowed_values=allowed,
        minimum=_number(data.get("min", data.get("minimum"))),
        maximum=_number(data.get("max", data.get("maximum"))),
        step=_number(data.get("step")),
        max_length=int(max_length) if isinstance(max_length, (int, float)) else None,
        max_items=int(max_items) if isinstance(max_items, (int, float)) else None,
        kind=str(data.get("kind") or ""),
        is_prompt=_truthy(data.get("prompt")) or data.get("name") == "prompt",
        prompt_spark=_truthy(data.get("prompt_spark")),
        cost_impact=_truthy(data.get("cost_impact")),
        raw=dict(data),
    )


def _missing_file(item: Field) -> str:
    """``Add an image``; with the field's name when the model takes several kinds of file."""
    noun = {"image": "image", "3d": "3D model", "video": "video", "audio": "audio file"}.get(item.kind, "file")
    text = f"Add {'an' if noun[0] in 'aeiou' else 'a'} {noun}"
    return text if item.name in _PRIMARY_NAMES else f"{text} for {item.label.lower()}"


@dataclass
class ModelForm:
    model_id: str
    name: str
    capabilities: tuple
    fields: list

    @classmethod
    def from_schema(cls, schema: dict) -> ModelForm:
        if not isinstance(schema, dict) or not isinstance(schema.get("parameters"), list):
            raise errors.ProtocolError("The model schema has no parameter list.")
        fields = [parse_field(item) for item in schema["parameters"] if isinstance(item, dict) and item.get("name")]
        return cls(
            model_id=str(schema.get("model_id") or schema.get("id") or ""),
            name=str(schema.get("name") or ""),
            capabilities=tuple(schema.get("capabilities") or ()),
            fields=fields,
        )

    def field(self, name: str) -> Field | None:
        return next((item for item in self.fields if item.name == name), None)

    @property
    def prompt_field(self) -> Field | None:
        return self.field("prompt") or next((item for item in self.fields if item.is_prompt), None)

    @property
    def file_fields(self) -> list:
        return [item for item in self.fields if item.is_file]

    @property
    def image_fields(self) -> list:
        """Image inputs, required ones first (the lane's image row fills the first)."""
        fields = [item for item in self.fields if item.is_file and item.kind in ("image", "")]
        return sorted(fields, key=lambda item: not item.required)

    def defaults(self) -> dict:
        return {item.name: item.default for item in self.fields if item.default is not None}

    def problems(self, values: dict) -> list:
        """Human-readable reasons the form cannot be priced yet; empty when ready."""
        out = []
        for item in self.fields:
            value = values.get(item.name)
            empty = value is None or value == "" or value == [] or value == ()
            if item.required and empty:
                out.append(_missing_file(item) if item.is_file else f"Needs a {item.label.lower()}")
                continue
            if empty:
                continue
            if item.allowed_values and not item.is_array and value not in item.allowed_values:
                out.append(f"{item.label}: {value!r} is not one of {list(item.allowed_values)}")
            if item.type in ("number", "integer") and not isinstance(value, bool):
                number = _number(value)
                if number is None:
                    out.append(f"{item.label}: not a number")
                elif item.minimum is not None and number < item.minimum:
                    out.append(f"{item.label}: at least {item.minimum:g}")
                elif item.maximum is not None and number > item.maximum:
                    out.append(f"{item.label}: at most {item.maximum:g}")
            if item.type == "string" and item.max_length and isinstance(value, str) and len(value) > item.max_length:
                out.append(f"{item.label}: {len(value)} characters, at most {item.max_length}")
            if item.is_file:
                ids = value if isinstance(value, (list, tuple)) else [value]
                if any(not (isinstance(v, str) and v.startswith("asset_")) for v in ids):
                    out.append(f"{item.label}: needs a Scenario asset id (upload the file first)")
                if item.max_items and len(ids) > item.max_items:
                    out.append(f"{item.label}: at most {item.max_items} files")
        return out

    def build_params(self, values: dict) -> dict:
        """Parameters for ``model_run``: known fields only, unchanged defaults left out."""
        params = {}
        for item in self.fields:
            if item.name not in values:
                continue
            value = values[item.name]
            if value is None or value == "" or value == []:
                continue
            if not item.required and item.default is not None and value == item.default:
                continue
            if item.type == "integer" and isinstance(value, float) and value.is_integer():
                value = int(value)
            if item.type == "number" and isinstance(value, str):
                value = _number(value)
            if item.type == "file_array" and isinstance(value, str):
                value = [value]
            params[item.name] = value
        return params
