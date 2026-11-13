"""Free live check that Scenario still answers the way the plug-in expects (0 CU).

Reads and dry runs only. Paid calls are refused here, in this script, before
any request, and ``SCENARIO_NO_SPEND=1`` is set
as well. Checks, against Scenario's REST API:

- the API key reads its project;
- the catalog lists image and 3D models;
- each quick-pick model loads its inputs, and prompt-only ones price with a dry run;
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
from scenario_maya.core.backend import RestBackend  # noqa: E402
from scenario_maya.core.jsonutil import cu_exact  # noqa: E402
from scenario_maya.core.rest import RestClient  # noqa: E402
from scenario_maya.core.session import api_url  # noqa: E402

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


class GuardedClient(RestClient):
    """Refuses paid calls before any request, whatever the caller asks."""

    def call(self, op, *, paid=False, **kwargs):
        if paid:
            raise AssertionError(f"contract check refused a paid call ({kwargs.get('name') or 'unnamed'})")
        return super().call(op, paid=False, **kwargs)


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
    endpoint = api_url()
    backend = RestBackend(GuardedClient(ApiKeyAuth(key, secret, source="environment"), endpoint))
    report = Report()

    def project():
        found = backend.teams()
        assert found and found[0]["projects"] and found[0]["projects"][0].get("id"), "the key reads no project"
        return "the key's project"

    def catalog(modality):
        def check():
            rows, _token = backend.models(modality=modality)
            assert rows and all(row.get("id") and row.get("capabilities") for row in rows), f"no {modality} models"
            return f"{len(rows)} models"

        return check

    report.run("key project", project)
    report.run("catalog image", catalog("image"))
    report.run("catalog 3d", catalog("3d"))
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

    def no_spend():
        from scenario_maya.core.ledger import Ledger
        from scenario_maya.core.session import Session

        session = Session(ledger=Ledger(), endpoint=endpoint, backend_factory=lambda auth: RestBackend(GuardedClient(auth, endpoint)))
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
