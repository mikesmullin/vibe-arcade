# CHALLENGE — Scorpion Boss Legs (boss.html)

## Goal
`boss.html` is a standalone scorpion boss arena sharing the flight model of `mars.html` (Three.js 0.160.0, Mars gravity 3.71, same terrain). The mecha-scorpion must look like a real scorpion — 8 legs **upright** with **foot pads clearly touching the ground**, not flat like an octopus and not folded under on its knees.

**Spec constraints (do not change):**
- Body 14×6.4×26, head 8.4×4.8×6.4, hip y=3.8, leg segs 6.5/7.0/4.2, tail 4.2→1.8, mound r26, collision r16, wantDist 62
- All boxes: carapace Box + plates/skirts, legs 3×Box (1.6×SEG×1.6) + Box joints + foot Box 1.4×0.6×2.2, tail 6×Box Y-up over body + Box plates/pistons + Box gun + Cone barb, claws at ±9.2,6.2,11.5
- Flight/HUD/phases identical: `claws 90+90 → tail 110 → head 130 → dying→VICTORY`, armored hits spark+shake 0.3 only (no red flash)

## Current State (after GrokHeavy tetrapod)
Previous bug was Z-oriented tail/legs upside-down (tail below ground, feet up, shots missed) — fixed to Y-up tail / Y-down legs, but legs read as **flat octopus** (spread 11.5 outward, splayed 1.05 rad) then **folded under on knees / crawling** (knees under body, tibias horizontal along sand, feet tucked). You noted: "he kind of looks like he's running around on his knees or crawling on his knees. Somehow they're folded under him."

Latest `boss.html` now implements **GrokHeavy procedural tetrapod** (fully IK-driven, not baked cycles):
- 8 legs in two alternating groups: A = L1,R2,L3,R4 (indices 0,5,2,7), B = R1,L2,R3,L4 (4,1,6,3), phase 0.5, neighbor rule (no adjacent/mirror stepping together)
- Per-leg: `homeOffset` (hip + side*2.2 outward), `plantPosition`, `plantNormal`, `isStepping`, `stepT`, `stepStart/End`
- Stepping: `ideal = body.pos + rot*homeOffset + velocity*0.15`, raycast via `terrainHeight(ideal.x,ideal.z) → ideal.y=gY+0.02`, if `dist>stepDistance (2.8 moving /1.4 idle)` and group+neighbor allow → step arc `lerp(smoothstep) + sin(tπ)*stepHeight (1.6/0.6)` duration `0.24/0.34`, with forward obstacle lift
- IK: analytic 2-bone (L1,L2 6.5/7.0) → `splay=clamp(downAng-thighAdj*0.35,0.35,0.68)`, thigh `0.35+thighAdj*0.55`, shin `0.55+kneeAng*0.45`, foot `-0.55 -kneeAng*0.2`
- Body: `avgY` of planted feet → `bossGroup.y = lerp( (avgY-0.22)*0.35, damp 4)` + bob `sin*0.22`

But **still folded/crawling in rig**: `poseBossRest()` is the frozen view (IK disabled when `inspectFrozen`). Current rest:
```js
legOffsets = [[-7.2,3.8,7.5],[-8.0,3.8,1.0],[-8.0,3.8,-5.5],[-6.8,3.8,-11.0],
              [ 7.2,3.8,7.5],[ 8.0,3.8,1.0],[ 8.0,3.8,-5.5],[ 6.8,3.8,-11.0]]
SEG1=6.5, SEG2=7.0, SEG3=4.2
poseBossRest(): leg.rot (0.04, yawSpread=(row-1.5)*0.22, side*0.48)
                thighG 0.84, shinG 0.88, foot -0.72   // feet Y ~0.87, just above ground but knee still low
// IK now procedural as above (restOut etc. removed; homeOffset + side*2.2)
```
Feet near-touch but visually **knees still under the body, femur/tibia nearly horizontal** (~1 high, not 2-3), so he crawls on knees — the classic spider/scorpion upright is **femur at ~40-55° outward-down with knee clearly above ground (~2-3 high), tibia near-vertical down to a flat tarsus**. Real scorpion hinges are high, not tucked. Increasing thigh to 0.95 raises knee but lifts foot to 1.45, so trade-off remains.

The rig and the walking now use **different code paths** (rest vs. procedural IK). Walking may be slightly better (tetrapod lift) but still inherits low knee because `splay` small and `homeOffset` only 2.2 outward. The folded-under is because `homeOffset` outward is still modest and `thighG 0.84` is shallow — knee stays under belly.

