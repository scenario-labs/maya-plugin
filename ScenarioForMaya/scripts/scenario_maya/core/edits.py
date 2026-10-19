"""3D edits of the user's own meshes (spec 6.3, 6.4): the tasks, what each
edit model accepts, and the checks made before a mesh is sent.

Price checks do not validate mesh formats or face caps (a GLB priced fine on
an FBX-only model, then failed after submission), so the plug-in keeps its
own table, read from each model's schema text, and refuses before uploading.
GLB caps count triangles: a GLB holds nothing else.
"""

from __future__ import annotations

import array
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: str
    label: str
    apply_mode: str  # the default apply (spec 6.4 mesh_policy)
    quick_picks: tuple
    needs_prompt: bool = False
    hint: str = ""


@dataclass(frozen=True)
class EditModel:
    task: str
    field: str = "model"
    formats: tuple = ("glb",)
    max_triangles: int = 0  # 0: no cap documented
    note: str = ""


# Defaults from `recommend` (quality) and the newest-first catalog on 2026-10-19:
# Tripo Retopology v3, Tripo Smart UV and Meshy 7 Retexture rank first; the
# runners-up are cheaper (spec 6.3).
TASKS = (
    Task(
        "remesh",
        "Remesh",
        "REMESH",
        ("model_tripo-retopology-v3", "model_meshy-remesh", "model_tencent-smarttopology"),
        hint="Rebuilds the mesh with clean topology at a face budget; textures are baked onto the new mesh by models that can.",
    ),
    Task(
        "uv",
        "UV unwrap",
        "UV",
        ("model_tripo-smart-uv", "model_tencent-uv-unwrapping", "model_meshy-uv-unwrap"),
        hint="New UVs on the same surface. Apply replaces the UV set and keeps the old one as a backup.",
    ),
    Task(
        "retexture",
        "Retexture",
        "RETEXTURE",
        ("model_meshy-7-retexture", "model_tripo-v3-0-texturing"),
        needs_prompt=True,
        hint="New PBR textures from a prompt, on the mesh's own UVs when it has them.",
    ),
)
BY_TASK = {task.id: task for task in TASKS}

MODELS = {
    "model_tripo-retopology-v3": EditModel("remesh"),
    "model_meshy-remesh": EditModel("remesh"),
    "model_tencent-smarttopology": EditModel("remesh", field="file3d", formats=("glb", "obj")),
    "model_tripo-smart-uv": EditModel("uv", max_triangles=80000),
    "model_tencent-uv-unwrapping": EditModel("uv", field="file3d", formats=("glb", "fbx", "obj"), max_triangles=30000),
    "model_meshy-uv-unwrap": EditModel("uv", max_triangles=44000, note="returns an untextured model"),
    "model_meshy-7-retexture": EditModel("retexture"),
    "model_tripo-v3-0-texturing": EditModel("retexture"),
    "model_tencent-texture-edit": EditModel("retexture", field="file3d", formats=("fbx",), max_triangles=100000),
}


def task_for_model(model_id: str) -> Task | None:
    known = MODELS.get(model_id)
    return BY_TASK.get(known.task) if known else None


def check(model_id: str, model_name: str, capture: dict) -> list:
    """Why this captured mesh cannot go to this model, in plain words; empty when it can.

    ``capture`` is the record ``maya/mesh_export.export`` returns.
    """
    known = MODELS.get(model_id)
    if known is None or not capture:
        return []
    problems = []
    fmt = capture.get("format") or "glb"
    if fmt not in known.formats:
        problems.append(f"{model_name} takes {'/'.join(f.upper() for f in known.formats)} only; the plug-in sends {fmt.upper()}.")
    triangles = int(capture.get("triangles") or 0)
    if known.max_triangles and triangles > known.max_triangles:
        problems.append(f"{model_name} takes up to {known.max_triangles:,} triangles; the selection has {triangles:,}. Remesh it first.")
    return problems


def fingerprint(*parts) -> str:
    """SHA-256 over numeric sequences (points, counts, ids, UVs): any change to the mesh changes it."""
    digest = hashlib.sha256()
    for part in parts:
        values = list(part)
        code = "d" if any(isinstance(value, float) for value in values[:64]) else "q"
        digest.update(code.encode() + len(values).to_bytes(8, "little"))
        digest.update(array.array(code, values).tobytes())
    return digest.hexdigest()
