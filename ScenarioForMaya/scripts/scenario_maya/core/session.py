"""The money contract in one place: sign-in state, workspace, price checks,
quotes, the one paid request, and Not confirmed reviews.

Every caller (panel, agent server, Python API) goes through ``Session``, so
the same rules hold whoever drives:

1. ``price`` runs the free dry run and issues a single-use quote.
2. ``submit`` takes the quote (exact cost string, same payload, workspace and
   target), checks for a Not confirmed twin, saves the intent in the ledger,
   then sends exactly one request. A failure where Scenario may have started
   the work leaves the row Not confirmed; nothing is ever resent.
3. Only a person links a Not confirmed row to a Scenario job or marks it
   reviewed; agents can list candidates.

All methods block. The Maya layer calls them from worker threads.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime

from . import errors
from .auth import ApiKeyAuth, Credentials
from .backend import McpBackend, ScenarioBackend
from .jsonutil import cu_exact, payload_hash
from .ledger import Ledger
from .mcp import DEFAULT_ENDPOINT, McpClient
from .paths import env_flag
from .quotes import Quote, QuoteBook
from .settings import Settings


def no_spend() -> bool:
    return env_flag("SCENARIO_NO_SPEND")


def _parse_utc(text: str) -> float:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() if text else 0.0
    except ValueError:
        return 0.0


class Session:
    def __init__(
        self,
        settings: Settings | None = None,
        ledger: Ledger | None = None,
        credentials: Credentials | None = None,
        endpoint: str | None = None,
        backend_factory=None,
        transport=None,
    ) -> None:
        self.settings = settings or Settings()
        self.ledger = ledger or Ledger()
        self.credentials = credentials or Credentials(self.settings)
        self.endpoint = endpoint or os.environ.get("SCENARIO_MCP_URL", "").strip() or DEFAULT_ENDPOINT
        self.transport = transport
        self._backend_factory = backend_factory or (lambda auth: McpBackend(McpClient(auth, self.endpoint, transport=self.transport)))
        self.quotes = QuoteBook()
        self._lock = threading.RLock()
        self._auth = None
        self._backend: ScenarioBackend | None = None
        self.price_checks_stopped = ""
        self.listeners: list = []

    # -- state -----------------------------------------------------------

    def _notify(self, event: str, **data) -> None:
        for listener in list(self.listeners):
            try:
                listener(event, data)
            except Exception:  # noqa: BLE001 - a broken listener never breaks the session
                pass

    def load(self) -> bool:
        """Resolves stored credentials without any network call. True when signed in."""
        with self._lock:
            self._auth = self.credentials.resolve()
            self._backend = self._backend_factory(self._auth) if self._auth else None
        return self._auth is not None

    @property
    def signed_in(self) -> bool:
        return self._auth is not None

    @property
    def auth(self):
        return self._auth

    def backend(self) -> ScenarioBackend:
        with self._lock:
            if self._backend is None:
                if self._auth is None and not self.load():
                    raise errors.SignInRequired("Sign in to Scenario first.")
            return self._backend

    def workspace(self) -> str:
        team = self.settings.get("team_id")
        project = self.settings.get("project_id")
        if isinstance(self._auth, ApiKeyAuth) and not (team and project):
            return f"key:{self._auth.key_id}"
        return f"{team}/{project}" if team or project else ""

    def status(self) -> dict:
        auth = self._auth
        return {
            "signed_in": auth is not None,
            "method": getattr(auth, "kind", ""),
            "account": auth.label() if auth else "",
            "team": {"id": self.settings.get("team_id"), "name": self.settings.get("team_name")},
            "project": {"id": self.settings.get("project_id"), "name": self.settings.get("project_name")},
            "spending": "off (SCENARIO_NO_SPEND)" if no_spend() else "on",
            "price_checks": "stopped: " + self.price_checks_stopped if self.price_checks_stopped else "on",
            "credential_store": self.credentials.store.name,
            "credential_store_insecure": bool(self.credentials.store.insecure),
        }

    # -- sign-in ---------------------------------------------------------

    def _adopt(self, auth) -> None:
        with self._lock:
            self._auth = auth
            self._backend = self._backend_factory(auth)
            self.quotes.clear()
        self._notify("signed_in", method=auth.kind)

    def sign_in_api_key(self, key_id: str, secret: str) -> dict:
        """Checks the key with a free read, then stores it. Returns the workspace."""
        probe = ApiKeyAuth(key_id, secret, source="check")
        backend = self._backend_factory(probe)
        teams = backend.teams()
        team = next(iter(teams), {})
        project = next(iter(team.get("projects") or []), {})
        auth = self.credentials.save_api_key(key_id, secret)
        self.settings.update(team_id=team.get("id", ""), team_name=team.get("name", ""), project_id=project.get("id", ""), project_name=project.get("name", ""))
        self._adopt(auth)
        return {"team": team.get("name", ""), "project": project.get("name", "")}

    def sign_in_browser(self, open_browser, cancel: threading.Event | None = None) -> None:
        client_id = self.credentials.client_id()
        tokens = self.credentials.oauth.sign_in_browser(client_id, open_browser, cancel=cancel)
        self._adopt(self.credentials.save_oauth(client_id, tokens))

    def sign_in_device(self, on_code, cancel: threading.Event | None = None) -> None:
        client_id = self.credentials.client_id()
        device = self.credentials.oauth.start_device(client_id)
        on_code(device)
        tokens = self.credentials.oauth.poll_device(client_id, device, cancel=cancel)
        self._adopt(self.credentials.save_oauth(client_id, tokens))

    def sign_out(self) -> None:
        self.credentials.sign_out()
        with self._lock:
            self._auth = None
            self._backend = None
            self.quotes.clear()
        self._notify("signed_out")

    def set_workspace(self, team_id: str, project_id: str, team_name: str = "", project_name: str = "") -> None:
        """Changes the workspace: clears quotes, never touches submitted jobs."""
        self.settings.update(team_id=team_id, project_id=project_id, team_name=team_name, project_name=project_name)
        with self._lock:
            if self._auth is not None and getattr(self._auth, "kind", "") == "oauth":
                self._auth.team_id, self._auth.project_id = team_id, project_id
            self.quotes.clear()
        self._notify("workspace", team_id=team_id, project_id=project_id)

    # -- price and spend -------------------------------------------------

    def price(self, model_id: str, params: dict, *, origin: dict | None = None, driver: str = "person") -> Quote:
        if self.price_checks_stopped:
            raise errors.Refused("Automatic price checks are stopped: " + self.price_checks_stopped, hint="Restart Maya after checking the job.")
        backend = self.backend()
        try:
            cost = backend.estimate(model_id, params)
        except errors.ProtocolError as error:
            if "ALARM" in error.message:
                self.price_checks_stopped = error.message
                self._track_alarm(model_id, params, error.message)
            raise
        return self.quotes.issue(kind="model", target_id=model_id, params=params, workspace=self.workspace(), cu_cost_exact=cost, origin=origin, driver=driver)

    def _track_alarm(self, model_id: str, params: dict, message: str) -> None:
        job_id = message.split("job ", 1)[-1].split(".", 1)[0].strip()
        row = self.ledger.prepare(
            kind="model", target_id=model_id, workspace=self.workspace(), payload_hash=payload_hash(params), params=params, driver="price-check", label="Price check returned a job"
        )
        self.ledger.set_state(row["local_id"], "submitting", "price check returned a job")
        self.ledger.submitted(row["local_id"], job_id, "tracked: a price check returned this job")

    def blocking(self, model_id: str, params: dict, target: str = "") -> list:
        return self.ledger.blocking_uncertain(self.workspace(), model_id, target, payload_hash(params))

    def submit(
        self,
        quote_id: str,
        *,
        approved_cost: str | None = None,
        params: dict | None = None,
        origin: dict | None = None,
        driver: str = "person",
        label: str = "",
        model_name: str = "",
    ) -> dict:
        """Spends one quote. Returns the ledger row (state ``remote`` on success)."""
        if no_spend():
            raise errors.Refused("Spending is off (SCENARIO_NO_SPEND=1). Price checks still work.")
        quote = self.quotes.take(quote_id, approved_cost=approved_cost, params=params, workspace=self.workspace(), origin=origin)
        target = quote.origin.get("target", "")
        twins = self.ledger.blocking_uncertain(quote.workspace, quote.target_id, target, quote.params_hash)
        if twins:
            self.quotes.release(quote_id)
            raise errors.Refused(
                "An identical request is Not confirmed; it may have run and been charged.",
                hint=f"Review job {twins[0]['local_id']} in Jobs before sending it again.",
            )
        backend = self.backend()
        try:
            self._auth.ensure_fresh(300.0)
        except errors.ScenarioError:
            self.quotes.release(quote_id)
            raise
        row = self.ledger.prepare(
            kind=quote.kind,
            target_id=quote.target_id,
            target_name=model_name,
            workspace=quote.workspace,
            payload_hash=quote.params_hash,
            params=quote.params,
            quote_hash=quote.quote_hash,
            cost_exact=quote.cu_cost_exact,
            scene_uuid=quote.origin.get("scene_uuid", ""),
            scene_path=quote.origin.get("scene_path", ""),
            target=target,
            origin=quote.origin,
            driver=driver,
            label=label,
        )
        local_id = row["local_id"]
        self.ledger.claim(local_id)
        try:
            job_id = backend.run(quote.target_id, quote.params)
        except errors.NotConfirmed as error:
            row = self.ledger.not_confirmed(local_id, error.message)
            self._notify("not_confirmed", local_id=local_id)
            raise
        except (errors.Blocked, errors.ToolError, errors.Forbidden, errors.AuthFailed, errors.Refused, errors.ProtocolError, errors.NotFound, errors.RateLimited) as error:
            self.ledger.refused(local_id, str(error), error.hint)
            raise
        except BaseException as error:  # noqa: BLE001 - unknown outcome: never resend
            self.ledger.not_confirmed(local_id, f"Unexpected error after sending: {type(error).__name__}")
            raise errors.NotConfirmed("The request may have been sent; its outcome is unknown.") from error
        row = self.ledger.submitted(local_id, job_id)
        self._notify("submitted", local_id=local_id, job_id=job_id, cost=quote.cu_cost_exact, driver=driver)
        return row

    # -- jobs ------------------------------------------------------------

    def refresh_job(self, local_id: str) -> dict:
        """Reads the Scenario job once and moves the ledger row accordingly."""
        row = self.ledger.get(local_id)
        if row is None:
            raise errors.NotFound(f"No local job {local_id}.")
        if row["state"] not in ("remote", "cancel_requested") or not row.get("remote_job_id"):
            return row
        job = self.backend().job(row["remote_job_id"])
        return self.apply_job_status(local_id, job)

    def apply_job_status(self, local_id: str, job: dict) -> dict:
        row = self.ledger.get(local_id)
        result = dict(row.get("result") or {})
        result.update({"asset_ids": job.get("asset_ids") or [], "progress": job.get("progress"), "status": job.get("status")})
        fields = {"result_json": result}
        if job.get("cu_cost") is not None:
            fields["charged_exact"] = job["cu_cost"]
        status = job.get("status")
        if status == "success":
            return self.ledger.set_state(local_id, "succeeded", "Scenario finished", **fields)
        if status == "failure":
            message = job.get("error") or "Scenario reported a failure."
            prefix = "Blocked: " if any(word in message.lower() for word in ("moderation", "flagged", "nsfw", "content policy")) else ""
            return self.ledger.set_state(local_id, "failed", "Scenario failed", error=prefix + message, hint=job.get("hint") or "", **fields)
        if status == "canceled":
            return self.ledger.set_state(local_id, "canceled", "Scenario canceled", **fields)
        return self.ledger.update_fields(local_id, **fields)

    def candidates(self, local_id: str, pages: int = 5) -> list:
        """Scenario jobs that may be the outcome of a Not confirmed row. None preselected."""
        row = self.ledger.get(local_id)
        if row is None or row["state"] != "uncertain":
            raise errors.Refused("Only a Not confirmed job has candidates.")
        claim = row.get("claim_epoch") or 0.0
        start, end = claim - 600, claim + 3600
        found, token = [], ""
        backend = self.backend()
        for _ in range(pages):
            rows, token = backend.jobs(limit=50, page_token=token)
            for job in rows:
                when = _parse_utc(job.get("created_at", ""))
                if job.get("model_id") == row["target_id"] and start <= when <= end:
                    job["seconds_from_claim"] = round(when - claim, 1)
                    found.append(job)
            oldest = min((_parse_utc(j.get("created_at", "")) for j in rows), default=0.0)
            if not token or (oldest and oldest < start):
                break
        found.sort(key=lambda j: abs(j["seconds_from_claim"]))
        return found[:20]

    def link(self, local_id: str, remote_job_id: str, *, by_person: bool) -> dict:
        if not by_person:
            raise errors.Refused("Only a person can link a Not confirmed job, from the Jobs view in Maya.")
        row = self.ledger.get(local_id)
        if row is None or row["state"] != "uncertain":
            raise errors.Refused("Only a Not confirmed job can be linked.")
        job = self.backend().job(remote_job_id)
        if job.get("model_id") and job["model_id"] != row["target_id"]:
            raise errors.Refused(f"Job {remote_job_id} ran {job['model_id']}, not {row['target_id']}.")
        if self.ledger.find_remote(remote_job_id):
            raise errors.Refused(f"Job {remote_job_id} is already linked to another local job.")
        self.ledger.link(local_id, remote_job_id)
        return self.apply_job_status(local_id, job)

    def mark_reviewed(self, local_id: str, *, by_person: bool) -> dict:
        if not by_person:
            raise errors.Refused("Only a person can mark a Not confirmed job reviewed.")
        return self.ledger.mark_reviewed(local_id)

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)


__all__ = ["Session", "no_spend", "cu_exact"]
