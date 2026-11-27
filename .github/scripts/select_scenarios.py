#!/usr/bin/env python3
"""Select smoke-test scenarios from a NUL-delimited Git changed-file list."""

import sys
from pathlib import Path

# Changes to shared inputs must exercise the catalog, subject to the workflow cap.
SHARED_INPUTS = {
    "image-versions.env",
    "run-example.sh",
    "scenarios.yml",
    ".github/scenario-list.txt",
    ".github/scripts/generate_scenarios_docs.py",
    ".github/scripts/select_scenarios.py",
    ".github/workflows/validate-scenarios.yml",
}


def select_scenarios(scenarios, changed):
    if SHARED_INPUTS.intersection(changed):
        return sorted(set(scenarios))
    return sorted({scenario for scenario in scenarios
                   if any(path == scenario or path.startswith(scenario + "/")
                          for path in changed)})


def main():
    scenarios = Path(".github/scenario-list.txt").read_text().splitlines()
    changed = Path(sys.argv[1]).read_bytes().decode("utf-8", errors="surrogateescape").split("\0")
    for scenario in select_scenarios(scenarios, changed):
        print(scenario)


if __name__ == "__main__":
    main()
