#!/usr/bin/env python3
"""Assemble the Home Assistant custom component into dist/soliscloud/.

The component imports the API client as `.soliscloud_api`, so the client package is
copied in beside it. Once this repo has a git remote, this step can be replaced by a
single manifest entry:

    "requirements": ["ha-solis @ git+https://<host>/<user>/ha-solis@main"]
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "soliscloud"
CLIENT = ROOT / "src" / "soliscloud_api"
DIST = ROOT / "dist" / "soliscloud"


def main() -> int:
    if not COMPONENT.is_dir() or not CLIENT.is_dir():
        print("error: expected custom_components/soliscloud and src/soliscloud_api", file=sys.stderr)
        return 1

    if DIST.exists():
        shutil.rmtree(DIST)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(COMPONENT, DIST, ignore=ignore)
    shutil.copytree(CLIENT, DIST / "soliscloud_api", ignore=ignore)

    # Home Assistant reads translations/<lang>.json for custom integrations;
    # strings.json is build input for core only. Generated rather than duplicated by
    # hand, so the two can never drift apart.
    strings = DIST / "strings.json"
    if strings.is_file():
        translations = DIST / "translations"
        translations.mkdir(exist_ok=True)
        shutil.copyfile(strings, translations / "en.json")

    files = sorted(p.relative_to(DIST).as_posix() for p in DIST.rglob("*") if p.is_file())
    print(f"built {DIST.relative_to(ROOT)} ({len(files)} files)")
    for f in files:
        print(f"  {f}")
    print(f"\nCopy it to your HA config:\n  cp -r {DIST} <config>/custom_components/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
