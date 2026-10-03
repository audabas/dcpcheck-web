"""Small HTTP server: a JSON API plus the static single-page UI.

Only the Python standard library is used, so the image stays small and
there is nothing to keep up to date besides DCP-o-matic itself.
"""

import json
import mimetypes
import os
import re
import shlex
import shutil
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .manager import Manager

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
ROUTE = re.compile(r"^/api/dcp/([0-9a-f]{12})(?:/(verify|cancel|report|log))?$")


@dataclass
class Config:
    dcp_root: str
    dcp_root_label: str
    data_dir: str
    verifier: str
    verify_args: list
    html_report: bool
    max_parallel: int
    scan_depth: int
    scan_interval: int
    copy_quiet: int
    copy_poll: float
    host: str
    port: int
    verifier_version: str

    @classmethod
    def from_env(cls):
        e = os.environ.get
        root = e("DCP_ROOT", "/dcp")
        version = e("DCPOMATIC_VERSION", "")
        version_file = e("DCPOMATIC_VERSION_FILE", "/etc/dcpomatic-version")
        if not version and os.path.isfile(version_file):
            with open(version_file, encoding="utf-8") as f:
                version = f.read().strip()
        return cls(
            dcp_root=root,
            dcp_root_label=e("DCP_ROOT_LABEL", root),
            data_dir=e("DATA_DIR", "/data"),
            verifier=e("VERIFIER", "dcpomatic2_verify_cli"),
            verify_args=shlex.split(e("VERIFY_ARGS", "")),
            html_report=e("HTML_REPORT", "1").lower() not in ("0", "false", "no", "off"),
            max_parallel=int(e("MAX_PARALLEL", "1")),
            scan_depth=int(e("SCAN_DEPTH", "3")),
            scan_interval=int(e("SCAN_INTERVAL", "300")),
            copy_quiet=int(e("COPY_QUIET", "20")),
            copy_poll=float(e("COPY_POLL", "3")),
            host=e("HOST", "0.0.0.0"),
            port=int(e("PORT", "8080")),
            verifier_version=version,
        )


class Handler(BaseHTTPRequestHandler):
    manager: Manager = None
    server_version = "dcpcheck"

    def log_message(self, fmt, *args):
        if os.environ.get("ACCESS_LOG"):
            super().log_message(fmt, *args)

    # ---- helpers ---------------------------------------------------------

    def send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype=None, extra_headers=()):
        try:
            f = open(path, "rb")
        except OSError:
            return self.send_error(HTTPStatus.NOT_FOUND)
        with f:
            size = os.fstat(f.fileno()).st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype or mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-cache")
            for k, v in extra_headers:
                self.send_header(k, v)
            self.end_headers()
            shutil.copyfileobj(f, self.wfile)

    # ---- routes ----------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        m = self.manager
        if path == "/api/state":
            return self.send_json(m.state())
        r = ROUTE.match(path)
        if r:
            dcp_id, action = r.groups()
            if action is None:
                d = m.detail(dcp_id)
                return self.send_json(d) if d else self.send_error(HTTPStatus.NOT_FOUND)
            if action == "report":
                p = m.report_path(dcp_id)
                # The report is the verifier's own HTML; keep it from running scripts.
                return self.send_file(p, "text/html; charset=utf-8", [("Content-Security-Policy", "sandbox")]) if p else self.send_error(HTTPStatus.NOT_FOUND)
            if action == "log":
                p = m.log_path(dcp_id)
                return self.send_file(p, "text/plain; charset=utf-8") if p else self.send_error(HTTPStatus.NOT_FOUND)
            return self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
        if path in ("/", "/index.html"):
            return self.send_file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")
        if path.startswith("/static/"):
            name = os.path.normpath(path[len("/static/"):])
            if name.startswith("..") or os.path.isabs(name):
                return self.send_error(HTTPStatus.NOT_FOUND)
            return self.send_file(os.path.join(STATIC, name))
        if path == "/healthz":
            return self.send_json({"ok": True})
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        # A custom header can't be sent cross-site without a CORS preflight,
        # which we never answer: other web pages can't start verifications.
        if self.headers.get("X-Dcpcheck") != "1":
            return self.send_error(HTTPStatus.FORBIDDEN)
        path = self.path.split("?", 1)[0]
        m = self.manager
        if path == "/api/rescan":
            threading.Thread(target=m.rescan, daemon=True).start()
            return self.send_json({"ok": True})
        r = ROUTE.match(path)
        if r and r.group(2) in ("verify", "cancel"):
            dcp_id, action = r.groups()
            if action == "verify" and m.is_copying(dcp_id):
                return self.send_json({"ok": False, "error": "The DCP is still being copied."}, HTTPStatus.CONFLICT)
            ok = m.verify(dcp_id) if action == "verify" else m.cancel(dcp_id)
            return self.send_json({"ok": ok}, HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND)
        self.send_error(HTTPStatus.NOT_FOUND)


def main():
    cfg = Config.from_env()
    if not shutil.which(cfg.verifier):
        print(f"warning: verifier '{cfg.verifier}' not found on PATH", flush=True)
    if not os.path.isdir(cfg.dcp_root):
        print(f"warning: DCP directory '{cfg.dcp_root}' does not exist; mount your DCPs there", flush=True)
    manager = Manager(cfg)
    manager.start()
    Handler.manager = manager
    httpd = ThreadingHTTPServer((cfg.host, cfg.port), Handler)
    httpd.daemon_threads = True
    print(f"dcpcheck listening on http://{cfg.host}:{cfg.port} (DCPs in {cfg.dcp_root}, data in {cfg.data_dir})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
