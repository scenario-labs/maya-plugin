"""Durable job ledger: SQLite in ``<MAYA_APP_DIR>/scenario/ledger.sqlite3``.

Shared by every Maya version and ``mayapy`` run of the same user (WAL mode, a
short connection per operation, ``BEGIN IMMEDIATE`` around every state
change). Each Maya session holds an OS lock on its own session file while it
lives, so another session can tell a live owner from a crashed one.

Money rules kept here (spec 7.1):
- The intent is saved before the paid request: ``prepared`` -> ``submitting``
  records payload hash, quote hash, exact cost and claim time, then the caller
  sends exactly one request.
- A ``submitting`` row whose owner session is gone becomes ``uncertain`` (Not
  confirmed) at the next start.
- A Not confirmed row blocks an identical request (same workspace, model or
  workflow, target and payload hash) until a person links it to a Scenario
  job or marks it reviewed. The check runs inside the claim transaction.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import uuid
from datetime import UTC, datetime

from . import errors
from .paths import user_dir

STATES = (
    "prepared",
    "submitting",
    "remote",
    "uncertain",
    "cancel_requested",
    "succeeded",
    "failed",
    "canceled",
    "downloading",
    "ready",
    "download_failed",
    "applying",
    "applied",
    "apply_failed",
)

TRANSITIONS = {
    "prepared": {"submitting", "canceled"},
    "submitting": {"remote", "uncertain", "failed"},
    "remote": {"succeeded", "failed", "canceled", "cancel_requested", "remote"},
    "cancel_requested": {"canceled", "succeeded", "failed"},
    "uncertain": {"remote", "uncertain"},
    "succeeded": {"downloading", "ready"},
    "downloading": {"ready", "download_failed", "downloading"},
    "download_failed": {"downloading"},
    "ready": {"applying", "downloading"},
    "applying": {"applied", "apply_failed", "ready"},
    "applied": {"applying", "downloading"},
    "apply_failed": {"applying", "ready"},
    "failed": set(),
    "canceled": set(),
}

ACTIVE = ("submitting", "remote", "cancel_requested", "downloading")
SCHEMA_VERSION = 1

_COLUMNS = (
    "local_id",
    "created_utc",
    "updated_utc",
    "state",
    "kind",
    "target_id",
    "target_name",
    "workspace",
    "payload_hash",
    "params_json",
    "quote_hash",
    "cost_exact",
    "charged_exact",
    "claim_utc",
    "claim_epoch",
    "remote_job_id",
    "scene_uuid",
    "scene_path",
    "target",
    "origin_json",
    "driver",
    "label",
    "result_json",
    "error",
    "hint",
    "reviewed",
    "owner",
)


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _SessionLock:
    """Holds an exclusive OS lock on ``locks/session-<id>.lock`` for the process lifetime."""

    def __init__(self, folder: str, session_id: str) -> None:
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, f"session-{session_id}.lock")
        self._handle = open(self.path, "a+b")
        _lock_file(self._handle, blocking=True)

    def release(self) -> None:
        try:
            _unlock_file(self._handle)
        finally:
            self._handle.close()


def _lock_file(handle, blocking: bool) -> bool:
    if sys.platform.startswith("win"):
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return True
    except OSError:
        return False


def _unlock_file(handle) -> None:
    if sys.platform.startswith("win"):
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Ledger:
    def __init__(self, path: str | None = None, session_id: str | None = None) -> None:
        folder = os.path.dirname(path) if path else user_dir()
        self.path = path or os.path.join(folder, "ledger.sqlite3")
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._locks_dir = os.path.join(folder, "locks")
        self._session_lock = _SessionLock(self._locks_dir, self.session_id)
        self._mutex = threading.Lock()
        self._init_db()

    # -- connection ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _init_db(self) -> None:
        with self._mutex:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS jobs ("
                    + ", ".join(
                        f"{name} {'TEXT PRIMARY KEY' if name == 'local_id' else ('REAL' if name == 'claim_epoch' else ('INTEGER DEFAULT 0' if name == 'reviewed' else 'TEXT'))}" for name in _COLUMNS
                    )
                    + ")"
                )
                connection.execute("CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state)")
                connection.execute("CREATE INDEX IF NOT EXISTS jobs_remote ON jobs(remote_job_id)")
                connection.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, local_id TEXT, utc TEXT, state TEXT, note TEXT)")
                connection.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
                connection.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            finally:
                connection.close()

    def close(self) -> None:
        self._session_lock.release()

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        for key in ("params_json", "origin_json", "result_json"):
            raw = out.pop(key, None)
            name = key[: -len("_json")]
            try:
                out[name] = json.loads(raw) if raw else {}
            except ValueError:
                out[name] = {}
        out["reviewed"] = bool(out.get("reviewed"))
        return out

    def _event(self, connection: sqlite3.Connection, local_id: str, state: str, note: str = "") -> None:
        connection.execute("INSERT INTO events(local_id, utc, state, note) VALUES (?, ?, ?, ?)", (local_id, utc_now(), state, note[:500]))

    def _transition(self, connection: sqlite3.Connection, local_id: str, new_state: str, note: str = "", **fields) -> dict:
        row = connection.execute("SELECT * FROM jobs WHERE local_id = ?", (local_id,)).fetchone()
        if row is None:
            raise errors.NotFound(f"No local job {local_id}.")
        current = row["state"]
        if new_state not in TRANSITIONS.get(current, set()):
            raise errors.Refused(f"Job {local_id} cannot go from {current} to {new_state}.")
        fields = {k: (json.dumps(v) if k in ("params_json", "origin_json", "result_json") and not isinstance(v, str) else v) for k, v in fields.items()}
        fields["state"] = new_state
        fields["updated_utc"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        connection.execute(f"UPDATE jobs SET {assignments} WHERE local_id = ?", (*fields.values(), local_id))
        self._event(connection, local_id, new_state, note)
        return self._row(connection.execute("SELECT * FROM jobs WHERE local_id = ?", (local_id,)).fetchone())

    def _write(self, fn):
        with self._mutex:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    result = fn(connection)
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                connection.execute("COMMIT")
                return result
            finally:
                connection.close()

    # -- reads -----------------------------------------------------------

    def get(self, local_id: str) -> dict | None:
        connection = self._connect()
        try:
            return self._row(connection.execute("SELECT * FROM jobs WHERE local_id = ?", (local_id,)).fetchone())
        finally:
            connection.close()

    def find_remote(self, remote_job_id: str) -> dict | None:
        connection = self._connect()
        try:
            return self._row(connection.execute("SELECT * FROM jobs WHERE remote_job_id = ? ORDER BY created_utc DESC", (remote_job_id,)).fetchone())
        finally:
            connection.close()

    def list(self, states: tuple | None = None, limit: int = 100, workspace: str | None = None) -> list:
        query = "SELECT * FROM jobs"
        clauses, args = [], []
        if states:
            clauses.append(f"state IN ({', '.join('?' for _ in states)})")
            args.extend(states)
        if workspace:
            clauses.append("workspace = ?")
            args.append(workspace)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_utc DESC LIMIT ?"
        args.append(int(limit))
        connection = self._connect()
        try:
            return [self._row(row) for row in connection.execute(query, args).fetchall()]
        finally:
            connection.close()

    def events(self, local_id: str) -> list:
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute("SELECT utc, state, note FROM events WHERE local_id = ? ORDER BY id", (local_id,)).fetchall()]
        finally:
            connection.close()

    def blocking_uncertain(self, workspace: str, target_id: str, target: str, payload_hash: str, connection: sqlite3.Connection | None = None) -> list:
        query = "SELECT * FROM jobs WHERE state = 'uncertain' AND reviewed = 0 AND workspace = ? AND target_id = ? AND COALESCE(target, '') = ? AND payload_hash = ?"
        args = (workspace, target_id, target or "", payload_hash)
        if connection is not None:
            return [self._row(row) for row in connection.execute(query, args).fetchall()]
        own = self._connect()
        try:
            return [self._row(row) for row in own.execute(query, args).fetchall()]
        finally:
            own.close()

    # -- writes ----------------------------------------------------------

    def prepare(
        self,
        *,
        kind: str,
        target_id: str,
        workspace: str,
        payload_hash: str,
        params: dict,
        quote_hash: str = "",
        cost_exact: str = "",
        target_name: str = "",
        scene_uuid: str = "",
        scene_path: str = "",
        target: str = "",
        origin: dict | None = None,
        driver: str = "person",
        label: str = "",
    ) -> dict:
        local_id = "lj_" + uuid.uuid4().hex[:16]
        now = utc_now()
        values = {
            "local_id": local_id,
            "created_utc": now,
            "updated_utc": now,
            "state": "prepared",
            "kind": kind,
            "target_id": target_id,
            "target_name": target_name,
            "workspace": workspace,
            "payload_hash": payload_hash,
            "params_json": json.dumps(params, sort_keys=True),
            "quote_hash": quote_hash,
            "cost_exact": cost_exact,
            "scene_uuid": scene_uuid,
            "scene_path": scene_path,
            "target": target,
            "origin_json": json.dumps(origin or {}, sort_keys=True),
            "driver": driver,
            "label": label,
            "reviewed": 0,
        }

        def run(connection):
            connection.execute(f"INSERT INTO jobs({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})", tuple(values.values()))
            self._event(connection, local_id, "prepared", f"{kind} {target_id} {cost_exact} CU")
            return self._row(connection.execute("SELECT * FROM jobs WHERE local_id = ?", (local_id,)).fetchone())

        return self._write(run)

    def claim(self, local_id: str) -> dict:
        """``prepared`` -> ``submitting``, refusing when an identical request is Not confirmed."""

        def run(connection):
            row = connection.execute("SELECT * FROM jobs WHERE local_id = ?", (local_id,)).fetchone()
            if row is None:
                raise errors.NotFound(f"No local job {local_id}.")
            if row["state"] != "prepared":
                raise errors.Refused(f"Job {local_id} is {row['state']}, not prepared; it was not sent again.")
            blocking = [job for job in self.blocking_uncertain(row["workspace"], row["target_id"], row["target"] or "", row["payload_hash"], connection) if job["local_id"] != local_id]
            if blocking:
                raise errors.Refused(
                    "An identical request is Not confirmed; it may have run and been charged.",
                    hint=f"Review job {blocking[0]['local_id']} first: link it to a Scenario job or mark it reviewed.",
                )
            return self._transition(connection, local_id, "submitting", "claimed", claim_utc=utc_now(), claim_epoch=time.time(), owner=self.session_id)

        return self._write(run)

    def submitted(self, local_id: str, remote_job_id: str, note: str = "") -> dict:
        return self._write(lambda c: self._transition(c, local_id, "remote", note or "submitted", remote_job_id=remote_job_id, owner=""))

    def not_confirmed(self, local_id: str, message: str) -> dict:
        return self._write(lambda c: self._transition(c, local_id, "uncertain", message, error=message[:500], owner=""))

    def refused(self, local_id: str, message: str, hint: str = "") -> dict:
        return self._write(lambda c: self._transition(c, local_id, "failed", message, error=message[:500], hint=hint[:500], owner=""))

    def drop_prepared(self, local_id: str, note: str = "dropped before sending") -> dict:
        return self._write(lambda c: self._transition(c, local_id, "canceled", note))

    def set_state(self, local_id: str, state: str, note: str = "", **fields) -> dict:
        if state not in STATES:
            raise ValueError(state)
        return self._write(lambda c: self._transition(c, local_id, state, note, **fields))

    def update_fields(self, local_id: str, **fields) -> dict:
        """Changes fields without a state change (result data, charged cost)."""
        fields = {k: (json.dumps(v) if k in ("result_json", "origin_json") and not isinstance(v, str) else v) for k, v in fields.items()}

        def run(connection):
            fields["updated_utc"] = utc_now()
            assignments = ", ".join(f"{key} = ?" for key in fields)
            connection.execute(f"UPDATE jobs SET {assignments} WHERE local_id = ?", (*fields.values(), local_id))
            return self._row(connection.execute("SELECT * FROM jobs WHERE local_id = ?", (local_id,)).fetchone())

        return self._write(run)

    def link(self, local_id: str, remote_job_id: str) -> dict:
        """A person linked a Not confirmed row to the Scenario job it produced."""
        return self._write(lambda c: self._transition(c, local_id, "remote", f"linked by a person to {remote_job_id}", remote_job_id=remote_job_id, reviewed=1))

    def mark_reviewed(self, local_id: str, note: str = "reviewed by a person: no matching Scenario job") -> dict:
        def run(connection):
            row = connection.execute("SELECT state FROM jobs WHERE local_id = ?", (local_id,)).fetchone()
            if row is None or row["state"] != "uncertain":
                raise errors.Refused("Only a Not confirmed job can be marked reviewed.")
            connection.execute("UPDATE jobs SET reviewed = 1, updated_utc = ? WHERE local_id = ?", (utc_now(), local_id))
            self._event(connection, local_id, "uncertain", note)
            return self._row(connection.execute("SELECT * FROM jobs WHERE local_id = ?", (local_id,)).fetchone())

        return self._write(run)

    def claim_owner(self, local_id: str) -> dict:
        """Marks this session as the live owner of a download or apply."""
        return self.update_fields(local_id, owner=self.session_id)

    # -- recovery --------------------------------------------------------

    def _owner_alive(self, owner: str) -> bool:
        if not owner:
            return False
        if owner == self.session_id:
            return True
        path = os.path.join(self._locks_dir, f"session-{owner}.lock")
        if not os.path.exists(path):
            return False
        with open(path, "a+b") as handle:
            if _lock_file(handle, blocking=False):
                _unlock_file(handle)
                return False
            return True

    def recover(self) -> dict:
        """Run once at start. Only reads and relabels; nothing is resumed or sent."""
        changed = {"not_confirmed": [], "interrupted_downloads": [], "needs_review": []}

        def run(connection):
            for row in connection.execute("SELECT local_id, state, owner FROM jobs WHERE state IN ('submitting', 'downloading', 'applying')").fetchall():
                if self._owner_alive(row["owner"] or ""):
                    continue
                if row["state"] == "submitting":
                    self._transition(connection, row["local_id"], "uncertain", "Maya stopped while the request was being sent", error="Maya stopped while the request was being sent.", owner="")
                    changed["not_confirmed"].append(row["local_id"])
                elif row["state"] == "downloading":
                    self._transition(connection, row["local_id"], "download_failed", "download interrupted", error="Download interrupted; resume it from Jobs.", owner="")
                    changed["interrupted_downloads"].append(row["local_id"])
                else:
                    connection.execute("UPDATE jobs SET hint = ?, owner = '' WHERE local_id = ?", ("Maya stopped during the apply. Check the scene before applying again.", row["local_id"]))
                    self._event(connection, row["local_id"], "applying", "needs review: owner session ended")
                    changed["needs_review"].append(row["local_id"])
            return changed

        return self._write(run)
