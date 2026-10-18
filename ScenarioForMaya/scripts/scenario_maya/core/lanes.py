"""Lanes: what the panel offers per kind of result (spec 4.2).

Lane ids are stable and separate from labels, so a renamed label never breaks
saved state. A lane appears in the panel only once it is built end to end.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lane:
    id: str
    label: str
    modality: str  # models_list modality filter
    capabilities: tuple  # a model belongs to the lane when it has one of these
    recommend: str  # capability passed to Scenario's recommend
    quick_picks: tuple  # first in the picker, first is the default
    starter_prompt: str
    examples: tuple
    destination: str  # the destination line before anything is generated


IMAGE = Lane(
    id="image",
    label="Image",
    modality="image",
    capabilities=("txt2img", "img2img"),
    recommend="txt2img",
    quick_picks=("model_openai-gpt-image-2-5-flare",),
    starter_prompt="a carved wooden treasure chest, game prop, studio light",
    examples=(
        "a mossy stone well, stylized, hand-painted",
        "weathered brass ship lantern, concept art, side view",
        "seamless cobblestone path texture, top down",
    ),
    destination="Saved under sourceimages/scenario. From the result: a textured card, a material on the selection, or an image plane.",
)

LANES = (IMAGE,)
BY_ID = {lane.id: lane for lane in LANES}


def lane_for_model(capabilities) -> Lane | None:
    caps = set(capabilities or ())
    return next((lane for lane in LANES if caps & set(lane.capabilities)), None)
