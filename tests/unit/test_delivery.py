"""Names, downloads, following jobs and result folders, against the fake Scenario server (0 CU)."""

import hashlib
import json
import os

import pytest

from scenario_maya.core import catalog, delivery, downloads, errors, lanes, naming, provenance
from tests.fake_backend import API_KEY, API_SECRET

FLARE = "model_openai-gpt-image-2-5-flare"


@pytest.fixture
def signed_in(session):
    session.sign_in_api_key(API_KEY, API_SECRET)
    return session


def sent_job(session, prompt="a carved wooden treasure chest, game prop"):
    params = {"prompt": prompt}
    quote = session.price(FLARE, params)
    return session.submit(quote.quote_id, approved_cost=quote.cu_cost_exact, params=params, model_name="GPT Image 2.5 Flare")


# -- names ---------------------------------------------------------------------


def test_slug_is_ascii_without_leading_digit():
    assert naming.slug("A carved wooden treasure chest, game prop") == "carved_wooden_treasure_chest"
    assert naming.slug("3 épées rouillées") == "n3_epees_rouillees"
    assert naming.slug("") == "scenario"
    assert naming.slug("!!!") == "scenario"
    assert naming.node_name("9-lives café") == "n9_lives_cafe"


def test_tail_and_extensions():
    assert naming.tail("asset_Fixture000000000S8Guqw") == "S8Guqw"
    assert naming.extension_for("image/png") == ".png"
    assert naming.extension_for("image/jpeg; charset=binary") == ".jpg"
    assert naming.extension_for("", "/x/asset_1.glb") == ".glb"
    assert naming.extension_for("application/octet-stream", "/x/asset_1") == ".bin"


def test_unique_path_never_reuses_a_name(tmp_path):
    first = naming.unique_path(str(tmp_path), "chest", ".png")
    open(first, "w").close()
    second = naming.unique_path(str(tmp_path), "chest", ".png")
    open(second + ".part", "w").close()
    third = naming.unique_path(str(tmp_path), "chest", ".png")
    assert [os.path.basename(p) for p in (first, second, third)] == ["chest.png", "chest_2.png", "chest_3.png"]


# -- downloads -------------------------------------------------------------------


def served(fake, name="f.bin", size=600_000):
    data = os.urandom(size)
    fake.state.files[name] = data
    return f"{fake.base}/files/{name}", data


def test_download_writes_receipt_and_never_overwrites(fake, tmp_path):
    url, data = served(fake)
    path = str(tmp_path / "out" / "f.bin")
    seen = []
    receipt = downloads.download(lambda: {"url": url, "mime_type": "application/octet-stream"}, path, progress=lambda got, total: seen.append((got, total)))
    assert open(path, "rb").read() == data
    assert receipt["sha256"] == hashlib.sha256(data).hexdigest() and receipt["size"] == len(data)
    assert seen[-1] == (len(data), len(data))
    assert not os.path.exists(path + ".part")
    assert downloads.verify(receipt)
    with pytest.raises(errors.Refused, match="never overwrite"):
        downloads.download(lambda: {"url": url}, path)


def test_download_resumes_with_a_range_and_a_fresh_link(fake, tmp_path):
    url, data = served(fake)
    path = str(tmp_path / "f.bin")
    with open(path + ".part", "wb") as handle:
        handle.write(data[:1000])
    links = []

    def get_link():
        links.append(1)
        return {"url": url}

    downloads.download(get_link, path)
    assert open(path, "rb").read() == data
    assert fake.state.file_requests[-1] == ("f.bin", "bytes=1000-")
    assert len(links) == 1


def test_download_retries_a_cut_connection_with_a_new_link(fake, tmp_path):
    url, data = served(fake)
    fake.state.file_faults["f.bin"] = ["cut"]
    links = []

    def get_link():
        links.append(1)
        return {"url": url}

    downloads.download(get_link, str(tmp_path / "f.bin"), sleep=lambda s: None)
    assert open(tmp_path / "f.bin", "rb").read() == data
    assert len(links) == 2
    assert fake.state.file_requests[1][1].startswith("bytes=")


def test_download_retries_503_then_gives_up(fake, tmp_path):
    url, _data = served(fake)
    fake.state.file_faults["f.bin"] = ["503", "503", "503"]
    with pytest.raises(errors.ServerError):
        downloads.download(lambda: {"url": url}, str(tmp_path / "f.bin"), sleep=lambda s: None)
    assert len(fake.state.file_requests) == 3


