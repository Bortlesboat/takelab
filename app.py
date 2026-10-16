from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from studio import BASE, Conflict, Studio


def create_app(data_dir: Path | None = None, *, start_workers: bool = True) -> Flask:
    app = Flask(__name__, static_folder=str(BASE / "static"))
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    studio = Studio(data_dir or Path(os.environ.get("TAKELAB_DATA", BASE / "data")), start_workers)
    app.extensions["studio"] = studio

    @app.before_request
    def local_only():
        hostname = urlsplit("http://" + request.host).hostname
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            abort(400, "TakeLab only accepts loopback hosts.")
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            abort(403, "Use TakeLab from its own local page.")
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            abort(403, "Cross-site requests are not allowed.")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.description), exc.code

    @app.get("/")
    def index():
        return send_file(BASE / "static/index.html")

    @app.get("/api/status")
    def status():
        return jsonify(**studio.health(), model="LTX-2.5", width=864, height=480, frames=121, fps=24)

    @app.get("/api/takes")
    def takes():
        return jsonify(takes=studio.list())

    @app.post("/api/takes")
    def generate():
        try:
            return jsonify(take=studio.submit(request.get_json())), 202
        except Conflict as exc:
            return jsonify(error=str(exc)), 409
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    def find(take_id):
        take = studio.get(take_id)
        if take is None:
            abort(404, "Take not found.")
        return take

    @app.get("/api/takes/<take_id>/workflow")
    def workflow(take_id):
        find(take_id)
        return send_file(io.BytesIO(json.dumps(studio.workflow(take_id), indent=2).encode()),
                         mimetype="application/json", as_attachment=True, download_name="workflow.json")

    @app.get("/api/takes/<take_id>/video")
    def video(take_id):
        take = find(take_id)
        path = studio.folder(take_id) / "video.mp4"
        if take["status"] != "succeeded" or not path.is_file():
            abort(404, "This take has no completed video yet.")
        return send_file(path, mimetype="video/mp4", conditional=True, download_name="take-" + take_id + ".mp4")

    @app.get("/api/takes/<take_id>/bundle")
    def bundle(take_id):
        take = find(take_id)
        path = studio.folder(take_id) / "video.mp4"
        if take["status"] != "succeeded" or not path.is_file():
            abort(404, "This take has no completed video yet.")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            output.write(path, "video.mp4")
            output.writestr("workflow.json", json.dumps(studio.workflow(take_id), indent=2))
            output.writestr("take.json", json.dumps(take, indent=2))
        archive.seek(0)
        return send_file(archive, mimetype="application/zip", as_attachment=True, download_name="takelab-" + take_id + ".zip")

    return app


if __name__ == "__main__":
    from waitress import serve
    serve(create_app(), host="127.0.0.1", port=int(os.environ.get("TAKELAB_PORT", "41732")), threads=6)
