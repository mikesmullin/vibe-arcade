#!/usr/bin/env python
"""Regen assets.json from manifest.yaml (code-side). Run after every accept."""
import json
from pathlib import Path
import yaml
HERE = Path(__file__).resolve().parent
m = yaml.safe_load(open(HERE / "manifest.yaml"))
out = {}
for _id, e in m.items():
    for k, p in e["files"].items():
        out[k] = p
(HERE / "assets.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print(f"wrote assets.json with {len(out)} keys")
