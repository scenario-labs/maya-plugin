"""Shared test setup: the package on sys.path, a private per-test home, an in-memory credential store."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ScenarioForMaya", "scripts"))
sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENARIO_MAYA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SCENARIO_MAYA_CREDSTORE", "memory")
    for name in ("SCENARIO_API_KEY", "SCENARIO_API_SECRET", "SCENARIO_NO_SPEND", "SCENARIO_MAYA_OFFLINE", "SCENARIO_TEAM_ID", "SCENARIO_PROJECT_ID", "SCENARIO_MCP_URL"):
        monkeypatch.delenv(name, raising=False)
    from scenario_maya.core import credstore

    credstore.set_default_store(None)
    yield tmp_path / "home"
    credstore.set_default_store(None)


@pytest.fixture
def fake():
    from tests.fake_backend import FakeScenario

    with FakeScenario() as server:
        yield server


@pytest.fixture
def session(fake):
    from scenario_maya.core.auth import Credentials
    from scenario_maya.core.credstore import MemoryStore
    from scenario_maya.core.ledger import Ledger
    from scenario_maya.core.oauth import OAuthApp, OAuthClient
    from scenario_maya.core.session import Session
    from scenario_maya.core.settings import Settings
    from tests.fake_backend.fake_scenario import CLIENT_ID

    settings = Settings()
    credentials = Credentials(settings, MemoryStore(), OAuthClient(app=OAuthApp(fake.base, CLIENT_ID)))
    ledger = Ledger()
    instance = Session(settings=settings, ledger=ledger, credentials=credentials, endpoint=fake.endpoint)
    yield instance
    ledger.close()
