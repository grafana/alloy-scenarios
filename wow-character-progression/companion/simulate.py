"""Drive the shipped addon with mock WoW APIs and export its completed save."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from read_recording import read_file, session_key, write_sessions
from simulation.journey import CHAPTERS, SAMPLES

HERE = Path(__file__).resolve().parent


def lua_value(value):
    if isinstance(value, str):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return str(value).lower()


def simulate(example, output):
    if example not in ("gear", "journey"):
        raise ValueError("Choose a supported simulation.")
    lua = next((p for cmd in ("luajit", "lua5.1", "lua") if (p := shutil.which(cmd))), None)
    if not lua:
        raise ValueError("Install Lua 5.1 or LuaJIT to run a simulation.")
    duration = 210 if example == "gear" else 10800
    start = int(time.time()) - duration - 2
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        scenario = HERE / "simulation" / "gear.lua"
        if example == "journey":
            scenario = tmp / "journey.lua"
            with scenario.open("w", encoding="utf-8") as script:
                script.write((HERE / "simulation" / "journey_driver.lua").read_text())
                for row in SAMPLES:
                    fields = ", ".join(f"{k}={lua_value(v)}" for k,v in row.items())
                    script.write(f"sample({{{fields}}})\n")
                script.write("H.logout()\n")
        save = tmp / "AlloyRoute.lua"
        proc = subprocess.run([lua, str(HERE / "simulation" / "harness.lua"),
                               str(HERE.parent / "app/addon/AlloyRoute/AlloyRoute.lua"), str(scenario), str(save)],
                              env={**os.environ, "ALLOYROUTE_TEST_EPOCH": str(start)}, capture_output=True, timeout=45)
        if proc.returncode:
            raise ValueError("The simulated addon stopped: " + proc.stderr.decode(errors="replace")[:240])
        sessions, events = read_file(save)
        write_sessions(output, sessions, events)
    if example == "journey":
        # Optional local atlas projection. The companion is its only source of runs.
        target = output / ".journey"
        target.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=target, delete=False) as handle:
            json.dump({"start": start, "chapters": CHAPTERS, "samples": SAMPLES}, handle)
        os.replace(handle.name, target / "replay.json")
    return session_key(sessions[0])
