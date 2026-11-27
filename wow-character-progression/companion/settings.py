"""Local companion configuration. Cloud write tokens never leave this module via the UI."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "cloud"
ENV = CLOUD / ".env"
FIELDS = {"loki_url": "GRAFANA_CLOUD_LOKI_URL", "loki_user": "GRAFANA_CLOUD_LOKI_USER",
          "otlp_url": "ALLOYROUTE_OTLP_ENDPOINT", "otlp_user": "ALLOYROUTE_OTLP_USER",
          "stack_url": "ALLOYROUTE_STACK_URL"}
TOKENS = {"loki_token": "ALLOYROUTE_LOKI_TOKEN", "otlp_token": "ALLOYROUTE_OTLP_TOKEN"}


def save_private(path, body):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        handle.write(body)
    os.replace(handle.name, path)


def load_settings(folder, client):
    path = folder / ".companion.json"
    config = {"mode": "real", "client": str(client), "interval": 5}
    if path.exists():
        config.update(json.loads(path.read_text()))
    return config


def read_env():
    if not ENV.exists():
        return {}
    return dict(line.split("=", 1) for line in ENV.read_text().splitlines() if "=" in line and not line.startswith("#"))


def public_cloud():
    env = read_env()
    return {**{k: env.get(v, "") for k, v in FIELDS.items()},
            **{k + "_set": bool(env.get(v)) for k, v in TOKENS.items()}}


def https_url(value):
    u = urlsplit(value)
    if (u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment
            or not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/[A-Za-z0-9/_.-]*)?", value)):
        raise ValueError("Enter an HTTPS URL without credentials, query parameters or fragments.")
    return value.rstrip("/")


def configure_cloud(data):
    env = read_env()
    updates = {}
    for key, var in FIELDS.items():
        value = data.get(key, "").strip()
        if key.endswith("_url"):
            value = https_url(value)
        elif not value.isdecimal():
            raise ValueError("Enter the numeric Cloud instance IDs.")
        updates[var] = value
    for key, var in TOKENS.items():
        group = key.split("_")[0]
        token = data.get(key, "").strip()
        if not token and any(updates[FIELDS[group + suffix]] != env.get(FIELDS[group + suffix])
                             for suffix in ("_url", "_user")):
            raise ValueError("Enter a new token when changing its destination or instance ID.")
        token = token or env.get(var, "")
        if not re.fullmatch(r"[A-Za-z0-9._=+/-]+", token):
            raise ValueError("Enter a Cloud write token for each destination.")
        updates[var] = token
    # Keep unrelated Compose settings and comments intact.
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [line for line in lines if line.partition("=")[0] not in updates]
    lines.extend(f"{key}={value}" for key, value in updates.items())
    save_private(ENV, "\n".join(lines) + "\n")


def start_collector(folder):
    if not ENV.exists():
        raise ValueError("Save Cloud settings before starting the collector.")
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Install and start Docker to run the collector.")
    cmd = [docker, "compose", "-p", "wow-route-cloud", "--env-file", str(ENV),
           "-f", str(CLOUD / "docker-compose.yml"), "up", "-d", "--build"]
    proc = subprocess.run(cmd, capture_output=True, timeout=180, env={**os.environ, "ALLOYROUTE_EXPORT_DIR": str(folder)})
    if proc.returncode:
        raise ValueError("Docker could not start the collector. Check that Docker is running and the ports are free.")
