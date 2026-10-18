"""Names for files, folders and Maya nodes (spec 10.1 and 10.2).

Maya drops leading digits from node names, turns other characters into ``_``
and non-ASCII into ``?``, so every name is made ASCII here first:
``[A-Za-z_][A-Za-z0-9_]*``. Files never overwrite: a taken name gets a numeric
suffix.
"""

from __future__ import annotations

import os
import re
import unicodedata

_SKIP = {"a", "an", "the", "of", "and", "with", "in", "on", "for", "to", "at", "by"}

EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/tiff": ".tif",
    "image/x-exr": ".exr",
    "image/exr": ".exr",
    "image/vnd.radiance": ".hdr",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "model/gltf-binary": ".glb",
    "model/gltf+json": ".gltf",
    "model/obj": ".obj",
    "application/x-fbx": ".fbx",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
}


def slug(text: str, words: int = 4, fallback: str = "scenario", max_length: int = 40) -> str:
    """``"A carved wooden treasure chest, game prop"`` -> ``"carved_wooden_treasure_chest"``."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", plain.lower()) if token]
    chosen = [token for token in tokens if token not in _SKIP][:words] or tokens[:words]
    out = "_".join(chosen)[:max_length].strip("_")
    if not out:
        out = fallback
    if out[0].isdigit():
        out = "n" + out
    return out


def node_name(text: str) -> str:
    """Any string to a valid Maya node name, keeping case."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    out = re.sub(r"[^A-Za-z0-9_]+", "_", plain).strip("_") or "scenario"
    return "n" + out if out[0].isdigit() else out


def tail(asset_id: str, length: int = 6) -> str:
    """The last characters of a Scenario id, so names stay unique and traceable."""
    core = re.sub(r"[^A-Za-z0-9]", "", (asset_id or "").split("_", 1)[-1])
    return core[-length:] or "000000"


def extension_for(mime_type: str, url_path: str = "", fallback: str = ".bin") -> str:
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if mime in EXTENSIONS:
        return EXTENSIONS[mime]
    _root, ext = os.path.splitext(url_path or "")
    if re.fullmatch(r"\.[A-Za-z0-9]{2,5}", ext or ""):
        return ext.lower()
    return fallback


def unique_path(folder: str, name: str, ext: str) -> str:
    """``folder/name.ext``, or ``name_2.ext``, ``name_3.ext``... if taken (``.part`` files count)."""
    candidate = os.path.join(folder, name + ext)
    number = 2
    while os.path.exists(candidate) or os.path.exists(candidate + ".part"):
        candidate = os.path.join(folder, f"{name}_{number}{ext}")
        number += 1
    return candidate


def unique_folder(parent: str, name: str) -> str:
    candidate = os.path.join(parent, name)
    number = 2
    while os.path.exists(candidate):
        candidate = os.path.join(parent, f"{name}_{number}")
        number += 1
    return candidate