**What “upright scorpion” means (per GrokHeavy + visual target):**
- From front/left/iso: each leg shows a high inverted-V: coxa outward → femur down-out at ~40-55°, **knee joint visibly 1.8-3.0 high** above sand (well above tarsus), **tibia near-vertical down to pad flat** on sand (pad 1.4×0.6 long axis forward, bottom at 0.02). No segment should lie flat along sand, intersect belly, or tuck under. Current rig shows **tibias horizontal along sand** — the giveaway of folded-under.
- From top: 4 legs/side fan along body length (Z 7.5 to -11), feet land ~2.5-3.5 outside belly wall (belly half-width ~7), not 6-8 outside (octopus) nor 0-1 tucked under.
- During walking: GrokHeavy **alternating tetrapod** (Group A: L1,R2,L3,R4; Group B: R1,L2,R3,L4, phase 0.5, duty factor ~0.6) with raycast planting — feet must **appear to push against ground**, not slide. Swing arc `sin(tπ)*liftHeight` should be clearly visible. `strideLen` 14 was too frog-like — tetrapod uses `stepDistance 2.8` + velocity look-ahead 0.15.
- Body: small bob + `avgY` of planted feet, not floating. Hip y=3.8 should stay ~3.6 above avg foot (so body not sinking).

## How To Troubleshoot (rig is already in boss.html)

You are a secondary worker in `/workspace/tmp/gemma-mjs-test` — **do NOT touch `mars.html`**. Main agent uses two browsers on `mars.html?room=MARS-RAID`; use the **third browser on `http://127.0.0.1:8080/boss.html`** (port `:3794` for this workspace, `~/.integrated-browser-mcp/instances/*.json`).

**Inspection rig (frozen, white background):**
```js
window.bossInspect.enter('front'|'back'|'left'|'right'|'top'|'iso'|'tail'|'claw')
// white bg 0xffffff, fog null, hides non-boss meshes/points/dust,
// white ground Plane 120×120 at y0.02, freezes boss at (0,0,0) active/claws,
window.bossInspect.view('left')  // switch angle without re-entering
window.bossInspect.exit()        // restore bg/fog/HUD/boss pos/state
window.bossInspect.angles, _angles, _state()
window.bossDebug.state()
window.bossDebug.pose() // returns {feet:[{i,side,foot:[x,y,z], rot, thigh, shin}], tail, barb, head} — y of foot tells if touching
window.bossDebug.killClaws() / killTail() / killHead() / hurtBoss(part)
```
Angles: front [0,14,52]→[0,7,0], left [-52,14,0], top [0,62,0]→[0,0,0], iso [38,26,38], tail [0,20,-48]→[0,10,-6], claw [0,12,42]→[0,6,10]

**Browser MCP (integrated browser, not Chrome):**
- MCP is `integrated-browser-mcp` → `fetch` to `http://127.0.0.1:3794` (discovered via `~/.integrated-browser-mcp/instances/13befff70a2f.json`). Do **not** use `browser_tab_open` (needs --enable-proposed-api) — use `POST /navigate {"url":...}` if tab closes.
- `curl` via proxy (`http_proxy` env) often fails for POST/screenshot with `Empty reply`; **use Node `fetch`** (as in examples below). `ss` shows only proxy listener, not direct `:3794`.
- `GET /tabs`, `GET /status`, `GET /screenshot?tabId=tab-main` (returns base64 PNG), `POST /eval {"expression": ...}`, `POST /tab/close/tab-main`, `POST /navigate`.

**Example: take all rig shots (Node fetch, not curl)**
```js
async function evalInPage(expr){
  const r='http://127.0.0.1:3794';
  const res=await fetch(r+'/eval',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expression:expr})});
  return (await res.json()).data;
}
async function screenshot(name){
  const r=await fetch('http://127.0.0.1:3794/screenshot?tabId=tab-main');
  const j=await r.json();
  await import('fs').then(fs=>fs.writeFileSync('/tmp/boss-'+name+'.png', Buffer.from(j.data,'base64')));
}
await evalInPage("window.bossInspect.enter('left')");
await evalInPage("window.bossInspect.view('iso')"); // etc: front, left, top, iso, tail, claw
await evalInPage("JSON.stringify(window.bossDebug.pose(),null,2)"); // feet Y: want ~0.2-0.5, not -5 or 2.4
```

