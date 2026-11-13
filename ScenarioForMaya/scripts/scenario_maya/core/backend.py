"""What the plug-in needs from Scenario, and its implementation over the REST API.

``ScenarioBackend`` names every call; ``RestBackend`` implements it with
Scenario's Python SDK through ``RestClient``. Replies are read as the API's
JSON, defensively (several field spellings are accepted); the recorded
fixtures and the weekly contract check catch drift.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from . import errors
from .http import is_secure_url
from .jsonutil import cu_exact
from .rest import RestClient
from .schema import ModelForm

# Capabilities that produce each modality: a model belongs to a modality when any of its
# capabilities is listed (the API has no modality filter).
MODALITY_CAPABILITIES = {
    "image": {"txt2img", "img2img", "inpaint", "outpaint", "reference", "video2img", "txt2img_texture", "img2img_texture", "reference_texture"},
    "video": {"txt2video", "img2video", "video2video", "audio2video"},
    "3d": {"3d23d", "img23d", "txt23d", "video23d"},
    "audio": {"txt2audio", "audio2audio", "video2audio"},
}
ARRAY_TYPES = ("file_array", "string_array", "model_array", "number_array", "inputs_array")
UPLOAD_PART_SIZE = 6_000_000  # every part but the last must be at least 5 MiB
_UPLOAD_RACES = ("unable to load request upload id", "unable to complete upload with status")


def job_id_in(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("job_id", "jobId"):
        if value.get(key):
            return str(value[key])
    for key in ("job", "inference"):
        inner = value.get(key)
        if isinstance(inner, dict):
            found = inner.get("jobId") or inner.get("id") or inner.get("job_id")
            if found:
                return str(found)
    return ""


def cost_in(value: dict) -> str | None:
    billing = value.get("billing")
    details = billing.get("cuCostDetails") if isinstance(billing, dict) else None
    if isinstance(details, dict) and details:
        # A job's cuCost is its main action only; add-ons (quality gate, IP detection) are charged beside it.
        try:
            return cu_exact(sum((Decimal(cu_exact(amount)) for amount in details.values()), Decimal(0)))
        except ValueError:
            return None
    for key in ("creativeUnitsCost", "cuCost", "cu_cost", "cost"):
        if key in value and value[key] is not None:
            try:
                return cu_exact(value[key])
            except ValueError:
                return None
    billing = value.get("billing")
    if isinstance(billing, dict) and billing.get("cuCost") is not None:
        return cu_exact(billing["cuCost"])
    return None


def normalize_job(row: dict) -> dict:
    """One shape for job rows from ``GET /jobs/{id}`` and ``GET /jobs``."""
    if "job" in row and isinstance(row["job"], dict):
        row = row["job"]
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    given = meta.get("input") if isinstance(meta.get("input"), dict) else {}
    status = str(row.get("status") or "").lower()
    out = {
        "job_id": job_id_in(row) or str(row.get("id") or ""),
        "status": status,
        "progress": row.get("progress"),
        "model_id": row.get("modelId") or given.get("modelId") or row.get("model_id") or "",
        "job_type": row.get("jobType") or "",
        "asset_ids": list(row.get("assetIds") or meta.get("assetIds") or row.get("asset_ids") or []),
        "cu_cost": cost_in(row),
        "error": row.get("error") or meta.get("error") or "",
        "hint": row.get("hint") or meta.get("hint") or "",
        "workflow_id": row.get("workflowId") or meta.get("workflowId") or "",
        "created_at": row.get("createdAt") or "",
        "updated_at": row.get("updatedAt") or "",
    }
    out["finished"] = status in ("success", "failure", "canceled")
    return out


def schema_from_model(model: dict) -> dict:
    """``GET /models/{id}`` to the parameter list ``ModelForm`` reads (snake_case, plain booleans)."""
    return {
        "model_id": model.get("id") or "",
        "name": model.get("name") or "",
        "capabilities": list(model.get("capabilities") or []),
        "parameters": [_parameter(item) for item in model.get("inputs") or [] if isinstance(item, dict) and item.get("name")],
    }


def _parameter(raw: dict) -> dict:
    required = raw.get("required")
    out: dict = {"name": raw["name"], "type": raw.get("type") or "string", "required": bool(required.get("always")) if isinstance(required, dict) else bool(required)}
    if raw.get("description") or raw.get("label"):
        out["description"] = raw.get("description") or raw.get("label")
    renames = {
        "default": "default",
        "allowedValues": "allowed_values",
        "min": "min",
        "max": "max",
        "minLength": "min_length",
        "maxLength": "max_length",
        "step": "step",
        "maxSize": "max_size",
        "maxDuration": "max_duration",
        "modelTypes": "model_types",
    }
    for source, target in renames.items():
        if raw.get(source) is not None:
            out[target] = raw[source]
    for source, target in (("kind", "kind"), ("costImpact", "cost_impact"), ("promptSpark", "prompt_spark"), ("prompt", "prompt")):
        if raw.get(source):
            out[target] = raw[source]
    if out["type"] in ARRAY_TYPES:
        out["array"] = True
    if raw.get("inputs"):
        out["fields"] = [_parameter(item) for item in raw["inputs"] if isinstance(item, dict) and item.get("name")]
    return out


def upload_name(name: str) -> str:
    """Lower-case words joined by dashes, extension kept: signed upload links break on spaces and brackets."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "file"
    return slug + ("." + re.sub(r"[^a-z0-9]", "", ext.lower()) if ext else "")


