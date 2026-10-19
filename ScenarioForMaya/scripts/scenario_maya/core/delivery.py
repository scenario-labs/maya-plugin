"""From a sent job to files on disk (spec 7.4): follow, then download.

``follow`` reads the Scenario job every 2 s until it finishes. On a timeout, a
lost connection, 408, 429 or 5xx the next read waits 4, 8, 16, 32, then 60 s
(or ``Retry-After``, up to 300 s) and the row says "Status not refreshed;
retrying". After eight such failures in a row, or any other error, delivery
pauses for review: the job keeps its state and nothing is sent again.

``download_results`` moves a finished job to ``downloading`` then ``ready``,
with one receipt per file (``downloads.py``) and a ``scenario.json`` sidecar
holding the provenance and receipts. Files that are already there with the
same hash are kept, never downloaded twice. A 3D job returns several files
(GLB, OBJ, MTL, textures): with ``formats`` only the preferred format is
downloaded, chosen by each asset record's format, never by its position.

Both block; the Maya layer runs them on workers. Neither touches Maya.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from . import downloads, errors, naming

INTERVAL = 2.0
BACKOFF = (4.0, 8.0, 16.0, 32.0, 60.0)
MAX_TRANSIENT = 8
_RUNNING = ("remote", "cancel_requested")


def _transient(error: errors.ScenarioError) -> bool:
    return error.retryable or isinstance(error, errors.Offline)


def follow(
    session,
    local_id: str,
    *,
    on_update: Callable[[dict, str], None] | None = None,
    cancel: threading.Event | None = None,
    interval: float = INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Returns the row once the job left ``remote`` (or ``cancel`` was set)."""
    failures = 0
    row = session.ledger.get(local_id)
    while row is not None and row["state"] in _RUNNING:
        if cancel is not None and cancel.is_set():
            return row
        try:
            row = session.refresh_job(local_id)
            failures = 0
            note = ""
        except errors.ScenarioError as error:
            if not _transient(error):
                session.ledger.update_fields(local_id, hint=f"Delivery paused: {error.message}")
                raise
            failures += 1
            if failures >= MAX_TRANSIENT:
                session.ledger.update_fields(local_id, hint="Delivery paused: the status could not be read eight times in a row.")
                raise
            wait = min(error.retry_after, 300.0) if error.retry_after else BACKOFF[min(failures, len(BACKOFF)) - 1]
            note = f"Status not refreshed; retrying in {int(wait)} s"
            row = session.ledger.get(local_id)
            if on_update is not None:
                on_update(row, note)
            sleep(wait)
            continue
        if on_update is not None:
            on_update(row, note)
        if row["state"] in _RUNNING:
            sleep(interval)
    return row


MIME_FORMATS = {
    "model/gltf-binary": "glb",
    "model/gltf+json": "gltf",
    "model/obj": "obj",
    "model/mtl": "mtl",
    "application/vnd.autodesk.fbx": "fbx",
    "application/x-fbx": "fbx",
    "model/x-fbx": "fbx",
}


def asset_format(record: dict) -> str:
    """``glb``, ``obj``, ``fbx``... from an asset record (``metadata.format``, else its MIME type)."""
    for source in (record.get("metadata"), record.get("properties"), record):
        if isinstance(source, dict) and source.get("format"):
            return str(source["format"]).lower()
    return MIME_FORMATS.get(str(record.get("mimeType") or "").split(";", 1)[0].strip().lower(), "")


def _facts(record: dict) -> dict:
    """What the card shows before an import: format, faces, size in metres."""
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    out = {"format": asset_format(record)}
    if isinstance(meta.get("faceCount"), (int, float)):
        out["faces"] = int(meta["faceCount"])
    dims = meta.get("dimensions")
    if isinstance(dims, list) and len(dims) == 3 and all(isinstance(v, (int, float)) for v in dims):
        out["size_m"] = [round(float(v), 4) for v in dims]
    return out


