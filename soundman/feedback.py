#!/usr/bin/env python
"""feedback.py — read the human's per-candidate notes typed into the Sound Desk.

    python3 feedback.py                      # everything, newest first
    python3 feedback.py --src scratch/models_compare/sfx_soda_pour_loop
    python3 feedback.py --json               # raw

The desk POSTs to /api/feedback (desk_server.py) -> scratch/feedback.json, keyed by
candidate path (<src>/<id>/<file>). Loop: generate batch -> "Sounds ready." ->
human types notes per take -> human says "read the feedback" -> this -> next batch.
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FB = HERE / "scratch" / "feedback.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="only candidates under this dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--history", action="store_true", help="print the prompt history (every generate, in order)")
    a = ap.parse_args()
    if a.history:
        hp = HERE / "scratch" / "prompt_history.jsonl"
        for line in (hp.read_text().splitlines() if hp.is_file() else []):
            h = json.loads(line)
            print(f"{h['when']}  {h['origin']:<22} {h['model']:<18} {h.get('name') or ''}  seed {h.get('seed')} ×{h.get('takes')} {h.get('seconds')}s\n    {h['prompt']}")
        return
    fb = json.loads(FB.read_text()) if FB.is_file() else {}
    if a.src:
        fb = {k: v for k, v in fb.items() if k.startswith(a.src.rstrip("/") + "/")}
    if a.json:
        print(json.dumps(fb, indent=1, sort_keys=True)); return
    if not fb:
        print("(no feedback yet)"); return
    for k, v in sorted(fb.items(), key=lambda kv: kv[1].get("when", ""), reverse=True):
        print(f"{v.get('when','')}  {'[hidden] ' if v.get('hidden') else ''}{k}\n    {v.get('text','')}")


if __name__ == "__main__":
    main()
