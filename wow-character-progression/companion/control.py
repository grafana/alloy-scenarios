"""Loopback-only HTTP interface to the companion. No external Python dependencies."""
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import subprocess
import threading
from urllib.parse import urlsplit

from export_signals import TRACE_SIGNAL, activity_trace_id
from settings import configure_cloud, load_settings, public_cloud, save_private, start_collector
from simulate import simulate

UI = Path(__file__).with_name("ui")
ASSETS = {"/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
          "/app.js": ("app.js", "text/javascript")}


class Companion:
    def __init__(self, folder, client, scan):
        self.folder = folder.resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / ".journey").mkdir(exist_ok=True)
        self.config = load_settings(self.folder, client)
        self.scan = scan
        self.lock = threading.RLock()
        self.wakeup = threading.Event()
        self.seen = {}
        self.error = ""

    def watch(self):
        while True:
            with self.lock:
                self.wakeup.clear()
                if self.config["mode"] == "real":
                    try:
                        self.scan(Path(self.config["client"]), self.folder, self.seen)
                        self.error = ""
                    except OSError as exc:
                        self.error = str(exc)
                interval = self.config["interval"]
            self.wakeup.wait(interval)

    def settings(self, data):
        with self.lock:
            mode = data.get("mode", self.config["mode"])
            client = Path(data.get("client", self.config["client"])).expanduser()
            interval = int(data.get("interval", self.config["interval"]))
            if mode not in ("real", "simulated") or not client.is_absolute() or not 1 <= interval <= 300:
                raise ValueError("Choose a mode, an absolute WoW client path, and a scan interval from 1 to 300 seconds.")
            config = {"mode": mode, "client": str(client), "interval": interval}
            save_private(self.folder / ".companion.json", json.dumps(config))
            self.config = config
            self.wakeup.set()

    def sessions(self):
        state = self.folder / ".delivery" / "delivery.sqlite"
        sent, checkpoints = set(), {}
        if state.is_file():
            try:
                db = sqlite3.connect(state.as_uri() + "?mode=ro", uri=True, timeout=1)
                try:
                    sent.update(db.execute("SELECT session, signal FROM delivery WHERE next_batch=-1"))
                    checkpoints.update(db.execute("SELECT session, stamp/1000000 FROM checkpoint"))
                finally:
                    db.close()
            except sqlite3.OperationalError:
                pass
        sessions = []
        for path in self.folder.glob("*.jsonl"):
            try:
                with path.open(encoding="utf-8") as stream:
                    header = json.loads(next(stream))
                sessions.append({"key": path.stem, **{k: header[k] for k in
                    ("ts", "ended", "duration_seconds", "character", "realm", "region", "rows", "session_id")},
                    "checkpoint_ms": checkpoints.get(path.stem), "trace_id": activity_trace_id(path.stem),
                    "metrics": (path.stem, "checkpoint_metrics") in sent, "traces": (path.stem, TRACE_SIGNAL) in sent})
            except (OSError, KeyError, ValueError, StopIteration):
                continue
        return sorted(sessions, key=lambda s: s["ts"], reverse=True)[:40]

    def status(self):
        with self.lock:
            config = self.config.copy()
            return {"config": config, "client_present": Path(config["client"]).is_dir(),
                    "cloud": public_cloud(), "sessions": self.sessions(), "error": self.error}

    def action(self, route, data):
        if route == "/settings":
            self.settings(data)
        elif route == "/simulate":
            with self.lock:
                if self.config["mode"] != "simulated":
                    raise ValueError("Switch to Simulated mode to generate a recording.")
                simulate(data.get("example"), self.folder)
        elif route == "/cloud":
            with self.lock:
                configure_cloud(data)
                start_collector(self.folder)
        elif route == "/start-collector":
            with self.lock:
                start_collector(self.folder)
        else:
            raise ValueError("Unknown action.")


def serve(app, port):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, kind="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; form-action 'self'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            return self.headers.get("Host") in hosts

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, b"{}")
            path = urlsplit(self.path).path
            if path == "/status":
                return self.reply(200, json.dumps(app.status()).encode())
            if path in ASSETS:
                name, kind = ASSETS[path]
                return self.reply(200, (UI / name).read_bytes(), kind)
            self.reply(404, b"{}")

        def do_POST(self):
            if (not self.allowed() or self.headers.get("Origin") != "http://" + self.headers.get("Host", "")
                    or self.headers.get_content_type() != "application/json"):
                return self.reply(403, b'{"error":"Use the local companion page."}')
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16000:
                    raise ValueError("Invalid request size.")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected a settings object.")
                app.action(self.path, data)
            except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
                return self.reply(400, json.dumps({"error": str(exc)}).encode())
            self.reply(200, b'{"ok":true}')

        def log_message(self, fmt, *args):
            if self.command != "GET":
                logging.info(fmt, *args)

    # Bind first, so a second instance cannot start watching or writing.
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        threading.Thread(target=app.watch, daemon=True).start()
        print(f"Alloy Route companion: http://127.0.0.1:{port}", flush=True)
        server.serve_forever()