def test_download_refuses_unexpected_hosts(fake, tmp_path):
    with pytest.raises(errors.ProtocolError, match="unexpected host"):
        downloads.download(lambda: {"url": "https://files.example.net/x.png"}, str(tmp_path / "x.png"))
    with pytest.raises(errors.ProtocolError, match="unexpected host"):
        downloads.download(lambda: {"url": "http://example.net/x.png"}, str(tmp_path / "x.png"))
    url, _data = served(fake)
    fake.state.file_faults["f.bin"] = ["redirect:https://files.example.net/f.bin"]
    with pytest.raises(errors.ProtocolError, match="redirected to an unexpected host"):
        downloads.download(lambda: {"url": url}, str(tmp_path / "f.bin"))


def test_allowed_hosts():
    assert downloads.allowed_url("https://cdn.cloud.scenario.com/assets-transform/asset_1?p=100")
    assert downloads.allowed_url("https://bucket.s3.eu-west-1.amazonaws.com/x")
    assert not downloads.allowed_url("https://scenario.com.example.net/x")
    assert not downloads.allowed_url("http://cdn.cloud.scenario.com/x")


def test_cancel_keeps_the_part_file(fake, tmp_path):
    import threading

    url, _data = served(fake)
    stop = threading.Event()
    path = str(tmp_path / "f.bin")

    def progress(got, total):
        stop.set()

    with pytest.raises(downloads.Cancelled):
        downloads.download(lambda: {"url": url}, path, progress=progress, cancel=stop)
    assert os.path.exists(path + ".part") and not os.path.exists(path)


# -- following a job ---------------------------------------------------------------


def test_follow_until_finished_then_download(signed_in, fake, tmp_path):
    row = sent_job(signed_in)
    updates = []
    row = delivery.follow(signed_in, row["local_id"], on_update=lambda r, note: updates.append((r["state"], note)), sleep=lambda s: None)
    assert row["state"] == "succeeded" and row["charged_exact"] == "11"
    assert updates[-1] == ("succeeded", "")
    root = str(tmp_path / "sourceimages" / "scenario")
    ready = delivery.download_results(signed_in, row["local_id"], root, provenance={"scene_uuid": "abc"})
    assert ready["state"] == "ready"
    files = ready["result"]["files"]
    assert len(files) == 1 and files[0]["asset_id"] == ready["result"]["asset_ids"][0]
    assert os.path.basename(ready["result"]["folder"]).startswith("carved_wooden_treasure_chest_")
    assert files[0]["file"].endswith(".png") and os.path.exists(files[0]["path"])
    sidecar = json.load(open(os.path.join(ready["result"]["folder"], "scenario.json")))
    assert sidecar["job"]["charged_cu"] == "11" and sidecar["files"][0]["sha256"] == files[0]["sha256"]
    assert "path" not in sidecar["files"][0] and "http" not in json.dumps(sidecar)
    calls = len(fake.state.tool_calls("asset_download"))
    again = delivery.download_results(signed_in, row["local_id"], root)
    assert again["state"] == "ready" and len(fake.state.tool_calls("asset_download")) == calls


def test_failed_download_can_resume(signed_in, fake, tmp_path):
    row = delivery.follow(signed_in, sent_job(signed_in)["local_id"], sleep=lambda s: None)
    asset_id = row["result"]["asset_ids"][0]
    name = fake.state.assets[asset_id]["file"]
    fake.state.file_faults[name] = ["503", "503", "503"]
    with pytest.raises(errors.ServerError):
        delivery.download_results(signed_in, row["local_id"], str(tmp_path), sleep=lambda s: None)
    failed = signed_in.ledger.get(row["local_id"])
    assert failed["state"] == "download_failed" and "503" in failed["error"]
    ready = delivery.download_results(signed_in, row["local_id"], str(tmp_path), sleep=lambda s: None)
    assert ready["state"] == "ready" and ready["result"]["folder"] == failed["result"]["folder"]


class _FlakySession:
    """``refresh_job`` fails the way a lost connection does, then answers."""

    def __init__(self, failures, error):
        self.failures = failures
        self.error = error
        self.ledger = self
        self.row = {"local_id": "l1", "state": "remote", "result": {}}
        self.fields = {}

    def get(self, local_id):
        return dict(self.row)

    def update_fields(self, local_id, **fields):
        self.fields.update(fields)
        return dict(self.row)

    def refresh_job(self, local_id):
        if self.failures:
            self.failures -= 1
            raise self.error
        self.row["state"] = "succeeded"
        return dict(self.row)


