import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from comfy_sdk import Comfy
from comfy_sdk.exceptions import ComfyError

from studio import Studio


@contextmanager
def recording_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = b'{"error": "not_found", "message": "No such job"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_sdk_keeps_local_requests_out_of_environment_proxy(tmp_path, monkeypatch):
    with recording_server() as (direct_url, direct), recording_server() as (proxy_url, proxy):
        for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(key, proxy_url)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setenv("COMFY_BASE_URL", direct_url)
        Studio(tmp_path, start_workers=False)
        with Comfy(client_info="takelab-test") as client, pytest.raises(ComfyError):
            client.jobs.get("missing")
        assert direct == ["/api/v2/jobs/missing"]
        assert proxy == []
