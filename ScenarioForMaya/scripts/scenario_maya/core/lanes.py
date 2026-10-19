"""Lanes: what the panel offers per kind of result (spec 4.2).

Lane ids are stable and separate from labels, so a renamed label never breaks
saved state. A lane appears in the panel only once it is built end to end.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
    results: str = "image"  # "image" lands as card, material or image plane; "model" imports a GLB
    formats: tuple = ()  # for "model" lanes: which result files to download, in order of preference
    presets: dict = field(default_factory=dict, compare=False, hash=False)  # first values per model, before the user saves any


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

THREE_D = Lane(
    id="3d",
    label="3D",
    modality="3d",
    capabilities=("txt23d",),
    recommend="txt23d",
    quick_picks=(
        "model_meshy-7-1-txt23d",
        "model_meshy-t2-5-smart-topology",
        "model_tripo-p2-text-to-3d",
        "model_rodin-hyper3d-v2-5-text-to-3d",
    ),
    starter_prompt="a carved wooden treasure chest, game prop",
    examples=(
        "a mossy stone well, stylized, hand-painted",
        "weathered brass ship lantern, game prop",
        "low poly pine tree, stylized",
    ),
    destination="Saved under scenario/<date> in the project. Imports as a new group at real-world size, on the ground at the camera's centre of interest.",
    results="model",
    formats=("glb",),
    # Meshy 7.1 returns about a million triangles unless asked to remesh, for the same price.
    presets={"model_meshy-7-1-txt23d": {"shouldRemesh": True, "targetPolycount": 30000}},
)

LANES = (IMAGE, THREE_D)
BY_ID = {lane.id: lane for lane in LANES}


def lane_for_model(capabilities) -> Lane | None:
    caps = set(capabilities or ())
    return next((lane for lane in LANES if caps & set(lane.capabilities)), None)
