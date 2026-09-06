> User: explain in DAW sound design like synths what the 4 parts of an envelope are (ie. attack, sustain, release, etc.)

An **ADSR envelope** is the most common way a synth (or sampler) shapes a sound over time. It is a control signal that usually drives amplitude (volume), but the same four stages are also used on filter cutoff, pitch, wavetable position, etc.

The four stages:

**Attack** — time from note-on to peak level.

Fast attack = instant “hit” (plucks, drums, most basses). Slow attack = fade-in (pads, strings, swells).

**Decay** — time from that peak down to the sustain level.

This is the “snap” or “punch” after the initial hit. Short decay + low sustain = percussive. Longer decay keeps more of the initial transient.

**Sustain** — *level* (not time) held for as long as the key/note is held.

This is the only stage that is a height, not a duration. Full sustain = organ-like. Zero sustain = the sound dies after the decay even if you keep holding the key.

**Release** — time from note-off down to silence.

Short release = tight cutoff. Long release = tails, reverb-like hang, or overlapping notes.

Typical mental picture:

- Piano / pluck: very fast A, short D, low or zero S, short-to-medium R
- Pad: slow A, medium D, high S, long R
- Staccato lead: fast A, short D, medium S, short R

Most DAW synths (Ableton Operator/Wavetable, Serum, Massive, etc.) give you four knobs labeled exactly A-D-S-R. Some also add a Hold stage between Attack and Decay, but classic ADSR is the four parts you asked about.

