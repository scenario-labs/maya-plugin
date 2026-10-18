"""Provenance written on every node the plug-in lands (spec 10.3).

Plain string attributes, so scenes open on machines without the plug-in. The
values come from the job row and never include credentials, signed links or
local paths.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime

from .. import __version__

PREFIX = "scenario_"
NAMES = (
    "scenario_asset_id",
    "scenario_job_id",
    "scenario_model_id",
    "scenario_model_name",
    "scenario_prompt",
    "scenario_parameters",
    "scenario_input_asset_ids",
    "scenario_quoted_cu",
    "scenario_charged_cu",
    "scenario_created_utc",
    "scenario_apply",
    "scenario_plugin_version",
    "scenario_maya_version",
)


def _asset_ids_in(value) -> list:
    if isinstance(value, str):
        return [value] if value.startswith("asset_") else []
    if isinstance(value, (list, tuple)):
        return [item for entry in value for item in _asset_ids_in(entry)]
    if isinstance(value, dict):
        return [item for entry in value.values() for item in _asset_ids_in(entry)]
    return []


def attributes(row: dict, asset_id: str, *, maya_version: str, apply: str = "import", store_prompt: bool = True) -> dict:
    """Attribute name to string value for one landed asset."""
    params = dict(row.get("params") or {})
    prompt = str(params.pop("prompt", "") or "")
    inputs = _asset_ids_in(params)
    plain = {key: value for key, value in params.items() if not _asset_ids_in(value)}
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "scenario_asset_id": asset_id,
        "scenario_job_id": row.get("remote_job_id") or "",
        "scenario_model_id": row.get("target_id") or "",
        "scenario_model_name": row.get("target_name") or "",
        "scenario_prompt": prompt if store_prompt else "",
        "scenario_parameters": json.dumps(plain, sort_keys=True, separators=(",", ":")),
        "scenario_input_asset_ids": json.dumps(inputs),
        "scenario_quoted_cu": row.get("cost_exact") or "",
        "scenario_charged_cu": row.get("charged_exact") or "",
        "scenario_created_utc": row.get("created_utc") or now,
        "scenario_apply": f"{apply} {now}",
        "scenario_plugin_version": __version__,
        "scenario_maya_version": maya_version,
    }


def web_url(asset_id: str, team_id: str = "", project_id: str = "") -> str:
    """Open on Scenario: the web app's asset view in the asset's workspace."""
    query = {"openAssetId": asset_id} if asset_id else {}
    if team_id and project_id:
        query.update(teamId=team_id, projectId=project_id)
    return "https://app.scenario.com/assets" + ("?" + urllib.parse.urlencode(query) if query else "")
