#!/usr/bin/env python3
"""Export completed per-character checkpoints from a WoW Forever installation."""
import argparse
import sys
from pathlib import Path

from journal import note_read
from read_recording import read_file, write_sessions


def scan(root, output, seen):
    errors = []
    paths = set(root.glob("WTF/Account/*/*/*/SavedVariables/AlloyRoute.lua"))
    for path in sorted(paths, key=lambda p: p.stat().st_mtime_ns):
        try:
            stat = path.stat()
            signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if seen.get(path) == signature:
                continue
            sessions, events = read_file(path, allow_empty=True)
            published = write_sessions(output, sessions, events)
            note_read(output, sessions, events, published, "real", path.parents[1].name)
            seen[path] = signature
            if sessions:
                print(f"Exported {len(published)} new saved sessions for {sessions[0]['character']}.", flush=True)
        except (ValueError, OSError, OverflowError) as exc:
            errors.append("Waiting for a complete character save (" + type(exc).__name__ + ").")
            print(f"Waiting for a complete checkpoint: {exc}", file=sys.stderr, flush=True)
    for missing in seen.keys() - paths:
        del seen[missing]
    return " ".join(dict.fromkeys(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, default=Path("/Volumes/T7/Blizzard/World of Warcraft/_forever_"))
    parser.add_argument("--export-dir", type=Path, default=Path(__file__).resolve().parents[1] / "exports")
    parser.add_argument("--port", type=int, default=8096, help="local companion UI port")
    args = parser.parse_args()
    from control import Companion, serve
    serve(Companion(args.export_dir, args.client, scan), args.port)


if __name__ == "__main__":
    main()
