#!/usr/bin/env python
"""batch.py — run a round of candidate generations through the desk server, one job at
a time (the GPU is shared), and say "Sounds ready." once at the end.

    python3 batch.py rounds/pour_r2.yaml        # jobs: [{name, model, prompt, seed, takes, seconds, loop}]
    python3 batch.py rounds/pour_r2.yaml --dry  # print the plan only

Each job becomes scratch/desk_gen/<name>_<model>_<hhmmss>/ (catalogued for the desk
source `scratch/desk_gen`). Rounds live in rounds/*.yaml so the prompt history is
kept next to the feedback (scratch/feedback.json).
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
API = "http://127.0.0.1:8091"


def call(path, data=None):
    req = urllib.request.Request(API + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    plan = yaml.safe_load(open(a.plan))
    defaults = plan.get("defaults", {})
    jobs = [dict(defaults, **j) for j in plan["jobs"]]
    for j in jobs:
        print(f"- {j['name']:<28} {j['model']:<18} seed {j.get('seed', 1)} ×{j.get('takes', 1)}  {j['prompt'][:70]}…")
    if a.dry:
        return
    results = []
    t0 = time.time()
    for j in jobs:
        j["announce"] = False; j["origin"] = "batch:" + Path(a.plan).name
        jid = call("/api/generate", j)["job"]
        while True:
            s = call(f"/api/jobs/{jid}")
            if s["state"] in ("done", "error"):
                break
            time.sleep(2)
        if s["state"] == "error":
            print(f"  FAILED {j['name']} {j['model']}: {s.get('error', '')[-300:]}")
        else:
            r = s["result"]; results.append(r)
            print(f"  ok {r['id']}  {len(r['keepers'])} take(s)  {round(s['t1'] - s['t0'], 1)}s")
    print(f"round done: {len(results)}/{len(jobs)} jobs, {round(time.time() - t0)}s")
    try:
        sys.path.insert(0, str(HERE))
        from present import announce
        announce("Sounds ready.", "alan")
    except Exception as e:
        print("announce failed:", e)


if __name__ == "__main__":
    main()
