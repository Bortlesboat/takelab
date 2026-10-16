from contextlib import contextmanager
from types import SimpleNamespace

from app import create_app


def request_body():
    return {
        "request_id": "b729f527-8bd1-44bd-a06d-0ac4600dceaa",
        "title": "Recovery check",
        "scene": "A paper boat on a pond.",
        "camera": "locked",
        "lighting": "golden",
        "sound": "Water and birds.",
        "seed": 42,
    }


def run_workers_inline(monkeypatch):
    monkeypatch.setattr(
        "studio.threading.Thread",
        lambda *, target, args, **kwargs: SimpleNamespace(start=lambda: target(*args)),
    )


def test_restart_recovers_saved_job_without_submitting_again(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_workers=False)
    store = app.extensions["studio"]
    store.health = lambda: dict(ready=True, busy=False, message="Ready")
    take = app.test_client().post("/api/takes", json=request_body()).json["take"]
    store.update(take["id"], job_id="saved-job", status="running")
    looked_up = []
    output = SimpleNamespace(
        content_type="video/mp4", name="recovered.mp4",
        to_file=lambda path: path.write_bytes(b"recovered video"),
    )

    def get_job(job_id):
        looked_up.append(job_id)
        return SimpleNamespace(id=job_id, status="succeeded", get_outputs=lambda node: [output])

    @contextmanager
    def fake_client(**kwargs):
        # A submission attempt fails this test because this client only exposes saved jobs.
        yield SimpleNamespace(jobs=SimpleNamespace(get=get_job))

    monkeypatch.setattr("studio.Comfy", fake_client)
    run_workers_inline(monkeypatch)
    restarted = create_app(tmp_path, start_workers=True)
    client = restarted.test_client()
    recovered = client.get("/api/takes").json["takes"][0]
    assert looked_up == ["saved-job"]
    assert recovered["id"] == take["id"]
    assert recovered["status"] == "succeeded"
    assert recovered["job_id"] == "saved-job"
    assert client.get(recovered["video_url"]).data == b"recovered video"


def test_lost_submit_response_does_not_repeat_submission(tmp_path, monkeypatch):
    calls = []

    def submit(workflow, **kwargs):
        calls.append(kwargs["idempotency_key"])
        raise TimeoutError("The service may have accepted the job")

    @contextmanager
    def fake_client(**kwargs):
        yield SimpleNamespace(workflows=SimpleNamespace(from_json=lambda graph: graph), submit=submit)

    monkeypatch.setattr("studio.Comfy", fake_client)
    run_workers_inline(monkeypatch)
    app = create_app(tmp_path, start_workers=True)
    app.extensions["studio"].health = lambda: dict(ready=True, busy=False, message="Ready")
    client = app.test_client()
    body = request_body()
    assert client.post("/api/takes", json=body).status_code == 202
    replay = client.post("/api/takes", json=body)
    assert replay.status_code == 202
    assert replay.json["take"]["status"] == "unknown"
    assert replay.json["take"]["job_id"] is None
    assert calls == ["takelab-" + body["request_id"]]
    assert len(client.get("/api/takes").json["takes"]) == 1


def test_restart_without_job_id_never_opens_sdk(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_workers=False)
    app.extensions["studio"].health = lambda: dict(ready=True, busy=False, message="Ready")
    take = app.test_client().post("/api/takes", json=request_body()).json["take"]
    sdk_calls = []

    def unexpected_client(**kwargs):
        sdk_calls.append(kwargs)
        raise AssertionError("An unconfirmed submission must not be restarted")

    monkeypatch.setattr("studio.Comfy", unexpected_client)
    run_workers_inline(monkeypatch)
    restarted = create_app(tmp_path, start_workers=True)
    saved = restarted.extensions["studio"].get(take["id"])
    assert saved["status"] == "unknown"
    assert saved["job_id"] is None
    assert sdk_calls == []


def test_output_failure_keeps_saved_job_recoverable(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_workers=False)
    store = app.extensions["studio"]
    store.health = lambda: dict(ready=True, busy=False, message="Ready")
    take = app.test_client().post("/api/takes", json=request_body()).json["take"]
    store.update(take["id"], job_id="saved-job", status="running")
    downloads = []
    looked_up = []

    def download(path):
        downloads.append(path)
        if len(downloads) == 1:
            raise OSError("Temporary output failure")
        path.write_bytes(b"recovered on second restart")

    output = SimpleNamespace(content_type="video/mp4", name="recovered.mp4", to_file=download)

    def get_job(job_id):
        looked_up.append(job_id)
        return SimpleNamespace(id=job_id, status="succeeded", get_outputs=lambda node: [output])

    @contextmanager
    def fake_client(**kwargs):
        yield SimpleNamespace(jobs=SimpleNamespace(get=get_job))

    monkeypatch.setattr("studio.Comfy", fake_client)
    run_workers_inline(monkeypatch)
    first_restart = create_app(tmp_path, start_workers=True)
    failed = first_restart.extensions["studio"].get(take["id"])
    assert failed["status"] == "unknown"
    assert failed["job_id"] == "saved-job"
    assert failed["video_url"] is None
    second_restart = create_app(tmp_path, start_workers=True)
    recovered = second_restart.extensions["studio"].get(take["id"])
    assert recovered["status"] == "succeeded"
    assert looked_up == ["saved-job", "saved-job"]
    assert second_restart.test_client().get(recovered["video_url"]).data == b"recovered on second restart"
