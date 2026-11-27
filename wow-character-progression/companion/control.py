"""Loopback-only HTTP interface to the companion. No external Python dependencies."""
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from journal import history
from portrait import Portraits
import re
from urllib.parse import parse_qs, urlsplit

from export_signals import GROWTH_SIGNAL, TRACE_SIGNAL, activity_trace_id
from settings import configure_cloud, load_settings, public_cloud, save_private, start_collector
from simulate import simulate

UI = Path(__file__).with_name("ui")
ASSETS = {"/field-plate.jpg": ("field-plate.jpg", "image/jpeg"), "/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
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
        self.portraits = Portraits(self.folder)
        self.portrait_lock = threading.Lock()

    def watch(self):
        while True:
            with self.lock:
                self.wakeup.clear()
                if self.config["mode"] == "real":
                    try:
                        self.error = self.scan(Path(self.config["client"]), self.folder, self.seen) or ""
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

    def status(self, selected=None):
        with self.lock:
            sessions, latest, characters = history(self.folder, self.config["mode"], selected)
            state = self.folder / ".delivery" / "delivery.sqlite"
            sent, checks, attempts, offsets, health = set(), {}, {}, {}, None
            if state.is_file():
                with closing(sqlite3.connect(state.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
                    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if "delivery" in tables:
                        sent.update(db.execute("SELECT session,signal FROM delivery WHERE next_batch=-1"))
                    if "checkpoint" in tables:
                        checks.update(db.execute("SELECT session,stamp/1000000 FROM checkpoint"))
                    if "attempt" in tables:
                        for key, signal, at, ack, error in db.execute("SELECT * FROM attempt"):
                            attempts[key, signal] = dict(at=at, ack=ack, error=error)
                    if "tail" in tables:
                        offsets.update(db.execute("SELECT session,bytes FROM tail"))
                    if "health" in tables:
                        health = db.execute("SELECT at,ready FROM health WHERE id=1").fetchone()
            for item in sessions:
                key = item["key"]
                path = self.folder / (key + ".jsonl")
                item["logs_read"] = path.is_file() and offsets.get(key, -1) >= path.stat().st_size
                item.update(checkpoint_ms=checks.get(key), trace_id=activity_trace_id(key))
                for name, signal in (("metrics", "checkpoint_metrics"), ("traces", TRACE_SIGNAL)):
                    item[name] = (key, signal) in sent
                    item[name + "_attempt"] = attempts.get((key, signal), {})
                if item["metrics"] and (key, GROWTH_SIGNAL) not in sent:
                    item["metrics"] = False
                if (key, GROWTH_SIGNAL) in attempts:
                    item["metrics_attempt"] = attempts[key, GROWTH_SIGNAL]
            if not health or time.time() - health[0] > 90:
                collector = "No recent collector check"
            else:
                collector = "Alloy ready" if health[1] else "Alloy offline"
            return {"config": self.config.copy(), "client_present": Path(self.config["client"]).is_dir(),
                    "portrait_configured": all(self.portraits.credentials()), "characters": characters, "cloud": public_cloud(), "sessions": sessions, "latest": latest,
                    "collector": collector, "error": self.error}

    def action(self, route, data):
        if route == "/portrait-settings":
            with self.portrait_lock:
                self.portraits.configure(data.get("client_id"), data.get("secret"))
        elif route == "/portrait":
            key = data.get("session")
            if not isinstance(key, str) or not re.fullmatch("[0-9a-f]{64}", key):
                raise ValueError("Select a recorded character.")
            with self.lock:
                sessions, _, _ = history(self.folder, selected=data.get("character"))
                item = next((s for s in sessions if s["key"] == key and s["origin"] == "real"), None)
                if not item:
                    raise ValueError("Portraits are available for real character saves.")
                with (self.folder / (key + ".jsonl")).open() as stream:
                    header = json.loads(next(stream))
            with self.portrait_lock:
                return self.portraits.lookup(header, item["character_key"], item["full_name"])
        elif route == "/settings":
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
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' https://render.worldofwarcraft.com; frame-ancestors 'none'; form-action 'self'")
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
                return self.reply(200, json.dumps(app.status(parse_qs(urlsplit(self.path).query).get("character",[None])[0])).encode())
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
                result = app.action(self.path, data)
            except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
                return self.reply(400, json.dumps({"error": str(exc)}).encode())
            self.reply(200, json.dumps(result or {"ok":True}).encode())

        def log_message(self, fmt, *args):
            if self.command != "GET":
                logging.info(fmt, *args)

    # Bind first, so a second instance cannot start watching or writing.
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        threading.Thread(target=app.watch, daemon=True).start()
        print(f"Azeroth Chronicle companion: http://127.0.0.1:{port}", flush=True)
        server.serve_forever()
