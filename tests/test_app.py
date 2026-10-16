import io
import json
import uuid
import zipfile

import pytest

from app import create_app
from studio import build_workflow, validate_take


def payload(**changes):
    return dict(request_id=str(uuid.uuid4()), title="Paper boat", scene="A paper boat on a pond.",
                camera="locked", lighting="golden", sound="Water and birds.", seed=42, **changes)


@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path, start_workers=False)
    app.config["TESTING"] = True
    app.extensions["studio"].health = lambda: dict(ready=True, busy=False, message="Ready")
    return app


def test_workflow_reproducible_and_aligned():
    data = validate_take(payload())
    graph = build_workflow(data)
    assert graph["8"]["inputs"]["length"] == graph["9"]["inputs"]["frames_number"] == 121
    assert graph["7"]["inputs"]["frame_rate"] == graph["19"]["inputs"]["fps"] == 24
    assert graph["11"]["inputs"]["noise_seed"] == 42
    assert "paper boat" in graph["5"]["inputs"]["text"]
    assert build_workflow(data) == graph


@pytest.mark.parametrize("field,value", [("seed", True), ("seed", -1), ("camera", "fly-away"),
                                        ("scene", ""), ("title", "x" * 81), ("request_id", "../escape")])
def test_invalid_input(app, field, value):
    data = payload()
    data[field] = value
    assert app.test_client().post("/api/takes", json=data).status_code == 400
    assert app.test_client().get("/api/takes").json == {"takes": []}


def test_idempotency_and_busy(app):
    client = app.test_client()
    data = payload()
    first = client.post("/api/takes", json=data)
    assert first.status_code == 202
    assert client.post("/api/takes", json=data).json == first.json
    assert client.post("/api/takes", json={**data, "scene": "Changed"}).status_code == 409
    assert client.post("/api/takes", json=payload()).status_code == 409
    assert len(client.get("/api/takes").json["takes"]) == 1


def test_native_busy_does_not_create_job(app):
    app.extensions["studio"].health = lambda: dict(ready=True, busy=True, message="Busy")
    client = app.test_client()
    assert client.post("/api/takes", json=payload()).status_code == 409
    assert client.get("/api/takes").json == {"takes": []}


def test_cross_site_and_host_protection(app):
    client = app.test_client()
    assert client.post("/api/takes", json=payload(), headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/takes", json=payload(), headers={"Origin": "null"}).status_code == 403
    assert client.get("/api/takes", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/takes").status_code == 200


def test_external_link_can_open_home_but_not_api_or_frames(app):
    client = app.test_client()
    navigation = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
    for method in (client.get, client.head):
        assert method("/", headers=navigation).status_code == 200
        assert method("/api/takes", headers=navigation).status_code == 403
    assert client.post("/", headers=navigation).status_code == 403
    assert client.post("/api/takes", json=payload(), headers=navigation).status_code == 403
    assert client.get("/", headers={**navigation, "Sec-Fetch-Dest": "iframe"}).status_code == 403
    assert client.get("/", headers={**navigation, "Sec-Fetch-Mode": "cors"}).status_code == 403
    assert client.get("/", headers={**navigation, "Origin": "https://evil.example"}).status_code == 403
    assert client.get("/", headers={**navigation, "Host": "evil.example"}).status_code == 400


def test_workflow_and_bundle_contain_only_take_files(app):
    client = app.test_client()
    take = client.post("/api/takes", json=payload()).json["take"]
    assert client.get(take["workflow_url"]).json["11"]["inputs"]["noise_seed"] == 42
    assert client.get(f'/api/takes/{take["id"]}/video').status_code == 404
    store = app.extensions["studio"]
    (store.folder(take["id"]) / "video.mp4").write_bytes(b"test video")
    store.update(take["id"], status="succeeded", elapsed_seconds=2)
    response = client.get(f'/api/takes/{take["id"]}/bundle')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert set(archive.namelist()) == {"video.mp4", "workflow.json", "take.json"}
        assert json.loads(archive.read("take.json"))["seed"] == 42
    assert client.get("/api/takes/../../requirements.txt/video").status_code == 404


def test_restart_does_not_resubmit_uncertain_job(app):
    client = app.test_client()
    take = client.post("/api/takes", json=payload()).json["take"]
    resumed = create_app(app.extensions["studio"].root, start_workers=False)
    stored = resumed.test_client().get("/api/takes").json["takes"][0]
    assert stored["id"] == take["id"]
    assert stored["status"] == "unknown"
    assert stored["job_id"] is None
