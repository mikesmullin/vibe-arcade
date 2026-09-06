#!/usr/bin/env python
"""desk_server.py — the Sound Desk server (:8091): static files + a tiny generate API.

    python3 desk_server.py [--port 8091]        # detached: nohup python3 desk_server.py > scratch/desk.log 2>&1 &

Replaces the bare `python3 -m http.server`: same static serving of this directory
(daw.html, daw.mjs, out/, scratch/), plus:

    GET  /api/models                 -> [{id, label, available, license, steps}]
    POST /api/generate               {model, prompt, seconds, seed, takes, loop, negative}
                                     -> {job}   (async; one job at a time per model kind)
    GET  /api/jobs/<job>             -> {state: queued|running|done|error, log, result}
    GET  /api/generated              -> the desk-gen catalogue (newest first)
    GET  /api/feedback[?src=<dir>]   -> {path: {text, when}}  (human review notes per candidate take)
    POST /api/feedback               {path, text}  (path = <src>/<id>/<file>, relative to this dir)
    POST /api/hide                   {path, hidden}  (disapproved candidates drop out of the desk list; same store)
    POST /api/trim                   {src, id, file, start, end, loop, name?}  -> salvage a window of a take as a NEW
                                     candidate (loop splice + peak-normalize applied), catalogued under scratch/desk_gen
    POST /api/atlas                  {src, id, file, regions, name?}  -> "Export Ranges to Atlas": a NEW candidate made of
                                     ONLY the labeled stage regions (attack, hold, decay, sustain, release — in that order,
                                     samples untouched, no gaps), with the regions remapped to their new positions

Generated takes land in scratch/desk_gen/<stamp>_<model>/ and are catalogued in
scratch/desk_gen/sounds.json (desk source `scratch/desk_gen`) — scratch only, the
approval gate still stands (promote.py). Renders use compare.py's backends and the
manifest's post chain, so a desk take is byte-for-byte what run.py would keep.
"""
import argparse
import json
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare  # noqa: E402
from run import make_loop, peak_normalize, read_wav, write_wav  # noqa: E402

GEN = HERE / "scratch" / "desk_gen"
FEEDBACK = HERE / "scratch" / "feedback.json"   # the human's ears, per candidate path — read with feedback.py
HISTORY = HERE / "scratch" / "prompt_history.jsonl"   # every generate request, in order: how the prompt evolved (feedback.py --history)
JOBS = {}
LOCK = threading.Lock()


def announce_ready():
    """Voice ritual (agreed 2026-09-05): one short 'Sounds ready.' per finished batch, nothing else."""
    try:
        from present import announce
        threading.Thread(target=announce, args=("Sounds ready.", "alan"), daemon=True).start()
    except Exception as e:
        print("announce failed:", e, flush=True)


def load_feedback():
    try:
        return json.loads(FEEDBACK.read_text()) if FEEDBACK.is_file() else {}
    except Exception:
        return {}


def model_available(mid):
    m = compare.MODELS[mid]
    if m["kind"] == "comfy":
        ck = Path("/workspace/tmp/ComfyUI/models/checkpoints") / compare.comfy_sa.MODELS[mid]["ckpt"]
        return ck.is_file()
    return Path(m["python"]).is_file()


def models_list():
    labels = {"sa3_small_sfx": "Stable Audio 3 · small SFX", "sa3_small_sfx_base": "Stable Audio 3 · small SFX base",
              "sa3_medium": "Stable Audio 3 · medium", "sao1": "Stable Audio Open 1.0", "tangoflux": "TangoFlux",
              "moss_v2": "MOSS-SoundEffect v2", "audiox_turbo": "AudioX-Turbo (4-step)"}
    return [{"id": k, "label": labels.get(k, k), "available": model_available(k), "license": v["license"], "steps": v["steps"]}
            for k, v in compare.MODELS.items()]


def catalogue():
    p = GEN / "sounds.json"
    try:
        return json.loads(p.read_text()) if p.is_file() else {}
    except Exception:
        return {}


def save_catalogue(cat):
    GEN.mkdir(parents=True, exist_ok=True)
    (GEN / "sounds.json").write_text(json.dumps(cat, indent=1, sort_keys=True) + "\n")


