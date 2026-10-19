"""Sent jobs to files on disk to nodes in the scene, without blocking Maya.

``JobRunner.generate`` spends one quote on a worker, then ``track`` follows
the job and downloads its results on a worker too. Every change is announced
on the main thread as a ``job`` event (``row``, ``note``, ``progress``), which
the panel, the Jobs view and the agent server listen to. ``land`` runs on the
main thread: it puts a downloaded result in the scene in one undo step and
records it on the job.

Recovery (spec 7.4): nothing resumes by itself at load. ``resume_polling``
(when the panel opens) follows jobs that were running on Scenario;
``resume_downloads`` (the "Resume my jobs" banner, Retry download) fetches
results that finished while Maya was closed.
"""

from __future__ import annotations

import os
import threading
import time

from ..core import delivery, errors, lanes, naming, provenance
from . import compat, landing, scene

CONVERT = {"image/webp": "png", "image/avif": "png", "image/heif": "png"}
_PROGRESS_EVERY = 0.2


def lane_of(row: dict) -> lanes.Lane:
    return lanes.BY_ID.get((row.get("origin") or {}).get("lane") or "", lanes.IMAGE)


def result_root(lane: lanes.Lane) -> str:
    """Images go where textures live; 3D originals under ``scenario/<date>`` (spec 10.1)."""
    return scene.folders()["originals" if lane.results == "model" else "images"]


