"""Free live check that Scenario still answers the way the plug-in expects (0 CU).

Reads and dry runs only. Paid tools are refused here, in this script, before
any request, and ``SCENARIO_NO_SPEND=1`` is set as well. Checks:

- the hosted Scenario MCP initializes and lists every tool the plug-in calls;
- the API key reads its teams and projects;
- the catalog lists models;
- each quick-pick model loads its schema, and prompt-only ones price with a dry run;
- ``recommend`` answers for each lane capability;
- the plug-in's own session refuses to spend under ``SCENARIO_NO_SPEND``.

Credentials: ``SCENARIO_API_KEY`` and ``SCENARIO_API_SECRET``, or on macOS the
Keychain service ``Scenario for Maya tests`` (see ``tools/test_credentials.py``).

Usage: python3 tools/contract_check.py [--json report.json]
"""

import argparse
import json
import os
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ScenarioForMaya", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

os.environ["SCENARIO_NO_SPEND"] = "1"
os.environ.setdefault("SCENARIO_MAYA_HOME", tempfile.mkdtemp(prefix="scenario-contract-"))
os.environ["SCENARIO_MAYA_CREDSTORE"] = "memory"

import test_credentials  # noqa: E402

from scenario_maya.core import errors  # noqa: E402
from scenario_maya.core.auth import ApiKeyAuth  # noqa: E402
from scenario_maya.core.backend import McpBackend  # noqa: E402
from scenario_maya.core.jsonutil import cu_exact  # noqa: E402
from scenario_maya.core.mcp import DEFAULT_ENDPOINT, McpClient  # noqa: E402

REQUIRED_TOOLS = (
    "teams_list",
    "projects_list",
    "models_list",
    "model_schema_get",
    "model_run",
    "job_get",
    "jobs_wait",
    "jobs_list",
    "asset_get",
    "asset_download",
    "upload_asset",
    "upload_asset_complete",
    "recommend",
)
PAID_TOOLS = ("model_run", "workflow_run")

# Quick picks the plug-in relies on. Prompt-only models are priced; models that
# need an input asset are checked for their schema only (no upload each week).
QUICK_PICKS = (
    ("model_openai-gpt-image-2-5-flare", {"prompt": "a carved wooden treasure chest, game prop, studio light"}),
    ("model_meshy-7-1-txt23d", {"prompt": "a small wooden crate"}),
    ("model_meshy-7-1-img23d", None),
    ("model_tripo-p2-image-to-3d", None),
    ("model_tripo-v3-1-image-to-3d", None),
    ("model_meshy-remesh", None),
    ("model_meshy-uv-unwrap", None),
)
CAPABILITIES = (
    ("txt2img", "a stone well, stylized"),
    ("txt23d", "a small wooden crate"),
    ("img23d", "turn this concept into a mesh"),
    ("txt2video", "a lantern flickering"),
    ("txt2audio", "rain on a tin roof"),
)


class GuardedClient(McpClient):
    """Refuses paid tools before any request, whatever the caller asks."""

    def call_tool(self, name, arguments=None, *, paid=False, **kwargs):
        if paid or (name in PAID_TOOLS and not (arguments or {}).get("dry_run")):
            raise AssertionError(f"contract check refused a paid call to {name}")
        return super().call_tool(name, arguments, paid=False, **kwargs)


class Report:
    def __init__(self):
        self.checks = []

    def run(self, name, fn):
        started = time.monotonic()
        try:
            detail = fn()
            ok = True
        except Exception as error:  # noqa: BLE001 - every failure is reported, none stops the run
            ok, detail = False, f"{type(error).__name__}: {error}"
            if not isinstance(error, (errors.ScenarioError, AssertionError)):
                detail += "\n" + traceback.format_exc(limit=3)
        seconds = time.monotonic() - started
        self.checks.append({"name": name, "ok": ok, "detail": str(detail or "")[:500], "seconds": round(seconds, 2)})
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({seconds:.1f} s){'  ' + str(detail) if detail else ''}")
        return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", help="write the report here")
    args = parser.parse_args()
    key, secret = test_credentials.load()
    if not (key and secret):
        print("No test key: set SCENARIO_API_KEY and SCENARIO_API_SECRET.")
        return 2
    endpoint = os.environ.get("SCENARIO_MCP_URL", "").strip() or DEFAULT_ENDPOINT
    client = GuardedClient(ApiKeyAuth(key, secret, source="environment"), endpoint, client_name="scenario-maya-contract")
    backend = McpBackend(client)
    report = Report()

    def tools():
        names = {tool.get("name") for tool in client.list_tools()}
        missing = [name for name in REQUIRED_TOOLS if name not in names]
        assert not missing, f"missing tools: {missing}"
        return f"{len(names)} tools"

    def teams():
        found = backend.teams()
        assert found and isinstance(found[0].get("projects"), list), "no team with projects"
        return f"{len(found)} team(s)"

    def catalog():
        rows, _token = backend.models(limit=20)
        assert rows and all(row.get("id") for row in rows), "empty catalog"
        return f"{len(rows)} models"

    report.run("tools listed", tools)
    report.run("teams and projects", teams)
    report.run("catalog", catalog)
    for model_id, params in QUICK_PICKS:

        def pick(model_id=model_id, params=params):
            form = backend.model_form(model_id)
            assert form.fields, "schema has no fields"
            if params is None:
                assert form.file_fields, "expected an input asset field"
                return "schema only"
            assert form.problems(params) == [], form.problems(params)
            cost = cu_exact(backend.estimate(model_id, form.build_params(params)))
            assert float(cost) > 0, f"price {cost}"
            return f"{cost} CU"

        report.run(f"quick pick {model_id}", pick)
    for capability, prompt in CAPABILITIES:

        def recommend(capability=capability, prompt=prompt):
            ranked = backend.recommend(capability, prompt, limit=2).get("ranked") or []
            assert ranked and ranked[0].get("model_id"), "no recommendation"
            return ranked[0]["model_id"]

        report.run(f"recommend {capability}", recommend)

    def no_spend():
        from scenario_maya.core.ledger import Ledger
        from scenario_maya.core.session import Session

        session = Session(ledger=Ledger(), endpoint=endpoint, backend_factory=lambda auth: McpBackend(GuardedClient(auth, endpoint)))
        session.sign_in_api_key(key, secret)
        quote = session.price(QUICK_PICKS[0][0], QUICK_PICKS[0][1])
        try:
            session.submit(quote.quote_id, approved_cost=quote.cu_cost_exact, params=QUICK_PICKS[0][1])
        except errors.Refused as error:
            assert "SCENARIO_NO_SPEND" in str(error), str(error)
            return "refused before sending"
        raise AssertionError("submit was not refused")

    report.run("SCENARIO_NO_SPEND refusal", no_spend)
    failed = [check for check in report.checks if not check["ok"]]
    print(f"contract: {len(report.checks) - len(failed)} passed, {len(failed)} failed")
    if args.json:
        with open(args.json, "w") as handle:
            json.dump({"endpoint": endpoint, "checks": report.checks}, handle, indent=1)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