![ADSR — Attack, Decay, Sustain, Release](https://dt7v1i9vyp3mf.cloudfront.net/styles/news_large/s3/imagelibrary/f/fig2-1299-fN9hWWTilFqr_34uSAa100V.p.M35Nav.gif)[soundonsound.com](https://www.soundonsound.com/glossary/adsr-attack-decay-sustain-release)![ADSR envelope synth tutorial part A](https://i.ytimg.com/vi/A6pp6OMU5r8/maxresdefault.jpg)[youtube.com](https://www.youtube.com/watch?v=A6pp6OMU5r8)

The first diagram is the classic analog-style plot; the second shows how the four knobs map onto the shape. Play with them on a simple saw or sine patch and the relationship becomes obvious in a few seconds.

---

> User: describe (in comprehensive summary bullets) what all features are provided by FMod for the runtime and sound designer (ie. parameters/knobs that determine how sfx playback happens at runtime)

FMOD splits into **FMOD Studio** (what the sound designer authors) and the **FMOD Engine / Studio API** (what the game ticks every frame). Almost every designer knob below is either baked into a bank or exposed so game code can change it at runtime. This is current FMOD Studio / Engine 2.0x behavior.

## Mental model

- An **event** is the unit the game starts/stops. One event can spawn many **event instances**.
- Instances contain **tracks**, **instruments**, **parameters**, and **logic**.
- Instruments dump audio (or commands) onto tracks. Tracks route into the event master, then the **mixer**.
- Game code does *not* pick WAV files. It starts events, sets parameters / 3D pose / volume, and occasionally supplies programmer sounds.

---

## Event macros (per-event playback policy)

These live on the event master deck. They are the first “how does this SFX behave when the game fires it?” knobs.

- **Persistent** — instance keeps running even when silent. Needed for events that only make sound after a parameter crosses a threshold (heartbeat at low health).
- **Pitch** — sample-rate shift of everything in the event (also scales the timeline clock).
- **Doppler** on/off + scale — extra pitch from emitter vs listener velocity (game must pass velocity in `set3DAttributes`).
- **Min / Max Distance** — event-level attenuation range used by Spatializer (unless the effect overrides it) and by **Distance (Normalized)**.
- **Max Instances** — hard cap (1–64 or ∞) on simultaneous instances of *this* event.
- **Stealing** when the cap is hit:
  Oldest / Furthest / Quietest — stop a live instance
  Virtualize — keep the quiet ones “alive” but silent; they become real again when they win
  None — new start is rejected
- **Cooldown** — minimum time between starts of this event (anti-spam). Overridable from code.
- **Priority** — voice-stealing rank vs the engine voice limit (Highest is never stolen). Loudness is the tie-break.

---

## Instruments (what actually emits SFX)

Triggered when a parameter/timeline playback position overlaps their region *and* trigger conditions pass.

**Shared trigger knobs**

- Position / length on a parameter sheet = the parameter range that arms the instrument
- **Probability / Chance** (0–100%, automatable)
- **Conditions** — parameter ranges and/or parent event state, AND or OR, each invertible
- **Delay** (ms/s, can be a range) or **Quantize** to beats/bars (needs a tempo marker)
- **Polyphony** + steal Oldest / None (per instrument, inside one instance)
- **Fade in/out curves** on parameter sheets
- Volume / Pitch — automatable and modulatable

**Types**

- **Single** — one asset. Async vs sync (tied to timeline position), start offset, loop + play count, Cut-on-untrigger.
- **Multi** — playlist. Selection: Shuffle, Randomize, Sequential (play / global / instance scope). Per-item play %. Loop playlist + play count.
- **Scatterer** — ambient / debris machine. Spawn interval min–max, spawn rate, spawn total, vol/pitch random per spawn, 3D scatter distance min–max, own polyphony + steal. Good for rain, insects, wreckage.
- **Event instrument** — nested event. Has its own volume/pitch/offset/cut plus **exposed parameter knobs** into the child.
- **Programmer instrument** — empty slot. Runtime gets a callback and must attach a Core sound / file / memory buffer. Used for dialogue, user content, streamed VO.
- **Command instrument** — no audio. Start / stop / stop-immediate an event or snapshot; set or increment a parameter (local or global).
- **Snapshot instrument** — starts a mixer snapshot; **Intensity** scales how hard that snapshot hits; fade curves on the region.
- **Silence** — holds a duration so playlists / logic can wait.

---

## Parameters (the runtime knobs)

Setting a parameter is the primary way game code changes how an already-playing SFX behaves.

**User parameters**

- Continuous (float), Discrete (int steps), or Labeled (enum names the designer authored)
- **Local** — unique value per event instance
- **Global** — one value for the whole project (mixer + every event that references it)
- Initial value, min/max, hold, read-only flag
- **Velocity** / **Seek speed** (or a Seek modulator) — how fast the value is allowed to catch the target
- Shared across events; modulators and automation on the *preset* apply everywhere it is used

**Built-in parameters** (auto from 3D attributes; game cannot `setParameter` them)

- **Distance** — world units to nearest listener
- **Distance (Normalized)** — 0 at event min distance, 1 at max distance
- **Direction** — ±180°, listener-facing vs source (left/right)
- **Elevation** — ±90°, above/below
- **Event Cone Angle** — 0–180°, how far off the *emitter’s* forward the listener is (weapon/vehicle cones)
- **Event Orientation** — emitter forward vs listener forward
- **Listener Orientation**
- **Speed (Relative)** and **Speed (Absolute)**

**Timeline parameter**

- Auto-advances while playing; rate follows event pitch
- Unique per event; cannot be modulated
- Hosts **logic markers**: loop region, transition, destination, magnet, sustain point, tempo
- **keyOff()** from code releases sustain points (music stingers, held whooshes)

Parameters trigger instruments on their sheets and drive **automation curves** on almost any property (volume, pitch, filter cutoff, send, snapshot intensity, nested event params…). Multiple curves on one property combine.

---

## Modulators (variation without extra assets)

Applied on top of base + automation. Multiple modulators add.

- **Random** — one roll per trigger (pitch/vol/any unit)
- **AHDSR** — Attack, Hold, Decay, Sustain, Release + Initial / Peak / Final. Clock = instance (follows pitch) or global
- **LFO** — sine / square / triangle / saw up / saw down / noise stepped / noise ramped; depth, rate (Hz or beats), phase, direction, tempo sync
- **Seek** — slew-limit a property or parameter (asymmetric up/down)
- **Autopitch** — map a parameter’s position onto instrument pitch (useful on Distance or RPM)
- **Sidechain / Spectral Sidechain** — follow a Sidechain tap (RMS or spectral centroid); amount, attack, release, threshold

---

## 3D / spatial playback

An event is 3D if it has a Spatializer / Object Spatializer / 3rd-party spatializer, a built-in 3D parameter, or a nested 3D event.

**FMOD Spatializer** (usual SFX path; stays in the mixer)

- Roll-off: Linear Squared (Studio default), Linear, Inverse, Inverse Tapered, Custom curve, Off
- Min/Max Distance — from event macros, or **Distance Override** on the effect
- Extent: Auto / User / Off — **Sound Size** + **Min Extent** stop the image from flipping L↔R as the listener walks through the source
- 2D mix / panner override (blend to non-spatial)
- Doppler amount
- Output format follows platform speaker mode (including 7.1.4 height)

**Object Spatializer** — same attenuation family, but **bypasses the mixer** (no downstream FX/sends; platform object-panners / Atmos-style beds). Not captured by the profiler mix.

**Runtime 3D inputs (game every frame)**

- `EventInstance.set3DAttributes` — position, velocity, forward, up
- `System.setListenerAttributes` + listener count
- `setListenerMask` — which listeners this instance hears
- `setProperty` can override min/max distance, cooldown, priority at runtime
- Occlusion / transmission / air absorption are **not** magic in stock FMOD — designer usually automates a filter/volume from a game-driven user parameter, or uses a plugin (Steam Audio, Meta XR, etc.)

**Sandbox** in Studio is the designer’s 3D preview: multiple emitters + listeners, live parameters.

---

## Mixer, buses, VCAs, snapshots

This is how SFX sit in the game mix after the event has produced audio.

- **Master / Group buses** — volume, pitch, DSP chain, sends. Group buses can have their own Max Instances + stealing.
- **Return buses** — wet FX (shared reverb/delay). Send level is the knob; typical IR/reverb return is dry −∞ dB, wet 0 dB.
- **Port buses** — dump to a device (controller speaker, vibration, voice chat, VR haptics) instead of the main mix.
- **Sends** — tap a track or bus at a point in the chain; only property is send level (automatable).
- **Transceiver** — 32 global slots, send/receive without a return bus (radio / PA / world speakers).
- **VCAs** — parallel volume groups (SFX / Music / Dialogue / UI). Game code sets VCA volume; they do not change routing.

**Snapshots** = instanceable mix states, started like events (`snapshot:/Name`) or via snapshot instruments.

- **Overriding** vs **Blending** (blend *adds* on volume-class properties: bus vol, send, gain)
- **Intensity** 0–100% (AHDSR / Seek for fades). Multiple instances of the same snapshot average intensity.
- **Priority** = browser order. **Groups** average same-priority snapshots (room sets).
- Only **scoped** properties change. Snapshots can have parameters, automation, logic, modulators — no audio files.

---

## Built-in DSP the designer hangs on tracks or buses

Most knobs are automatable + modulatable.

- EQ: 3-EQ, Multiband, Parametric, HP/LP (simple and full)
- Dynamics: Compressor (threshold, ratio, attack, release, makeup, linked, sidechain), Limiter, Gain
- Time: Delay, Chorus, Flanger, Tremolo, Pitch Shifter
- Space: SFX Reverb (decay, early/late, HF ratio, diffusion, density, wet/dry…), Convolution Reverb (IR)
- Utility: Distortion, Channel Mix, Panner, Sidechain tap
- Plugins: Steam Audio, Meta XR, Resonance, custom DSPs — these add occlusion, transmission, reflections, HRTF

---

## Runtime API surface that actually changes SFX

**EventInstance**

- `start` / `stop(ALLOWFADEOUT | IMMEDIATE)` / `release`
- `setPaused`, `getPlaybackState`, `isVirtual`
- `setVolume`, `setPitch`
- `setParameterByName` / `ByID` (local); `ignoreseekspeed` option
- `setTimelinePosition`, `keyOff` (release sustain points)
- `set3DAttributes`, `setListenerMask`, `getMinMaxDistance`
- `setProperty` — priority, schedule delay/lookahead, min/max distance, cooldown
- Callbacks: created, starting, started, stopped, timeline marker/beat, programmer sound create/destroy, virtual↔real, sound stopped

**System / Bus / VCA**

- Global `setParameterByName`
- Listener attributes + count
- Bus volume / mute / pause; VCA volume
- Bank load/unload, `loadSampleData` vs stream-from-disk
- Live Update socket (designer edits a running build: new assets, mix, parameters)

**Banks**

- Metadata vs sample data can load separately
- Streaming vs decompress-into-memory is a per-asset Studio setting
- Localization / DLC / UGC banks
- Command replay + Profiler: capture API calls, 3D poses, parameter values, CPU/voices, then scrub and re-mix

---

## How a typical SFX is actually driven in-game

1. Load bank → `createInstance("event:/sfx/…")`.
2. Each frame: `set3DAttributes`, maybe `setParameterByName("Surface", 2)` or `"Health", 0.3`.
3. Built-in Distance/Direction/Speed update themselves from those poses.
4. Instruments trigger, playlists pick a variant, modulators add grit, Spatializer pans/attenuates.
5. Signal hits group bus → sends to reverb return → VCAs → master.
6. A snapshot (`Interior`, `Underwater`, `Paused`) can restack that mix without touching the event.
7. Voice/instance limits steal or virtualize according to the macros the designer set.

If you want this mapped onto a specific engine wrapper next (Unity `StudioEventEmitter` / Unreal `FMODAudioComponent` property list), say which one and we can line the same knobs up to the component UI.
