"""The Image lane end to end in mayapy against the fake Scenario server (0 CU):
price, generate, follow, download, land, undo; and recovery after a restart."""

import os
import threading

import pytest

from tests.fake_backend import API_KEY, API_SECRET
from tests.maya.conftest import MODULE, PLUGIN, fresh, pump_until

FLARE = "model_openai-gpt-image-2-5-flare"


@pytest.fixture
def lane(fake, monkeypatch, cmds, tmp_path):
    monkeypatch.setenv("SCENARIO_MCP_URL", fake.endpoint)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True, infinity=True)
    os.makedirs(tmp_path / "project", exist_ok=True)
    cmds.workspace(str(tmp_path / "project"), openWorkspace=True)
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    runtime = fresh("scenario_maya.maya.runtime").get()
    done = runtime.background(lambda: runtime.session.sign_in_api_key(API_KEY, API_SECRET))
    pump_until(done.done)
    done.result()
    yield runtime
    if cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN)


def generate(runtime, prompt="a carved wooden treasure chest, game prop"):
    params = {"prompt": prompt}
    priced = runtime.background(lambda: runtime.session.price(FLARE, params))
    pump_until(priced.done)
    quote = priced.result()
    sent = []
    runtime.jobs.generate(quote.quote_id, approved_cost=quote.cu_cost_exact, params=params, origin={}, model_name="GPT Image 2.5 Flare", on_sent=sent.append, on_error=sent.append)
    pump_until(lambda: sent)
    assert isinstance(sent[0], dict), sent[0]
    return sent[0]["local_id"]


def test_generate_follow_download_and_land(lane, fake, cmds, tmp_path):
    runtime = lane
    events = []
    runtime.subscribe(lambda event, data: events.append((event, data.get("row", {}).get("state"), threading.current_thread() is threading.main_thread())) if event == "job" else None)
    local_id = generate(runtime)
    # The ledger turns ready on the worker; the matching event reaches the main thread just after.
    pump_until(lambda: events and events[-1][1] == "ready", timeout=20)
    row = runtime.ledger.get(local_id)
    image = row["result"]["files"][0]["path"]
    assert image.startswith(str(tmp_path / "project" / "sourceimages" / "scenario"))
    assert os.path.exists(os.path.join(os.path.dirname(image), "scenario.json"))
    states = [state for _event, state, _main in events]
    assert states[0] == "remote" and states[-1] == "ready" and all(main for *_rest, main in events)
    assert len(fake.state.paid_runs()) == 1
    made = runtime.jobs.land(local_id, "card")
    assert cmds.getAttr(made["top"] + ".scenario_job_id") == row["remote_job_id"]
    assert cmds.getAttr(made["top"] + ".scenario_charged_cu") == "11"
    assert runtime.ledger.get(local_id)["state"] == "applied"
    cmds.undo()
    assert not cmds.objExists(made["top"])
    again = runtime.jobs.land(local_id, "image_plane", camera=("persp", "perspShape"))
    assert cmds.objExists(again["image_plane"])
    assert len(fake.state.paid_runs()) == 1, "landing never spends"


def test_material_needs_a_selection_and_says_so(lane, cmds):
    runtime = lane
    local_id = generate(runtime)
    pump_until(lambda: runtime.ledger.get(local_id)["state"] == "ready", timeout=20)
    cmds.select(clear=True)
    landing = fresh("scenario_maya.maya.landing")
    with pytest.raises(landing.LandingError, match="select a mesh"):
        runtime.jobs.land(local_id, "material")
    assert runtime.ledger.get(local_id)["state"] == "ready"


def test_downloads_wait_for_a_person_after_a_restart(lane, fake, cmds):
    runtime = lane
    fake.state.polls_to_finish = 1000
    local_id = generate(runtime)
    pump_until(lambda: runtime.ledger.get(local_id)["result"].get("status") == "in-progress", timeout=20)
    cmds.unloadPlugin(PLUGIN)
    fake.state.polls_to_finish = 0
    cmds.loadPlugin(os.path.join(MODULE, "plug-ins", "scenario_for_maya.py"))
    runtime = fresh("scenario_maya.maya.runtime").get()
    # Tests keep credentials in memory, which a reload forgets; the Keychain would not.
    signed = runtime.background(lambda: runtime.session.sign_in_api_key(API_KEY, API_SECRET))
    pump_until(signed.done)
    assert runtime.ledger.get(local_id)["state"] == "remote", "nothing resumes by itself at load"
    assert runtime.jobs.resume_polling() == 1
    pump_until(lambda: runtime.ledger.get(local_id)["state"] == "ready", timeout=20)
    assert len(fake.state.paid_runs()) == 1