class ScenarioBackend:
    """Interface. Every method blocks; call from a worker thread."""

    def teams(self) -> list: ...
    def projects(self, team_id: str) -> list: ...
    def models(self, *, privacy: str = "public", modality: str = "", limit: int = 100, page_token: str = "") -> tuple: ...
    def model_form(self, model_id: str) -> ModelForm: ...
    def estimate(self, model_id: str, params: dict) -> str: ...
    def run(self, model_id: str, params: dict) -> str: ...
    def job(self, job_id: str) -> dict: ...
    def jobs(self, *, limit: int = 20, status: str = "", page_token: str = "") -> tuple: ...
    def asset(self, asset_id: str) -> dict: ...
    def download_url(self, asset_id: str, fmt: str = "") -> dict: ...
    def upload_start(self, file_name: str, content_type: str, kind: str, size: int) -> dict: ...
    def upload_complete(self, upload_id: str) -> dict: ...


def _given(**values) -> dict:
    """SDK keyword arguments without the empty ones (the SDK leaves out what is not passed)."""
    return {key: value for key, value in values.items() if value not in (None, "")}


class RestBackend(ScenarioBackend):
    def __init__(self, client: RestClient, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client = client
        self._sleep = sleep

    def _read(self, op: Callable, *, workspace: str = "project", name: str = "", timeout: float = 60.0) -> dict:
        return self.client.call(op, workspace=workspace, name=name, timeout=timeout).data

    # -- workspace -------------------------------------------------------

    def teams(self) -> list:
        """Teams with their projects. An API key reads only its own project (``/teams`` is not open to keys)."""
        if getattr(self.client.auth, "kind", "") == "api_key":
            project, token, seen = None, "", set()
            # Pages are filtered after paging: an empty page may still have a next one.
            while project is None and token not in seen:
                seen.add(token)
                data = self._read(lambda c, q, token=token: c.projects.with_raw_response.list(**_given(page_size=100, pagination_token=token), extra_query=q), workspace="none")
                project = next((p for p in data.get("projects") or [] if isinstance(p, dict) and p.get("id")), None)
                token = data.get("nextPaginationToken") or ""
                if not token:
                    break
            if project is None:
                return []
            # The answer lists the project's members and keys: only the names and ids are kept.
            kept = {"id": project["id"], "name": project.get("name") or ""}
            return [{"id": project.get("teamId") or "", "name": project.get("teamName") or "", "projects": [kept]}]
        # Unscoped on purpose: with a stale projectId the gateway refuses the whole read.
        data = self._read(lambda c, q: c.teams.with_raw_response.list(extra_query=q), workspace="none")
        return [team for team in data.get("teams") or [] if isinstance(team, dict)]

    def projects(self, team_id: str) -> list:
        out, token = [], ""
        for _ in range(20):
            # The team only: with a projectId the API would list that project's team instead.
            data = self._read(lambda c, q, token=token: c.projects.with_raw_response.list(**_given(team_id=team_id, page_size=100, pagination_token=token), extra_query=q), workspace="none")
            out.extend(p for p in data.get("projects") or [] if isinstance(p, dict))
            token = data.get("nextPaginationToken") or ""
            if not token:  # pages are filtered after paging, so a short page is not the end
                break
        return out

    # -- catalog ---------------------------------------------------------

    def models(self, *, privacy: str = "public", modality: str = "", limit: int = 100, page_token: str = "") -> tuple:
        """One page of models, kept to ``modality`` by capability. A filtered page may be empty with a next token."""
        # Whole pages, whatever ``limit`` asks: the capability filter keeps only part of each.
        args = _given(privacy=privacy, page_size=500 if privacy == "public" else 100, pagination_token=page_token, status=None if privacy == "public" else "trained")
        data = self._read(lambda c, q: c.models.with_raw_response.list(**args, extra_query=q))
        wanted = MODALITY_CAPABILITIES.get(modality)
        rows = []
        for row in data.get("models") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            if wanted is not None and not set(row.get("capabilities") or ()) & wanted:
                continue
            rows.append(row)
        return rows, data.get("nextPaginationToken") or ""

    def model_form(self, model_id: str) -> ModelForm:
        data = self._read(lambda c, q: c.models.with_raw_response.retrieve(model_id, extra_query=q))
        model = data.get("model") if isinstance(data.get("model"), dict) else data
        return ModelForm.from_schema(schema_from_model(model))

    # -- money -----------------------------------------------------------

    def estimate(self, model_id: str, params: dict) -> str:
        """Free dry run (the API answers 269). Returns the exact cost string; a returned job is an alarm."""
        reply = self.client.call(lambda c, q: c.generate.with_raw_response.run_model(model_id, body=params, dry_run="true", extra_query=q), name="price check")
        alarm = job_id_in(reply.data)
        if alarm:
            raise errors.ProtocolError(f"ALARM: a price check returned job {alarm}. Automatic price checks are stopped until Maya restarts.")
        cost = cost_in(reply.data)
        if cost is None:
            raise errors.ProtocolError("The price check returned no cost.")
        return cost

    def run(self, model_id: str, params: dict) -> str:
        """The paid call. Sent once; see ``RestClient.call(paid=True)``."""
        reply = self.client.call(lambda c, q: c.generate.with_raw_response.run_model(model_id, body=params, extra_query=q), paid=True, timeout=120.0, name=f"generate with {model_id}")
        job_id = job_id_in(reply.data)
        if not job_id:
            raise errors.NotConfirmed("Scenario answered without a job id; the outcome is unknown.")
        return job_id

    # -- jobs ------------------------------------------------------------

    def job(self, job_id: str) -> dict:
        return normalize_job(self._read(lambda c, q: c.jobs.with_raw_response.retrieve(job_id, extra_query=q)))

    def jobs(self, *, limit: int = 20, status: str = "", page_token: str = "") -> tuple:
        args = _given(page_size=max(1, min(int(limit), 100)), status=status, pagination_token=page_token)
        data = self._read(lambda c, q: c.jobs.with_raw_response.list(**args, extra_query=q))
        return [normalize_job(row) for row in data.get("jobs") or [] if isinstance(row, dict)], data.get("nextPaginationToken") or ""

    # -- assets ----------------------------------------------------------

    def asset(self, asset_id: str) -> dict:
        data = self._read(lambda c, q: c.assets.with_raw_response.retrieve(asset_id, extra_query=q))
        return data.get("asset") if isinstance(data.get("asset"), dict) else data

    def download_url(self, asset_id: str, fmt: str = "") -> dict:
        """A signed link to the file, converted to ``fmt`` (``glb``, ``fbx``, ``obj``, an image type) when given."""
        args = _given(target_format=fmt.strip().lower())
        data = self._read(lambda c, q: c.assets.download.with_raw_response.request(asset_id, **args, extra_query=q))
        url = data.get("url") or ""
        if not is_secure_url(url):
            raise errors.ProtocolError("Scenario returned no HTTPS download link.")
        return {"url": url, "mime_type": data.get("mimeType") or ""}

    def upload_start(self, file_name: str, content_type: str, kind: str, size: int) -> dict:
        size = int(size)
        count = max(1, math.ceil(size / UPLOAD_PART_SIZE))
        args = {"file_name": upload_name(file_name), "content_type": content_type, "kind": kind, "file_size": size, "parts": count}
        upload = self._read(lambda c, q: c.uploads.with_raw_response.create(**args, extra_query=q)).get("upload") or {}
        parts = [p for p in upload.get("parts") or [] if isinstance(p, dict) and p.get("url")]
        if not upload.get("id") or len(parts) != count:
            raise errors.ProtocolError("Scenario did not return upload links.")
        return {
            "upload_id": upload["id"],
            "parts": [
                {"number": int(p.get("number") or i + 1), "url": p["url"], "size": min(UPLOAD_PART_SIZE, size - (int(p.get("number") or i + 1) - 1) * UPLOAD_PART_SIZE)} for i, p in enumerate(parts)
            ],
            "part_size": UPLOAD_PART_SIZE,
        }

    def upload_complete(self, upload_id: str, wait: float = 60.0) -> dict:
        """Asks Scenario to assemble the parts, then reads the upload until it names its asset."""
        try:
            self._read(lambda c, q: c.uploads.with_raw_response.trigger_action(upload_id, action="complete", extra_query=q))
        except errors.ToolError as error:
            # A second complete (or one sent before the upload is known) is harmless: read on.
            if not any(text in error.message.lower() for text in _UPLOAD_RACES):
                raise
        deadline = time.monotonic() + wait
        while True:
            try:
                upload = self._read(lambda c, q: c.uploads.with_raw_response.retrieve(upload_id, extra_query=q)).get("upload") or {}
            except errors.NotFound:
                upload = {}  # not readable yet right after the complete: read again until the deadline
            status = str(upload.get("status") or "")
            if upload.get("entityId"):
                return {"asset_id": str(upload["entityId"]), "status": status or "imported"}
            if status == "failed":
                raise errors.ToolError(f"Scenario could not import the file: {upload.get('errorMessage') or 'no reason given'}.")
            if time.monotonic() >= deadline:
                return {"asset_id": "", "status": "timeout"}
            self._sleep(2.0)
