"""What the plug-in needs from Scenario, and its implementation over the hosted MCP.

``ScenarioBackend`` names every call; ``McpBackend`` implements it with the
hosted Scenario MCP. Replies are read defensively (several field spellings are
accepted) because the hosted server is written for agents and its replies can
change; the recorded fixtures and the weekly contract check catch drift.
A REST backend can replace this one later without touching the rest.
"""

from __future__ import annotations

from typing import Any

from . import errors
from .http import is_secure_url
from .jsonutil import cu_exact
from .mcp import McpClient
from .schema import ModelForm


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
    """One shape for job rows from ``job_get``, ``jobs_wait`` and ``jobs_list``."""
    if "job" in row and isinstance(row["job"], dict):
        row = row["job"]
    status = str(row.get("status") or "").lower()
    out = {
        "job_id": job_id_in(row) or str(row.get("id") or ""),
        "status": status,
        "progress": row.get("progress"),
        "model_id": row.get("modelId") or row.get("model_id") or "",
        "job_type": row.get("jobType") or "",
        "asset_ids": list(row.get("assetIds") or row.get("asset_ids") or []),
        "cu_cost": cost_in(row),
        "error": row.get("error") or "",
        "hint": row.get("hint") or "",
        "workflow_id": row.get("workflowId") or "",
        "created_at": row.get("createdAt") or "",
        "updated_at": row.get("updatedAt") or "",
    }
    out["finished"] = status in ("success", "failure", "canceled")
    return out


class ScenarioBackend:
    """Interface. Every method blocks; call from a worker thread."""

    def teams(self) -> list: ...
    def projects(self, team_id: str) -> list: ...
    def models(self, *, privacy: str = "public", modality: str = "", limit: int = 100, page_token: str = "") -> tuple: ...
    def model_form(self, model_id: str) -> ModelForm: ...
    def estimate(self, model_id: str, params: dict) -> str: ...
    def run(self, model_id: str, params: dict) -> str: ...
    def job(self, job_id: str) -> dict: ...
    def wait_jobs(self, job_ids: list) -> dict: ...
    def jobs(self, *, limit: int = 20, status: str = "", page_token: str = "") -> tuple: ...
    def asset(self, asset_id: str) -> dict: ...
    def download_url(self, asset_id: str, fmt: str = "") -> dict: ...
    def upload_start(self, file_name: str, content_type: str, kind: str, size: int) -> dict: ...
    def upload_complete(self, upload_id: str) -> dict: ...
    def recommend(self, capability: str, prompt: str, priority: str = "quality", limit: int = 5) -> dict: ...


