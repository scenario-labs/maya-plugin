"""Lanes: what the panel offers per kind of result (spec 4.2).

Lane ids are stable and separate from labels, so a renamed label never breaks
saved state. A lane appears in the panel only once it is built end to end.
Lanes that share a ``tab`` are the modes of one tab (3D: Text, Image,
Multi-view, Edit selection, Motion) and share its results list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import edits
from .motion import PICKS as MOTION_PICKS
from .motion import PRESETS as MOTION_PRESETS


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
    results: str = "image"  # "image" lands as card, material or image plane; "model" imports a GLB or FBX
    formats: tuple = ()  # for "model" lanes: which result files to download, in order of preference
    presets: dict = field(default_factory=dict, compare=False, hash=False)  # first values per model, before the user saves any
    tab: str = ""  # lanes with the same tab are its modes; "" means the lane is its own tab
    mode: str = ""  # the mode's label inside its tab
    inputs: str = ""  # "images": an image row for the model's first image field; "views": one slot per named view; "mesh": the selected mesh for an edit; "character": the selected character, optional
    empty_hint: str = "Nothing generated yet. Type what you need and press Generate."
    tags: tuple = ()  # when set, a model joins the lane only with one of these catalog tags (lowercase)
    without_tags: tuple = ()  # a model with one of these tags is left out

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
    formats=("glb", "fbx"),
    # Meshy 7.1 returns about a million triangles unless asked to remesh, for the same price.
    presets={"model_meshy-7-1-txt23d": {"shouldRemesh": True, "targetPolycount": 30000}},
    without_tags=("motion",),  # text to motion models are txt23d too; they live in the Motion mode
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
    formats=("glb", "fbx"),
    presets={"model_meshy-7-1-img23d": {"shouldRemesh": True, "targetPolycount": 30000}},
    tab="3d",
    mode="Image",
    inputs="images",
    empty_hint="Nothing generated yet. Add an image of one object (a file, the viewport or an Image result) and press Generate.",
)

THREE_D_VIEWS = Lane(
    id="3d_views",
    label="3D",
    modality="3d",
    capabilities=("img23d",),
    recommend="img23d",
    # Models with named views (front, left, back, right...). Scenario's recommend ranked Tripo P2
    # Multi View first for four views on 2026-10-19, Tripo 3.1 Multi View second. On the same four
    # captured views both kept the shape; Tripo P2 gave 4,987 faces for 220 CU, Tripo 3.1
    # 1.4 million faces for 45 CU. Tripo P2 stays the default, Tripo 3.1 is the runner-up.
    quick_picks=(
        "model_tripo-p2-multiview-to-3d",
        "model_tripo-v3-1-multiview-to-3d",
        "model_hunyuan-3d-pro-3-1-multiview",
    ),
    starter_prompt="",
    examples=(),
    destination="Saved under scenario/<date> in the project. Imports as a new group at real-world size, on the ground at the camera's centre of interest.",
    results="model",
    formats=("glb", "fbx"),
    # Hunyuan's default is 500,000 faces; its minimum keeps the import light.
    presets={"model_hunyuan-3d-pro-3-1-multiview": {"faceCount": 40000}},
    tab="3d",
    mode="Multi-view",
    inputs="views",
    empty_hint="Nothing generated yet. Select an object and press Capture views, or add a front view and one more, then Generate.",
)

THREE_D_EDIT = Lane(
    id="3d_edit",
    label="3D",
    modality="3d",
    capabilities=("3d23d",),
    recommend="3d23d",
    # Every task's picks; the page shows the current task's (core/edits.py).
    quick_picks=tuple(model for task in edits.TASKS for model in task.quick_picks),
    starter_prompt="",
    examples=(),
    destination="Saved under scenario/<date> in the project. Import places the result over the mesh it came from, as a new group.",
    results="model",
    formats=("glb",),
    tab="3d",
    mode="Edit selection",
    inputs="mesh",
    empty_hint="Nothing edited yet. Select a mesh, choose a task, then Use selection and Generate.",
    without_tags=("motion",),  # Cartwheel Text to Motion is 3d23d too
)

THREE_D_MOTION = Lane(
    id="3d_motion",
    label="3D",
    modality="3d",
    capabilities=("txt23d",),
    recommend="txt23d",
    quick_picks=MOTION_PICKS,
    starter_prompt="waves hello with the right hand",
    examples=(
        "walks forward, then sits down on the floor",
        "a boxer's jab, then a cross",
        "a tired zombie shambling forward",
    ),
    destination="Saved under scenario/<date> in the project. Imports as a new character with its joints, skin and clip, on the ground at the camera's centre of interest; the clip starts on the scene's start frame.",
    results="model",
    formats=("glb", "fbx"),
    presets=MOTION_PRESETS,
    tab="3d",
    mode="Motion",
    inputs="character",
    empty_hint="Nothing animated yet. Describe a motion and press Generate. To animate your own character, select its meshes and press Use selection first.",
    tags=("motion",),
)

LANES = (IMAGE, THREE_D, THREE_D_IMAGE, THREE_D_VIEWS, THREE_D_EDIT, THREE_D_MOTION)
BY_ID = {lane.id: lane for lane in LANES}


def tab_lanes(tab_id: str) -> tuple:
    return tuple(lane for lane in LANES if lane.tab_id == tab_id)


def tabs() -> tuple:
    """Tab ids in panel order."""
    return tuple(dict.fromkeys(lane.tab_id for lane in LANES))


def lane_for_model(capabilities, tags=()) -> Lane | None:
    caps = set(capabilities or ())
    return next((lane for lane in LANES if caps & set(lane.capabilities) and takes_tags(lane, tags)), None)


def takes_tags(lane: Lane, tags) -> bool:
    """Whether a model with these catalog tags belongs in ``lane`` (tags compared in lowercase)."""
    words = {str(tag).lower() for tag in tags or ()}
    if lane.without_tags and words & set(lane.without_tags):
        return False
    return not lane.tags or bool(words & set(lane.tags))
