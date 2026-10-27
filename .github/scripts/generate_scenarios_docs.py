#!/usr/bin/env python3
"""Generate the scenario tables from scenarios.yml.

Writes the tables between the generated-content markers in README.md, and one
file per category in docs/alloy/ that the Grafana Alloy documentation copies
into its shared content.

Run without arguments to update the files. Run with --check to fail when they
are out of date, without writing anything.
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scenarios.yml"
README = ROOT / "README.md"
DOCS_DIR = ROOT / "docs" / "alloy"

REPO_URL = "https://github.com/grafana/alloy-scenarios"
TREE_URL = REPO_URL + "/tree/main/"
REPO_LABEL = "alloy-scenarios"

BEGIN = "<!-- BEGIN GENERATED SCENARIO TABLES: edit scenarios.yml, then run python3 .github/scripts/generate_scenarios_docs.py -->"
END = "<!-- END GENERATED SCENARIO TABLES -->"

TABLE_HEADER = ["| Scenario | Description |", "| -------- | ----------- |"]

DOCS_HEADER = """---
canonical: https://grafana.com/docs/alloy/latest/shared/scenarios/{slug}/
description: Shared content, Alloy scenarios, {title}
headless: true
---

<!--
This file is generated from scenarios.yml in https://github.com/grafana/alloy-scenarios.
Don't edit it directly. Edit scenarios.yml in alloy-scenarios. A weekly workflow
in grafana/alloy copies the change into the Alloy documentation.
-->
"""

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")
CATEGORY_KEYS = ("slug", "title", "intro", "scenarios")
SCENARIO_KEYS = ("name", "path", "description")


def label_key(label):
    """Normalize a reference-link label the way Markdown compares them."""
    return " ".join(label.split()).casefold()


def check_keys(where, item, keys, errors):
    if not isinstance(item, dict):
        errors.append(f"{where}: expected a mapping")
        return False
    for key in keys:
        if key not in item:
            errors.append(f"{where}: missing {key!r}")
    for key in item:
        if key not in keys:
            errors.append(f"{where}: unknown key {key!r}")
    return all(key in item for key in keys)


def check_text(where, value, errors, multiline=False):
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: expected a non-empty string")
        return
    if not multiline and "\n" in value.strip():
        errors.append(f"{where}: must be a single line")
    if "{{" in value or "{%" in value:
        errors.append(f"{where}: contains a Hugo shortcode delimiter")


def check_path(where, path, errors):
    if not isinstance(path, str) or not all(PATH_SEGMENT_RE.match(s) for s in path.split("/")):
        errors.append(f"{where}: path {path!r} must be a relative directory such as 'logs-file' or 'k8s/logs'")
    elif not (ROOT / path).is_dir():
        errors.append(f"{where}: directory {path!r} doesn't exist")


def load(path):
    """Load and validate scenarios.yml. Reports every problem, not just the first."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    errors = []

    if not check_keys("scenarios.yml", data, ("categories",), errors):
        raise SystemExit("\n".join(errors))
    categories = data["categories"]
    if not isinstance(categories, list) or not categories:
        raise SystemExit("scenarios.yml: 'categories' must be a non-empty list")

    slugs = {}
    for i, category in enumerate(categories):
        where = f"categories[{i}]"
        if not check_keys(where, category, CATEGORY_KEYS, errors):
            continue
        where = f"category {category['slug']!r}"

        slug = category["slug"]
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            errors.append(f"{where}: slug must be lowercase words separated by hyphens")
        elif slug in slugs:
            errors.append(f"{where}: duplicate slug, also used by category {slugs[slug]!r}")
        else:
            slugs[slug] = category["title"]
        check_text(f"{where}: title", category["title"], errors)
        check_text(f"{where}: intro", category["intro"], errors, multiline=True)

        scenarios = category["scenarios"]
        if not isinstance(scenarios, list) or not scenarios:
            errors.append(f"{where}: 'scenarios' must be a non-empty list")
            continue

        # Each docs file defines its links by name, so names must be unique per category.
        labels = {label_key(REPO_LABEL): REPO_LABEL}
        for j, scenario in enumerate(scenarios):
            item = f"{where}: scenarios[{j}]"
            if not check_keys(item, scenario, SCENARIO_KEYS, errors):
                continue
            name = scenario["name"]
            check_text(f"{item}: name", name, errors)
            check_text(f"{item}: description", scenario["description"], errors)
            check_path(item, scenario["path"], errors)
            if isinstance(name, str):
                if any(c in name for c in "[]|"):
                    errors.append(f"{item}: name {name!r} can't contain '[', ']', or '|'")
                key = label_key(name)
                if key in labels:
                    errors.append(f"{item}: name {name!r} clashes with {labels[key]!r} in the same category")
                labels[key] = name
            if isinstance(scenario["description"], str) and "|" in scenario["description"]:
                errors.append(f"{item}: description can't contain '|'")

    if errors:
        raise SystemExit("scenarios.yml is invalid:\n  " + "\n  ".join(errors))
    return categories


def render_readme_block(categories):
    lines = [BEGIN, ""]
    for category in categories:
        lines += [f"### {category['title']}", "", category["intro"].strip(), ""]
        lines += TABLE_HEADER
        for s in category["scenarios"]:
            lines.append(f"| [{s['name']}]({s['path']}/) | {s['description'].strip()} |")
        lines.append("")
    lines.append(END)
    return lines


def render_readme(readme, categories):
    lines = readme.split("\n")
    if lines.count(BEGIN) != 1 or lines.count(END) != 1:
        raise SystemExit("README.md must contain the BEGIN and END generated-content markers exactly once")
    start, end = lines.index(BEGIN), lines.index(END)
    if end < start:
        raise SystemExit("README.md has the END generated-content marker before the BEGIN marker")
    return "\n".join(lines[:start] + render_readme_block(categories) + lines[end + 1:])


def render_docs(category):
    rows = [f"| [{s['name']}][] | {s['description'].strip()} |" for s in category["scenarios"]]
    links = [f"[{s['name']}]: {TREE_URL}{s['path']}" for s in category["scenarios"]]
    links.append(f"[{REPO_LABEL}]: {REPO_URL}")
    footer = f"Refer to the [{REPO_LABEL}][] repository for the full list of scenarios."
    header = DOCS_HEADER.format(slug=category["slug"], title=category["title"])
    return "\n".join([header, *TABLE_HEADER, *rows, "", footer, "", *links, ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if any generated file is out of date")
    args = parser.parse_args()

    categories = load(SOURCE)

    want = {README: render_readme(README.read_text(encoding="utf-8"), categories)}
    for category in categories:
        want[DOCS_DIR / f"{category['slug']}.md"] = render_docs(category)
    stale = [p for p in DOCS_DIR.glob("*.md") if p not in want] if DOCS_DIR.is_dir() else []

    outdated = [p for p, text in want.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]

    if args.check:
        problems = [f"{p.relative_to(ROOT)} is out of date" for p in outdated]
        problems += [f"{p.relative_to(ROOT)} has no category in scenarios.yml" for p in stale]
        if problems:
            print("\n".join(problems), file=sys.stderr)
            print("Run 'python3 .github/scripts/generate_scenarios_docs.py' and commit the result.", file=sys.stderr)
            return 1
        print("Scenario tables are up to date.")
        return 0

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for path in outdated:
        path.write_text(want[path], encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    for path in stale:
        path.unlink()
        print(f"removed {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
