from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from comfy_sdk import Comfy

BASE = Path(__file__).resolve().parent
ACTIVE = {"submitting", "queued", "running"}
CAMERAS = {
    "locked": "The camera stays locked off on a tripod.",
    "push": "The camera slowly dollies forward toward the subject.",
    "orbit": "The camera makes a gentle clockwise orbit around the subject.",
    "track": "The camera tracks smoothly from left to right alongside the subject.",
}
LIGHTS = {
    "golden": "Soft golden-hour sunlight with warm highlights and natural shadows.",
    "studio": "Soft controlled studio lighting, clean highlights and a gentle fill.",
    "night": "Cinematic night lighting with warm practical lights and deep shadows.",
    "overcast": "Soft overcast daylight with natural muted colors.",
}


class Conflict(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_take(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Send a JSON object describing the take.")
    try:
        request_id = str(uuid.UUID(raw.get("request_id", "")))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid request_id is required.") from None
    result = {"request_id": request_id}
    for key, minimum, maximum in (("title", 1, 80), ("scene", 1, 1600), ("sound", 0, 400)):
        value = raw.get(key, "")
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise ValueError(f"{key.capitalize()} must contain {minimum}–{maximum} characters.")
        result[key] = value.strip()
    for key, choices in (("camera", CAMERAS), ("lighting", LIGHTS)):
        if not isinstance(raw.get(key), str) or raw[key] not in choices:
            raise ValueError(f"Choose a listed {key} option.")
        result[key] = raw[key]
    seed = raw.get("seed")
    if type(seed) is not int or not 0 <= seed <= 4294967295:
        raise ValueError("Seed must be an integer from 0 to 4294967295.")
    result["seed"] = seed
    return result


def build_workflow(data: dict) -> dict:
    graph = json.loads((BASE / "workflows/ltx25.json").read_text(encoding="utf-8-sig"))
    graph["5"]["inputs"]["text"] = " ".join((
        data["scene"], "One continuous five-second cinematic shot.", CAMERAS[data["camera"]],
        LIGHTS[data["lighting"]], "Audio: " + (data["sound"] or "Natural ambient sound, no music or dialogue."),
        "No text, logos, watermarks, or cuts.",
    ))
    graph["11"]["inputs"]["noise_seed"] = data["seed"]
    graph["20"]["inputs"]["filename_prefix"] = "TakeLab/" + data["request_id"]
    return graph


def loopback_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("TakeLab requires a loopback http URL, without credentials, path, or query.")
    return value.rstrip("/")


class Studio:
    def __init__(self, root: Path, start_workers: bool = True):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "takes.sqlite3"
        self.proxy = loopback_url(os.environ.get("COMFY_BASE_URL", "http://127.0.0.1:8189"))
        self.native = loopback_url(os.environ.get("TAKELAB_COMFY_URL", "http://127.0.0.1:8188"))
        os.environ["COMFY_BASE_URL"] = self.proxy
        os.environ.pop("COMFY_API_KEY", None)
        # SDK 0.5 has no transport override; keep loopback traffic out of ambient proxies.
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        self.start_workers = start_workers
        self._models_checked = 0.0
        self._models_ready = False
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS takes (id TEXT PRIMARY KEY, request TEXT NOT NULL, document TEXT NOT NULL, workflow TEXT NOT NULL)")
        for take in self.list():
            if take["status"] in ACTIVE or (take["status"] == "unknown" and take["job_id"]):
                if take["job_id"] and start_workers:
                    self.launch(take["id"], resume=True)
                else:
                    self.update(take["id"], status="unknown", error="The app stopped before the submission could be confirmed. This take will not be submitted again.")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def folder(self, take_id: str) -> Path:
        return self.root / str(uuid.UUID(take_id))

    def get(self, take_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT document FROM takes WHERE id=?", (take_id,)).fetchone()
        return self.public(json.loads(row[0])) if row else None

    def list(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT document FROM takes ORDER BY rowid DESC").fetchall()
        return [self.public(json.loads(row[0])) for row in rows]

    @staticmethod
    def public(take: dict) -> dict:
        base = f'/api/takes/{take["id"]}'
        take["workflow_url"] = base + "/workflow"
        take["video_url"] = base + "/video" if take["status"] == "succeeded" else None
        take["bundle_url"] = base + "/bundle" if take["status"] == "succeeded" else None
        return take

    def update(self, take_id: str, **values) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document FROM takes WHERE id=?", (take_id,)).fetchone()
            data = json.loads(row[0])
            data.update(values, updated_at=now())
            db.execute("UPDATE takes SET document=? WHERE id=?", (json.dumps(data), take_id))

    def workflow(self, take_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT workflow FROM takes WHERE id=?", (take_id,)).fetchone()
        return json.loads(row[0])

    def health(self) -> dict:
        try:
            with httpx.Client(timeout=5, trust_env=False) as client:
                client.get(self.proxy + "/api/v2/health").raise_for_status()
                queue_response = client.get(self.native + "/queue")
                queue_response.raise_for_status()
                queue = queue_response.json()
                if time.monotonic() - self._models_checked > 30:
                    graph = json.loads((BASE / "workflows/ltx25.json").read_text(encoding="utf-8-sig"))
                    missing = []
                    for node_id, field in (("1", "unet_name"), ("2", "clip_name"), ("3", "vae_name"), ("4", "vae_name")):
                        node = graph[node_id]
                        response = client.get(self.native + "/object_info/" + node["class_type"])
                        response.raise_for_status()
                        choices = response.json()[node["class_type"]]["input"]["required"][field][0]
                        if node["inputs"][field] not in choices:
                            missing.append(node["inputs"][field])
                    self._models_ready = not missing
                    self._models_checked = time.monotonic()
            busy = bool(queue.get("queue_running") or queue.get("queue_pending"))
            busy = busy or any(t["status"] in ACTIVE for t in self.list())
            return {"ready": self._models_ready, "busy": busy,
                    "message": "Rendering in progress" if busy else "Ready to direct" if self._models_ready else "Install the four LTX model files listed in the setup guide."}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {"ready": False, "busy": any(t["status"] in ACTIVE for t in self.list()),
                    "message": "Start ComfyUI and the local Comfy API proxy. See the setup guide."}

    def submit(self, raw: object) -> dict:
        data = validate_take(raw)
        request_json = json.dumps(data, sort_keys=True)
        take_id = data["request_id"]
        graph = build_workflow(data)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT request,document FROM takes WHERE id=?", (take_id,)).fetchone()
            if existing:
                if existing["request"] != request_json:
                    raise Conflict("This request ID already belongs to different settings.")
                return self.public(json.loads(existing["document"]))
            # Read through this connection to retain the submission lock across the busy check.
            rows = db.execute("SELECT document FROM takes").fetchall()
            if any(json.loads(r[0])["status"] in ACTIVE for r in rows):
                raise Conflict("A take is already rendering. Wait for it to finish.")
            state = self.health()
            if not state["ready"]:
                raise Conflict(state["message"])
            if state["busy"]:
                raise Conflict("ComfyUI is busy. Wait for its queue to finish.")
            take = {k: v for k, v in data.items() if k != "request_id"}
            take.update(id=take_id, prompt=graph["5"]["inputs"]["text"], status="submitting",
                        created_at=now(), updated_at=now(), job_id=None, error=None, elapsed_seconds=None)
            self.folder(take_id).mkdir(exist_ok=True)
            db.execute("INSERT INTO takes VALUES (?,?,?,?)", (take_id, request_json, json.dumps(take), json.dumps(graph)))
        if self.start_workers:
            self.launch(take_id)
        return self.public(take)

    def launch(self, take_id: str, resume: bool = False) -> None:
        threading.Thread(target=self.render, args=(take_id, resume), daemon=True, name="take-" + take_id).start()

    def render(self, take_id: str, resume: bool) -> None:
        started = time.monotonic()
        job = None
        try:
            with Comfy(client_info="takelab") as client:
                if resume:
                    job = client.jobs.get(self.get(take_id)["job_id"])
                else:
                    workflow = client.workflows.from_json(self.workflow(take_id))
                    job = client.submit(workflow, idempotency_key="takelab-" + take_id)
                    self.update(take_id, job_id=job.id, status="queued")
                failures = 0
                while job.status not in {"succeeded", "failed", "canceled", "expired"}:
                    if time.monotonic() - started > 1800:
                        raise TimeoutError("Render observation timed out")
                    self.update(take_id, status="running" if job.status == "running" else "queued")
                    time.sleep(2)
                    try:
                        job.refresh()
                        failures = 0
                    except Exception:
                        failures += 1
                        if failures >= 3:
                            raise
                if job.status != "succeeded":
                    self.update(take_id, status="failed", error="ComfyUI ended the job without a video. Check its console before making a new take.")
                    return
                outputs = job.get_outputs("20")
                videos = [o for o in outputs if o.content_type == "video/mp4" or o.name.lower().endswith(".mp4")]
                if not videos:
                    raise ValueError("The workflow returned no MP4")
                destination = self.folder(take_id) / "video.mp4"
                partial = destination.with_suffix(".part")
                videos[0].to_file(partial)
                if partial.stat().st_size == 0:
                    raise ValueError("Empty output")
                partial.replace(destination)
                self.update(take_id, status="succeeded", error=None, elapsed_seconds=round(time.monotonic() - started, 2))
        except Exception as exc:
            logging.exception("Take %s could not complete", take_id)
            definitive = getattr(exc, "http_status", None) in {400, 401, 403, 422}
            self.update(take_id, status="failed" if definitive else "unknown",
                        error=f"Could not confirm the render ({type(exc).__name__}). It will not be submitted again automatically. Check ComfyUI; restarting TakeLab can recover a saved job ID.")
