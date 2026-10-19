"""Motion (spec 6.2, 6.5): a text prompt to a rigged character that moves.

Some motion models make their own character (Meshy Text to Motion returns a
wooden mannequin); others rig and animate a character the user sends
(Cartwheel needs one, Uthana takes one or makes its own). The Motion mode's
character row sends the selected meshes as one GLB, written by the same
exporter as an edit's mesh, to the model's 3D input. The result lands as a
new character with its joints, skin and clip; a sent character's result
lands over it.

A model's frame-rate field starts at the scene's rate when the model offers
that rate, so the clip's keys fall on the scene's frames.
"""

from __future__ import annotations

from dataclasses import dataclass

NONE, OPTIONAL, REQUIRED = "none", "optional", "required"
RATE_FIELDS = ("fps", "frameRate")


@dataclass(frozen=True)
class MotionModel:
    character: str  # NONE: makes its own; OPTIONAL; REQUIRED
    hint: str = ""


MODELS = {
    "model_meshy-text-to-motion": MotionModel(NONE, "Makes its own character, a wooden mannequin. Pick Uthana or Cartwheel to animate yours."),
    "model_uthana-text-to-motion-3.0": MotionModel(OPTIONAL, "Rigs and animates your character when you send one, else makes its own."),
    # The price check says "Provide a reference image or a 3D model." without one [verified 2026-10-19].
    "model_cartwheel-text-to-motion": MotionModel(REQUIRED, "Rigs and animates your character: select it (a group or its meshes) and press Use selection. Check which way the rig faces."),
}

# Shoot-out on 2026-10-19, prompt "waves hello with the right hand" (spec 6.5). Scenario's recommend
# ranks Cartwheel, Uthana 3.0, then Meshy for quality; Meshy is the newest. Without a character:
# Meshy and Uthana both waved cleanly, Meshy in 31 s, Uthana in about 3 minutes. With the Multi-view
# robot as the character: Uthana rigged it facing the way it faces; Cartwheel rigged it back to
# front, whichever way it was sent and with forward -Z (one character: its back panel may read as
# a front). So Meshy is the default (works from a prompt alone), Uthana the first pick for a
# character, Cartwheel the runner-up.
PICKS = (
    "model_meshy-text-to-motion",
    "model_uthana-text-to-motion-3.0",
    "model_cartwheel-text-to-motion",
)

# Cartwheel's Maya-targeted FBX, never .ma or .mb: a scene file imports through cmds.file, which
# erases the undo history (spec 6.5).
PRESETS = {"model_cartwheel-text-to-motion": {"outputFormat": "fbx-maya"}}


def character_rule(model_id: str, takes_mesh: bool) -> str:
    """Whether ``model_id`` needs, takes or ignores a character; an unknown model takes one when it has a 3D input."""
    known = MODELS.get(model_id)
    if known is not None:
        return known.character
    return OPTIONAL if takes_mesh else NONE


def hint(model_id: str, takes_mesh: bool) -> str:
    known = MODELS.get(model_id)
    if known is not None and known.hint:
        return known.hint
    if takes_mesh:
        return "Rigs and animates your character when you send one."
    return "Makes its own character."


def scene_rate_values(form, fps: float, saved: dict) -> dict:
    """``{field: rate}`` for a frame-rate field the user has not set, when the model offers the scene's rate."""
    out = {}
    for name in RATE_FIELDS:
        field = form.field(name) if form is not None else None
        if field is None or name in saved:
            continue
        allowed = [float(value) for value in field.allowed_values if isinstance(value, (int, float))]
        match = next((value for value in allowed if abs(value - fps) < 0.01), None)
        if match is not None:
            out[name] = int(match) if match.is_integer() else match
    return out