class McpBackend(ScenarioBackend):
    def __init__(self, client: McpClient) -> None:
        self.client = client

    def _read(self, tool: str, args: dict | None = None, timeout: float = 60.0, workspace: bool = True) -> dict:
        return self.client.call_tool(tool, args or {}, timeout=timeout, workspace=workspace).data

    # -- workspace -------------------------------------------------------

    def teams(self) -> list:
        data = self._read("teams_list", workspace=False)
        return [team for team in data.get("teams") or [] if isinstance(team, dict)]

    def projects(self, team_id: str) -> list:
        out, token = [], ""
        for _ in range(20):
            args = {"team_id": team_id, "limit": 100}
            if token:
                args["page_token"] = token
            data = self._read("projects_list", args, workspace=False)
            out.extend(p for p in data.get("projects") or [] if isinstance(p, dict))
            token = data.get("nextPaginationToken") or ""
            if not token:
                break
        return out

    # -- catalog ---------------------------------------------------------

    def models(self, *, privacy: str = "public", modality: str = "", limit: int = 100, page_token: str = "") -> tuple:
        filters = {"privacy": privacy}
        if modality:
            filters["modality"] = modality
        args = {"limit": limit, "filters": filters}
        if page_token:
            args["page_token"] = page_token
        data = self._read("models_list", args)
        rows = [row for row in data.get("models") or [] if isinstance(row, dict) and row.get("id")]
        return rows, data.get("nextPaginationToken") or ""

    def model_form(self, model_id: str) -> ModelForm:
        return ModelForm.from_schema(self._read("model_schema_get", {"model_id": model_id}))

    def recommend(self, capability: str, prompt: str, priority: str = "quality", limit: int = 5) -> dict:
        args = {"capability": capability, "prompt": prompt, "priority": priority, "limit": limit}
        return self._read("recommend", args)

    # -- money -----------------------------------------------------------

    def estimate(self, model_id: str, params: dict) -> str:
        """Free dry run. Returns the exact cost string; a returned job is an alarm."""
        data = self._read("model_run", {"model_id": model_id, "parameters": params, "dry_run": True, "wait": False})
        alarm = job_id_in(data)
        if alarm:
            raise errors.ProtocolError(f"ALARM: a price check returned job {alarm}. Automatic price checks are stopped until Maya restarts.")
        cost = cost_in(data)
        if cost is None:
            raise errors.ProtocolError("The price check returned no cost.")
        return cost

    def run(self, model_id: str, params: dict) -> str:
        """The paid call. Sent once; see ``McpClient.call_tool(paid=True)``."""
        result = self.client.call_tool("model_run", {"model_id": model_id, "parameters": params, "wait": False}, paid=True, timeout=120.0)
        job_id = job_id_in(result.data)
        if not job_id:
            raise errors.NotConfirmed("model_run answered without a job id; the outcome is unknown.")
        return job_id

    # -- jobs ------------------------------------------------------------

    def job(self, job_id: str) -> dict:
        return normalize_job(self._read("job_get", {"job_id": job_id}))

    def wait_jobs(self, job_ids: list, timeout: float = 200.0) -> dict:
        data = self._read("jobs_wait", {"job_ids": list(job_ids)}, timeout=timeout)
        rows = data.get("jobs") or data.get("results") or data.get("rows") or []
        return {
            "status": data.get("status") or "",
            "jobs": [normalize_job(row) for row in rows if isinstance(row, dict)],
            "pending_job_ids": list(data.get("pending_job_ids") or []),
        }

    def jobs(self, *, limit: int = 20, status: str = "", page_token: str = "") -> tuple:
        args: dict = {"limit": limit}
        if status:
            args["filters"] = {"status": status}
        if page_token:
            args["page_token"] = page_token
        data = self._read("jobs_list", args)
        return [normalize_job(row) for row in data.get("jobs") or [] if isinstance(row, dict)], data.get("nextPaginationToken") or ""

    # -- assets ----------------------------------------------------------

    def asset(self, asset_id: str) -> dict:
        data = self._read("asset_get", {"asset_id": asset_id})
        return data.get("asset") if isinstance(data.get("asset"), dict) else data

    def download_url(self, asset_id: str, fmt: str = "") -> dict:
        args = {"asset_id": asset_id}
        if fmt:
            args["format"] = fmt
        data = self._read("asset_download", args)
        url = data.get("url") or data.get("download_url") or ""
        if not is_secure_url(url):
            raise errors.ProtocolError("Scenario returned no HTTPS download link.")
        return {"url": url, "mime_type": data.get("mimeType") or data.get("mime_type") or ""}

    def upload_start(self, file_name: str, content_type: str, kind: str, size: int) -> dict:
        args = {"file_name": file_name, "content_type": content_type, "kind": kind, "file_size": int(size)}
        data = self.client.call_tool("upload_asset", args, timeout=60.0).data
        parts = data.get("parts") or []
        if not data.get("upload_id") or not parts:
            raise errors.ProtocolError("Scenario did not return upload links.")
        return {
            "upload_id": data["upload_id"],
            "parts": [{"number": int(p.get("part_number") or i + 1), "url": p.get("upload_url") or p.get("url") or "", "size": p.get("content_length")} for i, p in enumerate(parts)],
            "part_size": int(data.get("part_size") or 0),
        }

    def upload_complete(self, upload_id: str) -> dict:
        data = self.client.call_tool("upload_asset_complete", {"upload_id": upload_id}, timeout=200.0).data
        return {"asset_id": data.get("asset_id") or "", "status": data.get("status") or ""}