class JobRunner:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.session = runtime.session
        self.ledger = runtime.ledger
        self._active: dict = {}
        self._lock = threading.Lock()

    # -- events ----------------------------------------------------------

    def _announce(self, row: dict, note: str = "", progress: float | None = None) -> None:
        if row is None:
            return
        self.runtime.dispatcher.call_on_main(self.runtime.emit, "job", row=row, note=note, progress=progress)

    def active(self) -> list:
        with self._lock:
            return list(self._active)

    # -- sending ---------------------------------------------------------

    def generate(self, quote_id: str, *, approved_cost: str, params: dict, origin: dict, model_name: str, label: str = "", driver: str = "person", on_sent=None, on_error=None):
        """Spends the quote on a worker; on success the job is tracked. Callbacks run on the main thread."""
        root = result_root(lanes.BY_ID.get(origin.get("lane") or "", lanes.IMAGE))

        def send():
            return self.session.submit(quote_id, approved_cost=approved_cost, params=params, origin=origin, driver=driver, label=label, model_name=model_name)

        def sent(row):
            self._announce(row, "Sent to Scenario")
            self.track(row["local_id"], root=root)
            if on_sent is not None:
                on_sent(row)

        return self.runtime.background(send, on_done=sent, on_error=on_error)

    # -- following and downloading ----------------------------------------

    def track(self, local_id: str, root: str | None = None) -> bool:
        """Follows and downloads one job on a worker. False when it is already tracked."""
        lane = lane_of(self.ledger.get(local_id) or {})
        root = root or result_root(lane)
        info = {"scene_uuid": scene.scene_uuid(create=False), "maya_version": compat.maya_version()}
        with self._lock:
            if local_id in self._active:
                return False
            cancel = threading.Event()
            self._active[local_id] = cancel

        def work():
            try:
                return self._deliver(local_id, root, info, cancel, lane.formats)
            finally:
                with self._lock:
                    self._active.pop(local_id, None)

        def failed(error):
            row = self.ledger.get(local_id)
            message = error.message if isinstance(error, errors.ScenarioError) else f"{type(error).__name__}: {error}"
            self._announce(row, message)

        self.runtime.background(work, on_error=failed)
        return True

    def _deliver(self, local_id: str, root: str, info: dict, cancel: threading.Event, formats: tuple = ()) -> dict:
        row = delivery.follow(self.session, local_id, on_update=lambda r, note: self._announce(r, note), cancel=cancel)
        if cancel.is_set() or row["state"] not in ("succeeded", "downloading", "download_failed"):
            return row
        last = [0.0]

        def progress(index, received, total):
            now = time.monotonic()
            if total and (now - last[0] >= _PROGRESS_EVERY or received >= total):
                last[0] = now
                self._announce(dict(row, state="downloading"), f"file {index + 1}", received / total)

        row = delivery.download_results(self.session, local_id, root, provenance=info, convert=CONVERT, formats=formats, progress=progress, cancel=cancel)
        self._announce(row, "Ready")
        if formats and not (row.get("result") or {}).get("thumbnail"):
            later = delivery.late_thumbnail(self.session, local_id, cancel=cancel)
            if later is not None:
                self._announce(later)
        return row

    def resume_polling(self) -> int:
        rows = self.ledger.list(states=("remote", "cancel_requested"), workspace=self.session.workspace() or None)
        return sum(self.track(row["local_id"]) for row in rows)

    def resume_downloads(self) -> int:
        rows = self.ledger.list(states=("succeeded", "downloading", "download_failed"), workspace=self.session.workspace() or None)
        return sum(self.track(row["local_id"]) for row in rows)

    def waiting_downloads(self) -> list:
        return [row for row in self.ledger.list(states=("succeeded", "downloading", "download_failed"), workspace=self.session.workspace() or None) if row["local_id"] not in self._active]

    def stop(self) -> None:
        with self._lock:
            for cancel in self._active.values():
                cancel.set()

    # -- landing ---------------------------------------------------------

    def land(self, local_id: str, mode: str, index: int = 0, *, select: bool = True, camera=None, targets=None) -> dict:
        """Main thread. Lands one downloaded file; the job row records it.

        ``mode`` is ``card``, ``material`` or ``image_plane`` for images and
        ``model`` for 3D results (a new group on the ground at the camera's
        centre of interest; textures under ``sourceimages/scenario``).
        """
        row = self.ledger.get(local_id)
        if row is None:
            raise errors.NotFound(f"No local job {local_id}.")
        files = (row.get("result") or {}).get("files") or []
        if row["state"] not in ("ready", "applied", "apply_failed") or index >= len(files):
            raise landing.LandingError("Nothing was imported: this result is not downloaded yet.")
        item = files[index]
        attrs = provenance.attributes(
            row,
            item.get("asset_id", ""),
            maya_version=compat.maya_version(),
            apply="import" if mode == "model" else mode,
            store_prompt=bool(self.runtime.settings.get("store_prompts_on_nodes", True)),
        )
        label = str((row.get("params") or {}).get("prompt") or row.get("label") or "")
        if mode == "material" and targets is None:
            targets = scene.selected_surfaces()
            if not targets:
                raise landing.LandingError("Nothing was applied: select a mesh or faces first.")
        self.ledger.set_state(local_id, "applying", mode)
        try:
            if mode == "model":
                folder = (row.get("result") or {}).get("folder") or item["path"]
                textures = naming.unique_folder(scene.folders()["images"], os.path.basename(folder.rstrip(os.sep)))
                if lane_of(row).inputs == "mesh":  # an edit: over the mesh it came from, fitted (maya/apply.py)
                    from . import apply

                    over = apply.import_over_target(row, item["path"])
                    made = landing.land_model(item["path"], attrs, texture_folder=textures, label=label, select=select, matrix=over["matrix"], over=over["target_name"])
                    if over["note"]:
                        made["checks"].setdefault("notes", []).append(over["note"])
                else:
                    made = landing.land_model(item["path"], attrs, texture_folder=textures, label=label, select=select, place=scene.interest_point(camera))
            else:
                made = landing.land(item["path"], attrs, mode, label=label, camera=camera, targets=targets, select=select)
        except Exception as error:
            message = error.args[0] if isinstance(error, landing.LandingError) and error.args else f"{type(error).__name__}: {error}"
            failed = self.ledger.set_state(local_id, "apply_failed", message, error=message)
            self._announce(failed, message)
            raise
        landed = list((row.get("result") or {}).get("landed") or [])
        landed.insert(0, {"mode": mode, "index": index, "top": made.get("top") or made.get("material"), "namespace": made.get("namespace"), "scene_uuid": scene.scene_uuid()})
        result = dict(row.get("result") or {}, landed=landed[:20])
        done = self.ledger.set_state(local_id, "applied", made.get("summary", mode), result_json=result, error="")
        self._announce(done, made.get("summary", ""))
        return made

    def review_apply(self, local_id: str, mode: str = "", on_done=None, on_error=None) -> None:
        """Main thread: reads the target now, then proves the result on a worker; ``on_done(review)`` on the main thread."""
        from . import apply

        row = self.ledger.get(local_id)
        if row is None:
            raise errors.NotFound(f"No local job {local_id}.")
        files = (row.get("result") or {}).get("files") or []
        if row["state"] not in ("ready", "applied", "apply_failed") or not files:
            raise landing.LandingError("Nothing was applied: this result is not downloaded yet.")
        gathered = apply.gather(row, mode)
        path = files[0]["path"]
        self.runtime.background(lambda: apply.compare(gathered, path), on_done=on_done, on_error=on_error)

    def apply_edit(self, local_id: str, review) -> dict:
        """Main thread: the reviewed edit onto the mesh, one undo step; the job row records it."""
        from . import apply

        row = self.ledger.get(local_id)
        if row is None:
            raise errors.NotFound(f"No local job {local_id}.")
        files = (row.get("result") or {}).get("files") or []
        attrs = provenance.attributes(
            row,
            (files[0] if files else {}).get("asset_id", ""),
            maya_version=compat.maya_version(),
            apply=review.mode.lower(),
            store_prompt=bool(self.runtime.settings.get("store_prompts_on_nodes", True)),
        )
        suffix = {"RETEXTURE": "retexture", "REMESH": "remesh"}.get(review.mode)
        folder = naming.unique_folder(scene.folders()["images"], naming.slug(f"{review.name}_{suffix}")) if suffix else ""
        self.ledger.set_state(local_id, "applying", review.mode)
        try:
            made = apply.run(review, attrs, texture_folder=folder)
        except Exception as error:
            message = error.args[0] if isinstance(error, landing.LandingError) and error.args else f"{type(error).__name__}: {error}"
            failed = self.ledger.set_state(local_id, "apply_failed", message, error=message)
            self._announce(failed, message)
            raise
        landed = list((row.get("result") or {}).get("landed") or [])
        landed.insert(0, {"mode": review.mode.lower(), "index": 0, "top": review.target, "material": made.get("material"), "scene_uuid": scene.scene_uuid()})
        result = dict(row.get("result") or {}, landed=landed[:20])
        done = self.ledger.set_state(local_id, "applied", made["summary"], result_json=result, error="")
        self._announce(done, made["summary"])
        return made