def rescan():
    """Catalogue any desk_gen dir that has takes but no sounds.json entry (a job that crashed
    after rendering, or a server restart mid-round). Uses job.json when present."""
    cat = catalogue(); added = 0
    for d in sorted(GEN.iterdir()) if GEN.is_dir() else []:
        if not d.is_dir() or d.name in cat:
            continue
        keepers = sorted(f.name for f in d.glob(f"{d.name}_v*.wav"))
        if not keepers:
            continue
        req = json.loads((d / "job.json").read_text()) if (d / "job.json").is_file() else {}
        model = req.get("model") or next((m for m in compare.MODELS if d.name.split("_" + m + "_")[0] != d.name), "?")
        cat[d.name] = {"keepers": keepers, "audition": "audition.wav" if (d / "audition.wav").is_file() else None,
                       "loop": bool(req.get("loop", True)), "model": model, "prompt": req.get("prompt", ""), "seed": req.get("seed"),
                       "seconds": req.get("seconds"), "date": datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds"),
                       "params": None, "layers": None, "recovered": True}
        added += 1
    if added:
        save_catalogue(cat); print(f"rescan: catalogued {added} orphan dir(s)", flush=True)


def trim_take(req):
    """Salvage [start, end] seconds of an existing candidate into a new one. The window is cut
    from the POSTED take (already mono 48 kHz, highpassed); a loop gets the manifest crossfade
    (needs `end + xfade` of material, else the window's own tail folds); one-shots get 8 ms fades."""
    man = yaml.safe_load(open(HERE / "manifest.yaml"))
    sr = int(man.get("sample_rate", 48000)); postc = man.get("post", {})
    peak_db = float(postc.get("peak_db", -1.0)); xfade = float(postc.get("loop_xfade", 0.5))
    src = (req.get("src") or "").strip("/"); sid = req["id"]; fname = req["file"]
    if ".." in src or ".." in sid or "/" in fname:
        raise ValueError("bad path")
    path = HERE / src / sid / fname
    if not path.is_file():
        raise FileNotFoundError(str(path.relative_to(HERE)))
    x, xsr = read_wav(path)
    if xsr != sr:
        raise ValueError(f"rate {xsr} != {sr}")
    start = max(0.0, float(req.get("start", 0))); end = min(len(x) / sr, float(req.get("end", len(x) / sr)))
    if end - start < 0.25:
        raise ValueError("window shorter than 0.25 s")
    loop = bool(req.get("loop", True))
    i0, i1 = int(start * sr), int(end * sr)
    secs = (i1 - i0) / sr
    if loop:
        X = int(xfade * sr)
        seg = x[i0:i1 + X] if i1 + X <= len(x) else np.concatenate([x[i0:i1], x[i0:i0 + X]])
        y = make_loop(seg, sr, secs, min(xfade, secs / 2))
    else:
        y = x[i0:i1].copy(); f = min(len(y) // 2, int(sr * 0.008))
        if f:
            y[:f] *= np.linspace(0, 1, f, dtype=np.float32); y[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
    y = peak_normalize(y.astype(np.float32), peak_db)
    base = (req.get("name") or (sid.rsplit("_", 1)[0] if sid[-6:].isdigit() else sid)) + "_trim"
    stamp = datetime.now().strftime("%H%M%S")
    nid = f"{base}_{stamp}"
    d = GEN / nid; d.mkdir(parents=True, exist_ok=True)
    out = d / f"{nid}_v01.wav"
    write_wav(out, y, sr)
    write_wav(d / "audition.wav", y, sr)
    cat_src = {}
    try:
        cat_src = json.loads((HERE / src / "sounds.json").read_text()).get(sid, {})
    except Exception:
        pass
    job = {"id": nid, "derived_from": f"{src}/{sid}/{fname}", "start": round(start, 3), "end": round(end, 3), "loop": loop,
           "model": cat_src.get("model", "?"), "prompt": cat_src.get("prompt", ""), "origin": req.get("origin", "desk-trim")}
    (d / "job.json").write_text(json.dumps(job, indent=1))
    with LOCK:
        cat = catalogue()
        cat[nid] = {"keepers": [out.name], "audition": "audition.wav", "loop": loop, "model": job["model"], "prompt": job["prompt"],
                    "seed": cat_src.get("seed"), "seconds": round(secs, 3), "date": datetime.now().isoformat(timespec="seconds"),
                    "params": cat_src.get("params"), "layers": cat_src.get("layers"), "derived_from": job["derived_from"],
                    "window": [job["start"], job["end"]]}
        save_catalogue(cat)
    return {"id": nid, "src": "scratch/desk_gen", "keepers": [out.name], "seconds": round(secs, 3), "loop": loop}


def atlas_take(req):
    """Compose a new take from just the labeled stage regions of an existing one, in envelope
    order, samples copied verbatim (no splice, no normalize — what the human tuned stays), and
    carry the regions over at their new offsets. Unused samples are gone; the envelope playback
    keeps working because it only ever reads the regions."""
    man = yaml.safe_load(open(HERE / "manifest.yaml"))
    sr = int(man.get("sample_rate", 48000))
    src = (req.get("src") or "").strip("/"); sid = req["id"]; fname = req["file"]
    if ".." in src or ".." in sid or "/" in fname:
        raise ValueError("bad path")
    path = HERE / src / sid / fname
    if not path.is_file():
        raise FileNotFoundError(str(path.relative_to(HERE)))
    x, xsr = read_wav(path)
    if xsr != sr:
        raise ValueError(f"rate {xsr} != {sr}")
    order = ["attack", "hold", "decay", "sustain", "release"]
    regs = req.get("regions") or {}
    used = [(k, float(regs[k][0]), float(regs[k][1])) for k in order if regs.get(k) and len(regs[k]) == 2 and regs[k][1] > regs[k][0]]
    if not used:
        raise ValueError("no labeled regions")
    parts, new_regions, pos = [], {}, 0.0
    for k, a, b in used:
        i0, i1 = max(0, int(a * sr)), min(len(x), int(b * sr))
        seg = x[i0:i1]
        parts.append(seg)
        new_regions[k] = [round(pos, 6), round(pos + len(seg) / sr, 6)]   # sample-exact offsets (ms rounding would drift the windows)
        pos += len(seg) / sr
    y = np.concatenate(parts).astype(np.float32)
    base = (req.get("name") or (sid.rsplit("_", 1)[0] if sid[-6:].isdigit() else sid))
    if base.endswith("_atlas"):
        base = base[:-6]
    nid = f"{base}_atlas_{datetime.now().strftime('%H%M%S')}"
    d = GEN / nid; d.mkdir(parents=True, exist_ok=True)
    out = d / f"{nid}_v01.wav"
    write_wav(out, y, sr); write_wav(d / "audition.wav", y, sr)
    cat_src = {}
    try:
        cat_src = json.loads((HERE / src / "sounds.json").read_text()).get(sid, {})
    except Exception:
        pass
    job = {"id": nid, "derived_from": f"{src}/{sid}/{fname}", "atlas_of": {k: [a, b] for k, a, b in used}, "regions": new_regions,
           "model": cat_src.get("model", "?"), "prompt": cat_src.get("prompt", ""), "origin": req.get("origin", "desk-atlas")}
    (d / "job.json").write_text(json.dumps(job, indent=1))
    with LOCK:
        cat = catalogue()
        settings = req.get("settings") or {}   # the desk's tuned layers/params/gain ride along so the atlas seeds with them
        cat[nid] = {"keepers": [out.name], "audition": "audition.wav", "loop": True, "model": job["model"], "prompt": job["prompt"],
                    "seed": cat_src.get("seed"), "seconds": round(pos, 3), "date": datetime.now().isoformat(timespec="seconds"),
                    "params": settings.get("params", cat_src.get("params")), "layers": settings.get("layers", cat_src.get("layers")),
                    "paramsOn": settings.get("paramsOn"), "gainDb": settings.get("monitorDb"),
                    "derived_from": job["derived_from"], "regions": new_regions}
        job["settings"] = settings
        (d / "job.json").write_text(json.dumps(job, indent=1))
        save_catalogue(cat)
    return {"id": nid, "src": "scratch/desk_gen", "keepers": [out.name], "seconds": round(pos, 3), "regions": new_regions}


def run_job(job):
    req = job["req"]
    try:
        job["state"] = "running"; job["t0"] = time.time()
        man = yaml.safe_load(open(HERE / "manifest.yaml"))
        sr = int(man.get("sample_rate", 48000)); postc = man.get("post", {})
        hp = int(postc.get("highpass", 80)); fade_ms = float(postc.get("fade_out_ms", 12))
        peak_db = float(postc.get("peak_db", -1.0)); xfade = float(postc.get("loop_xfade", 0.5))
        model = req["model"]; loop = bool(req.get("loop", True)); secs = float(req.get("seconds", 6))
        takes = max(1, min(6, int(req.get("takes", 1)))); seed0 = int(req.get("seed", 1))
        prompt = req["prompt"].strip(); negative = req.get("negative", "") or ""
        stamp = datetime.now().strftime("%H%M%S")
        sid = f"{req.get('name') or 'gen'}_{model}_{stamp}"
        d = GEN / sid; (d / "raw").mkdir(parents=True, exist_ok=True)
        (d / "job.json").write_text(json.dumps({"id": sid, **{k: v for k, v in req.items() if k != "announce"}}, indent=1))   # written FIRST so a crash later is recoverable (rescan)
        keepers = []; rows = []
        for i in range(1, takes + 1):
            seed = seed0 + (i - 1) * 977
            raw = d / "raw" / f"{sid}_v{i:02d}_raw.wav"; final = d / f"{sid}_v{i:02d}.wav"
            job["log"] += f"take {i}/{takes} seed {seed} …\n"
            t1 = time.time()
            info = compare.render_one(model, prompt, negative, secs + (xfade if loop else 0.0), seed, raw,
                                      steps=req.get("steps"), cfg=req.get("cfg"))
            compare.post(raw, final, sr, hp, fade_ms, peak_db, loop, secs, xfade)
            y, _ = read_wav(final)
            rows.append({"take": i, "seed": seed, "file": final.name, "secs_wall": round(time.time() - t1, 1), **compare.meters(y, sr)})
            keepers.append(final.name)
            job["log"] += f"  done {rows[-1]['secs_wall']}s  centroid {rows[-1]['centroid_hz']} Hz\n"
        gap = np.zeros(int(sr * 0.35), dtype=np.float32); parts = []
        for f in keepers:
            y, _ = read_wav(d / f); parts += [y, gap]
        write_wav(d / "audition.wav", np.concatenate(parts), sr)
        card = {"id": sid, "model": model, "prompt": prompt, "negative": negative, "seconds": secs, "loop": loop,
                "steps": req.get("steps"), "cfg": req.get("cfg"),
                "seed": seed0, "takes": rows, "date": datetime.now().isoformat(timespec="seconds"),
                "license": compare.MODELS[model]["license"], "note": "desk generate — scratch, unapproved"}
        (d / "gen.yaml").write_text(yaml.safe_dump(card, sort_keys=False))
        # runtime-automation seed (params/layers) from the manifest asset: explicit `asset`, else the name, else a prefix match (pour_r3_* -> sfx_soda_pour_loop)
        want = req.get("asset") or req.get("name") or ""
        asset = next((x for x in man["assets"] if x["id"] == want), None) \
            or next((x for x in man["assets"] if want.split("_")[0] and want.split("_")[0] in x["id"]), None) or {}
        with LOCK:
            cat = catalogue()
            cat[sid] = {"keepers": keepers, "audition": "audition.wav", "loop": loop, "model": model, "prompt": prompt,
                        "seed": seed0, "seconds": secs, "date": card["date"], "params": asset.get("params"), "layers": asset.get("layers")}
            save_catalogue(cat)
        job["result"] = {"id": sid, "src": "scratch/desk_gen", "keepers": keepers, "takes": rows}
        job["state"] = "done"
        if req.get("announce", True):
            announce_ready()
    except Exception as e:
        job["state"] = "error"; job["error"] = str(e)[-1500:]; job["log"] += traceback.format_exc()[-1500:]
    job["t1"] = time.time()


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE), **k)

    def log_message(self, fmt, *args):   # quieter log: API + errors only
        if "/api/" in (args[0] if args else "") or (args and str(args[1]).startswith(("4", "5"))):
            super().log_message(fmt, *args)

    def send_json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data)

    def end_headers(self):   # the desk is a live dev tool: never let the browser cache ANYTHING it serves
        # (a heuristically cached daw.mjs once ran an old engine under a freshly edited page — 2026-09-06)
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/models":
            return self.send_json(models_list())
        if self.path.startswith("/api/jobs/"):
            j = JOBS.get(self.path.rsplit("/", 1)[-1])
            return self.send_json({k: v for k, v in j.items() if k != "thread"} if j else {"error": "no such job"}, 200 if j else 404)
        if self.path.startswith("/api/feedback"):
            fb = load_feedback()
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            src = urllib.parse.unquote(dict(p.split("=", 1) for p in q.split("&") if "=" in p).get("src") or "") or None
            if src:
                fb = {k: v for k, v in fb.items() if k.startswith(src.rstrip("/") + "/")}
            return self.send_json(fb)
        if self.path == "/api/generated":
            cat = catalogue()
            items = sorted(({"id": k, **v} for k, v in cat.items()), key=lambda x: x.get("date", ""), reverse=True)
            return self.send_json(items)
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self.send_json({"error": "bad json"}, 400)
        if self.path in ("/api/feedback", "/api/hide"):
            path = (req.get("path") or "").strip().lstrip("/")
            if not path or ".." in path:
                return self.send_json({"error": "bad path"}, 400)
            with LOCK:
                fb = load_feedback()
                e = fb.get(path) or {}
                if self.path == "/api/feedback":
                    text = (req.get("text") or "").strip()
                    if text:
                        e.update({"text": text, "when": datetime.now().isoformat(timespec="seconds")})
                    else:
                        e.pop("text", None); e.pop("when", None)
                else:
                    if req.get("hidden"):
                        e["hidden"] = True
                    else:
                        e.pop("hidden", None)
                if e:
                    fb[path] = e
                else:
                    fb.pop(path, None)
                FEEDBACK.parent.mkdir(parents=True, exist_ok=True)
                FEEDBACK.write_text(json.dumps(fb, indent=1, sort_keys=True) + "\n")
            return self.send_json({"ok": True, "count": len(fb)})
        if self.path in ("/api/trim", "/api/atlas"):
            try:
                return self.send_json(trim_take(req) if self.path == "/api/trim" else atlas_take(req))
            except Exception as e:
                return self.send_json({"error": str(e)}, 400)
        if self.path != "/api/generate":
            return self.send_json({"error": "unknown endpoint"}, 404)
        if req.get("model") not in compare.MODELS:
            return self.send_json({"error": "unknown model"}, 400)
        if not (req.get("prompt") or "").strip():
            return self.send_json({"error": "empty prompt"}, 400)
        if not model_available(req["model"]):
            return self.send_json({"error": "model not installed"}, 400)
        jid = uuid.uuid4().hex[:8]
        with LOCK:
            HISTORY.parent.mkdir(parents=True, exist_ok=True)
            with open(HISTORY, "a") as f:
                f.write(json.dumps({"when": datetime.now().isoformat(timespec="seconds"), "origin": req.get("origin", "api"), "job": jid,
                                    "model": req["model"], "name": req.get("name"), "seconds": req.get("seconds"), "seed": req.get("seed"),
                                    "takes": req.get("takes"), "loop": req.get("loop"), "prompt": req["prompt"].strip()}) + "\n")
        job = {"id": jid, "state": "queued", "req": req, "log": "", "created": time.time()}
        JOBS[jid] = job
        t = threading.Thread(target=run_job, args=(job,), daemon=True); job["thread"] = t; t.start()
        return self.send_json({"job": jid})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8091)
    a = ap.parse_args()
    GEN.mkdir(parents=True, exist_ok=True)
    rescan()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"Sound Desk server on http://127.0.0.1:{a.port}/daw.html  (root {HERE})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
