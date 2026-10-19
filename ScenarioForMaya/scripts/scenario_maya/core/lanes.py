"""Lanes: what the panel offers per kind of result (spec 4.2).

Lane ids are stable and separate from labels, so a renamed label never breaks
saved state. A lane appears in the panel only once it is built end to end.
Lanes that share a ``tab`` are the modes of one tab (3D: Text, Image) and
share its results list.
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
    tab: str = ""  # lanes with the same tab are its modes; "" means the lane is its own tab
    mode: str = ""  # the mode's label inside its tab
    inputs: str = ""  # "images": the lane draws an image input row for the model's image fields
    empty_hint: str = "Nothing generated yet. Type what you need and press Generate."

    @property
    def tab_id(self) -> str:
        return self.tab or self.id


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
    tab="3d",
    mode="Text",
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

THREE_D_IMAGE = Lane(
    id="3d_image",
    label="3D",
    modality="3d",
    capabilities=("img23d",),
    recommend="img23d",
    # Meshy 7.1 takes one image or up to four views and costs about half of Tripo P2, which
    # Scenario's recommend ranks first for quality on one image (shoot-out in spec 6.2).
    quick_picks=(
        "model_meshy-7-1-img23d",
        "model_tripo-p2-image-to-3d",
        "model_rodin-hyper3d-v2-5",
        "model_tripo-v3-1-image-to-3d",
        "model_hunyuan-3d-pro-3-1-i23d",
    ),
    starter_prompt="",
    examples=(),
    destination="Saved under scenario/<date> in the project. Imports as a new group at real-world size, on the ground at the camera's centre of interest.",
    results="model",
    formats=("glb",),
    presets={"model_meshy-7-1-img23d": {"shouldRemesh": True, "targetPolycount": 30000}},
    tab="3d",
    mode="Image",
    inputs="images",
    empty_hint="Nothing generated yet. Add an image of one object (a file, the viewport or an Image result) and press Generate.",
)

LANES = (IMAGE, THREE_D, THREE_D_IMAGE)
BY_ID = {lane.id: lane for lane in LANES}


def tab_lanes(tab_id: str) -> tuple:
    return tuple(lane for lane in LANES if lane.tab_id == tab_id)


def tabs() -> tuple:
    """Tab ids in panel order."""
    return tuple(dict.fromkeys(lane.tab_id for lane in LANES))


def lane_for_model(capabilities) -> Lane | None:
    caps = set(capabilities or ())
    return next((lane for lane in LANES if caps & set(lane.capabilities)), None)