**Recent measurements:**
- Original pose (side*1.05, thigh 0.62, shin 0.95): feet Y ≈2.4 — floating, octopus spread X±16.
- Best touching so far (side*0.46, thigh 0.80, shin 0.88): feet Y≈0.4 — touching but knee low, still flat look. Left image `/tmp/final-left.png` etc.
- Current (side*0.48, thigh 0.84, shin 0.88, homeOut 2.2): feet Y≈0.87 — near-touch but still flat, knee ~1.0 high.
- High knee attempt (thigh 0.92, shin 1.12): feet Y≈3.2 — floating again.
- Trade-off: thigh larger → knee higher but foot rises; shin larger → foot rises; need knee high **and** foot ≈0.3.

**Where the bug lives:**
- `buildScorpion()` : leg construction Y-down (correct) — thigh `Box(1.6, SEG1, 1.6)` at `0,-SEG1/2,0`, shin offset `0,-SEG1,0`
- `poseBossRest()` : static pose used when `inspectFrozen` (rig). This is what the screenshots show.
- `updateBoss()` walk IK: now procedural tetrapod (see GrokHeavy block). It computes `homeOffset`, `ideal`, `plantPosition`, `stepT`, then IK `splay/thighAdj/kneeAng`. Previously used `restOut`, `strideLen`, `stepH` sine cycle.
- Walking is disabled when `inspectFrozen` returns early, so rig shows only `poseBossRest`; you must tune both paths.

**What to fix:**
1. Make rest pose upright with high knee: thigh ~0.95-1.08 (femur 55-65° down-out), shin ~0.52-0.72 (tibia near vertical), foot flat horizontal, splay ~0.55-0.62 (not 0.46), homeOffset outward 2.8-3.2 (not 1.9/2.2). Feet must be **outboard of belly but not under it**, pads parallel to ground, clearly separate from belly. Current tibias horizontal is the tell.
2. Make IK produce same: keep `homeOffset` outward 2.8-3.2, `stepDistance` 2.5-3.0, `stepHeight` 1.2-1.6, splay `0.50-0.68`. If you change hip height or SEG lengths you violate spec — adjust angles only.
3. Re-verify with rig shots `front/left/top/iso/tail/claw` on white bg (`screenshot_page` / `fetch /screenshot`): feet pads down on ground, tail arching UP (Y-up stack `prevD=tailSizes[i-1][2]` currently, spec says [1] — tail already correct, barb Y≈11.6), claws forward, head forward, no intersections.

**Checklist before handing back:**
- [ ] `window.bossInspect.enter('left'|'top'|'iso'|'front'|'tail'|'claw')` on white bg shows **high V, not flat**: from `left`/`iso`, each tibia is vertical-ish, knee 1.8-3.0 high, pad flat and touching (Y≈0.35-0.60, bottom at 0.02). From `top`, feet form two parallel rows 2.5-3.5 outside belly. Current `/tmp/final2-left.png` etc. show tibias horizontal — fix that.
- [ ] `window.bossDebug.pose().feet[].foot[1]` ≈0.30-0.60 and **knee world Y** ≈1.8-3.0 — not `0.87` with knee ~1.0 (current crawling)
- [ ] Procedural walk: `window.bossInspect.exit()` → `document.getElementById('startBtn').click()` → wait 3.5s (emerge 2.8s) → `GET /screenshot` while walking shows same upright V, feet pushing, tetrapod alternating, no sliding/skating. Check `window.bossDebug.state()` stays `active/claws` then after kills reaches `dying→dead→VICTORY`. `GET /console?limit=50` empty.
- [ ] Tune **only angles/offsets, not SEG lengths/hip**: try `poseBossRest` thigh 0.96-1.08 + shin 0.68-0.85 + splay 0.55-0.62 + `homeOffset` outward 2.8-3.2 — the sweet spot we missed was knee high + foot 0.4. Test combos via `location.reload()` → `bossInspect.enter('left')` loop; see `/tmp/boss*.png`.
- [ ] No purple/indigo gradient, glassmorphism, etc. (taste checklist) — boss stays brown/orange desert palette, tail Y-up arch barb ≈11.6 high.

**Current files:**
- `/workspace/tmp/gemma-mjs-test/boss.html` (2× size, all boxes correct, latest edit at `poseBossRest` + IK)
- Screenshots in `/tmp/boss*.png` and `/tmp/final2-*.png` and `/tmp/upright*.png` etc. — inspect them to compare.
- Browser at `http://127.0.0.1:8080/boss.html` on `:3794` (`tab-main`, `cdp connected`).

If legs still look gimpy, iterate on `thighG`/`shinG`/`foot`/`leg.rotation.z` in both `poseBossRest` and IK block, reload via `location.reload()`, re-enter rig, and compare left/top/iso. Do not touch `mars.html`.