def test_follow_backs_off_on_transient_errors():
    flaky = _FlakySession(3, errors.NetworkError("lost"))
    waits, notes = [], []
    row = delivery.follow(flaky, "l1", on_update=lambda r, note: notes.append(note), sleep=waits.append)
    assert row["state"] == "succeeded"
    assert waits == [4.0, 8.0, 16.0]
    assert notes[0] == "Status not refreshed; retrying in 4 s" and notes[-1] == ""


def test_follow_honours_retry_after_and_pauses_after_eight():
    flaky = _FlakySession(1, errors.RateLimited("slow", retry_after=30))
    waits = []
    delivery.follow(flaky, "l1", sleep=waits.append)
    assert waits == [30]
    flaky = _FlakySession(20, errors.ServerError("down"))
    with pytest.raises(errors.ServerError):
        delivery.follow(flaky, "l1", sleep=lambda s: None)
    assert "eight times" in flaky.fields["hint"]


def test_follow_pauses_on_other_errors():
    flaky = _FlakySession(1, errors.Forbidden("no"))
    with pytest.raises(errors.Forbidden):
        delivery.follow(flaky, "l1", sleep=lambda s: None)
    assert flaky.fields["hint"].startswith("Delivery paused")


# -- catalog, lanes, provenance ------------------------------------------------------


def test_catalog_orders_quick_picks_first_and_hides_legacy(tmp_path):
    cache = catalog.Catalog(str(tmp_path / "catalog.json"))
    rows = [
        {"id": "model_old", "name": "Old", "capabilities": ["txt2img"], "tags": ["sc:legacy"], "createdAt": "2025-01-01"},
        {"id": "model_new", "name": "New painter", "capabilities": ["txt2img"], "tags": [], "createdAt": "2026-10-01"},
        {"id": "model_mid", "name": "Mid", "capabilities": ["img2img"], "tags": [], "createdAt": "2026-05-01"},
        {"id": FLARE, "name": "GPT Image 2.5 Flare", "capabilities": ["txt2img", "img2img"], "tags": [], "createdAt": "2026-01-01"},
        {"id": "model_mesh", "name": "Mesh", "capabilities": ["txt23d"], "tags": [], "createdAt": "2026-10-10"},
    ]
    cache._data = {"workspaces": {"w": {"fetched": 0, "models": rows}}}
    ids = [row["id"] for row in cache.for_lane("w", lanes.IMAGE)]
    assert ids == [FLARE, "model_new", "model_mid"]
    assert [row["id"] for row in cache.for_lane("w", lanes.IMAGE, favorites=["model_mid"])][0] == "model_mid"
    assert [row["id"] for row in cache.for_lane("w", lanes.IMAGE, text="painter")] == ["model_new"]
    assert "model_old" in [row["id"] for row in cache.for_lane("w", lanes.IMAGE, show_legacy=True)]
    assert not cache.fresh("w")


def test_catalog_refresh_saves_per_workspace(signed_in, tmp_path):
    cache = catalog.Catalog(str(tmp_path / "catalog.json"))
    rows = cache.refresh(signed_in.backend(), "team/proj", modalities=("3d",))
    assert rows and cache.fresh("team/proj") and not cache.fresh("other")
    assert catalog.Catalog(str(tmp_path / "catalog.json")).models("team/proj") == rows


def test_provenance_has_inputs_and_no_secrets():
    row = {
        "remote_job_id": "job_1",
        "target_id": FLARE,
        "target_name": "GPT Image 2.5 Flare",
        "params": {"prompt": "a chest", "referenceImages": ["asset_ref1"], "numOutputs": 2},
        "cost_exact": "22",
        "charged_exact": "22",
        "created_utc": "2026-10-19T10:00:00Z",
    }
    attrs = provenance.attributes(row, "asset_out1", maya_version="2027.2")
    assert set(attrs) == set(provenance.NAMES)
    assert attrs["scenario_prompt"] == "a chest" and json.loads(attrs["scenario_input_asset_ids"]) == ["asset_ref1"]
    assert json.loads(attrs["scenario_parameters"]) == {"numOutputs": 2}
    assert attrs["scenario_apply"].startswith("import ")
    assert provenance.attributes(row, "asset_out1", maya_version="2027.2", store_prompt=False)["scenario_prompt"] == ""
    assert provenance.web_url("asset_1", "team_1", "proj_1") == "https://app.scenario.com/assets?openAssetId=asset_1&teamId=team_1&projectId=proj_1"