def pick_assets(backend, asset_ids: list, formats: tuple) -> tuple:
    """``(chosen ids, facts by id, thumbnail url)``: the assets of the first format in ``formats`` that the job returned.

    With no match every asset is kept, so the files are still saved and the
    import can say what it received.
    """
    records = {asset_id: backend.asset(asset_id) or {} for asset_id in asset_ids}
    chosen = list(asset_ids)
    for fmt in formats:
        matching = [asset_id for asset_id in asset_ids if asset_format(records[asset_id]) == fmt]
        if matching:
            chosen = matching
            break
    thumb = (records[chosen[0]].get("thumbnail") or {}).get("url") if chosen else ""
    return chosen, {asset_id: _facts(records[asset_id]) for asset_id in chosen}, thumb or ""


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def result_folder(root: str, row: dict, first_asset_id: str) -> str:
    """``<root>/<slug>_<tail>``: the prompt's first words and the asset id's last characters."""
    params = row.get("params") or {}
    base = f"{naming.slug(str(params.get('prompt') or row.get('label') or row.get('target_name') or 'scenario'))}_{naming.tail(first_asset_id)}"
    return os.path.join(root, base)


def download_results(
    session,
    local_id: str,
    root: str,
    *,
    provenance: dict | None = None,
    convert: dict | None = None,
    formats: tuple = (),
    progress: Callable[[int, int, int], None] | None = None,
    cancel: threading.Event | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Downloads every result asset of a finished job into one folder under ``root``.

    ``convert`` maps a delivered MIME type to a format Scenario converts to
    (``{"image/webp": "png"}``: Maya's file node cannot read WebP).
    ``formats`` (``("glb",)``) downloads only the assets of the first format
    the job returned, plus the result's thumbnail; the choice is kept on the job.
    ``progress(index, received, total)`` reports per file. Returns the ``ready`` row.
    """
    row = session.ledger.get(local_id)
    if row is None:
        raise errors.NotFound(f"No local job {local_id}.")
    if row["state"] not in ("succeeded", "download_failed", "ready", "applied"):
        raise errors.Refused(f"Job {local_id} has no finished result to download ({row['state']}).")
    result = dict(row.get("result") or {})
    if not result.get("asset_ids"):
        raise errors.ProtocolError("Scenario finished the job without a result file.")
    backend = session.backend()
    thumb = ""
    if formats and "picked" not in result:
        picked, facts, thumb = pick_assets(backend, list(result["asset_ids"]), formats)
        result.update(picked=picked, facts=facts)
    asset_ids = list(result.get("picked") or result["asset_ids"])
    facts = result.get("facts") or {}
    kept = {item["asset_id"]: item for item in result.get("files") or [] if downloads.verify(item)}
    if row["state"] in ("ready", "applied") and len(kept) == len(asset_ids):
        return row
    if formats and not thumb and not result.get("thumbnail"):
        thumb = _thumbnail_url(backend, asset_ids[0])  # signed links expire: read again, never stored
    folder = result.get("folder") or naming.unique_folder(*os.path.split(result_folder(root, row, asset_ids[0])))
    os.makedirs(folder, exist_ok=True)
    row = session.ledger.set_state(local_id, "downloading", f"{len(asset_ids)} file(s)", result_json=dict(result, folder=folder))
    files = []
    stem = os.path.basename(folder)
    try:
        for index, asset_id in enumerate(asset_ids):
            if asset_id in kept:
                files.append(kept[asset_id])
                continue
            first = backend.download_url(asset_id)
            fmt = (convert or {}).get((first.get("mime_type") or "").lower(), "")
            if fmt:
                first = backend.download_url(asset_id, fmt)
            links = [first]

            def get_link(asset_id=asset_id, links=links, fmt=fmt):
                return links.pop() if links else backend.download_url(asset_id, fmt)

            name = stem if len(asset_ids) == 1 else f"{stem}_{index + 1}"
            path = _part_or_new(folder, name, naming.extension_for(first.get("mime_type", ""), first.get("url", "").split("?", 1)[0]))
            receipt = downloads.download(
                get_link,
                path,
                progress=(lambda got, total, index=index: progress(index, got, total)) if progress else None,
                cancel=cancel,
                sleep=sleep,
            )
            receipt["asset_id"] = asset_id
            receipt.update(facts.get(asset_id) or {})
            files.append(receipt)
    except downloads.Cancelled:
        session.ledger.set_state(local_id, "download_failed", "stopped", result_json=dict(result, folder=folder, files=files), error="Download stopped.")
        raise
    except errors.ScenarioError as error:
        session.ledger.set_state(local_id, "download_failed", error.message, result_json=dict(result, folder=folder, files=files), error=error.message, hint=error.hint)
        raise
    result.update(folder=folder, files=files)
    if thumb and not result.get("thumbnail"):
        result["thumbnail"] = _thumbnail(thumb, folder, stem, cancel, sleep)
    write_sidecar(folder, row, files, provenance or {})
    return session.ledger.set_state(local_id, "ready", "downloaded", result_json=result, error="", hint="")


def late_thumbnail(session, local_id: str, *, attempts: int = 4, wait: float = 5.0, cancel: threading.Event | None = None, sleep: Callable[[float], None] = time.sleep) -> dict | None:
    """The preview picture of a downloaded 3D result that had none yet.

    Scenario renders 3D previews a few seconds after the job ends (Meshy 7.1:
    9 s after the asset was written), so the asset is read again a few times.
    Returns the updated row, or None while there is still no picture. Best
    effort: the result itself is never touched.
    """
    row = session.ledger.get(local_id) or {}
    result = row.get("result") or {}
    files = result.get("files") or []
    if not files or result.get("thumbnail") or not files[0].get("asset_id"):
        return None
    backend = session.backend()
    folder = result.get("folder") or os.path.dirname(files[0]["path"])
    for attempt in range(attempts):
        if attempt:
            sleep(wait)
        if cancel is not None and cancel.is_set():
            return None
        url = _thumbnail_url(backend, files[0]["asset_id"])
        if url:
            path = _thumbnail(url, folder, os.path.basename(folder.rstrip(os.sep)), cancel, sleep)
            return session.ledger.merge_result(local_id, thumbnail=path) if path else None
    return None


def _thumbnail_url(backend, asset_id: str) -> str:
    try:
        return ((backend.asset(asset_id) or {}).get("thumbnail") or {}).get("url") or ""
    except errors.ScenarioError:
        return ""


def _thumbnail(url: str, folder: str, stem: str, cancel, sleep) -> str:
    """The result's preview picture for the card. Best effort: a failure leaves the card without one."""
    path = _part_or_new(folder, stem + "_thumb", ".jpg")
    try:
        downloads.download(lambda: {"url": url, "mime_type": "image/jpeg"}, path, cancel=cancel, attempts=2, sleep=sleep)
    except (errors.ScenarioError, downloads.Cancelled, OSError):
        return ""
    return path


def _part_or_new(folder: str, name: str, ext: str) -> str:
    """Resumes an interrupted ``.part`` of the same name, else picks a free name."""
    candidate = os.path.join(folder, name + ext)
    if os.path.exists(candidate + ".part") and not os.path.exists(candidate):
        return candidate
    return naming.unique_path(folder, name, ext)


def write_sidecar(folder: str, row: dict, files: list, provenance: dict) -> str:
    """``scenario.json``: where the files came from, with their receipts. No secrets, no signed links."""
    data = {
        "schema": "scenario-maya/result@1",
        "written_utc": _utc_now(),
        "job": {
            "local_id": row.get("local_id"),
            "job_id": row.get("remote_job_id"),
            "model_id": row.get("target_id"),
            "model_name": row.get("target_name"),
            "quoted_cu": row.get("cost_exact"),
            "charged_cu": row.get("charged_exact"),
            "workspace": row.get("workspace"),
        },
        "provenance": provenance,
        "files": [{k: v for k, v in item.items() if k != "path"} for item in files],
    }
    path = os.path.join(folder, "scenario.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return path
