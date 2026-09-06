#!/usr/bin/env python
"""Regen assets.json (+ sfx.json) from manifest.yaml (code-side). Run after every accept.

assets.json: game_key -> path (art + audio alike; the ASSETS overlay).
sfx.json:    game_key -> {wav, mp3, loop, layers, gainDb, params} for every entry carrying an
             `automation:` card — the bank assets/daw.mjs (SfxEngine) loads so
             the game plays raw keepers with the card's two-layer ADSR live.
"""
import json
from pathlib import Path
import yaml
HERE = Path(__file__).resolve().parent
m = yaml.safe_load(open(HERE / "manifest.yaml"))
out, sfx = {}, {}
for _id, e in m.items():
    for k, p in e["files"].items():
        out[k] = p
    if e.get("automation"):
        card = yaml.safe_load(open(HERE / e["automation"]))
        by_path = {p: k for k, p in e["files"].items()}
        wav = next(p for p in e["files"].values() if p.endswith("/" + card["keeper"]))
        mp3 = next((p for p in e["files"].values() if card.get("keeper_mp3") and p.endswith("/" + card["keeper_mp3"])), None)
        sfx[by_path[wav]] = {
            "wav": wav, "mp3": mp3, "loop": bool(e.get("loop", False)),
            "layers": card["layers"], "take": card.get("take"),
            "gainDb": card.get("monitorDb", 0),   # the desk's monitor level = the sound's playback gain
            "params": card.get("params"),          # runtime parameters (voice.setParam(name, 0..1)) or null
            "regions": card.get("regions"),        # sampler windows {head, body, tail} (seconds) or null
            "automation": e["automation"],   # provenance only; the game reads this json
        }
(HERE / "assets.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
(HERE / "sfx.json").write_text(json.dumps(sfx, indent=1, sort_keys=True) + "\n")
print(f"wrote assets.json with {len(out)} keys, sfx.json with {len(sfx)} sounds")
