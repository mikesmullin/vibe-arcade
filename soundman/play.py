#!/usr/bin/env python
"""play.py: one-shot wav playback through the local speakers (blocking).

    python3 play.py out/sfx_patty_sizzle_loop/audition.wav
    python3 play.py out/sfx_patty_sizzle_loop/sfx_patty_sizzle_loop_v01.wav

Pure Python: stdlib wave + ctypes straight into libpulse-simple (the same
pa_simple API the voice daemon uses). No player binary, no extra deps —
only numpy for sample-width conversion when the wav isn't 16-bit.
"""
import argparse
import ctypes
import sys
import wave
from ctypes import POINTER, c_char_p, c_int, c_size_t, c_uint8, c_uint32, c_void_p
from pathlib import Path

import numpy as np

# pa_sample_format: U8=0, S16LE=3, S16BE=4, FLOAT32LE=5 (we map everything to these)
_PA_FORMAT = {1: 0, 2: 3, 4: 5}
PA_STREAM_PLAYBACK = 1


class _SampleSpec(ctypes.Structure):
    _fields_ = [("format", c_int), ("rate", c_uint32), ("channels", c_uint8)]


def _lib():
    lib = ctypes.CDLL("libpulse-simple.so.0")
    lib.pa_simple_new.restype = c_void_p
    lib.pa_simple_new.argtypes = [c_char_p, c_char_p, c_int, c_char_p, c_char_p,
                                  POINTER(_SampleSpec), c_void_p, c_void_p,
                                  POINTER(c_int)]
    lib.pa_simple_write.restype = c_int
    lib.pa_simple_write.argtypes = [c_void_p, c_void_p, c_size_t, POINTER(c_int)]
    lib.pa_simple_drain.restype = c_int
    lib.pa_simple_drain.argtypes = [c_void_p, POINTER(c_int)]
    lib.pa_simple_free.argtypes = [c_void_p]
    lib.pa_strerror.restype = c_char_p
    lib.pa_strerror.argtypes = [c_int]
    return lib


def _pcm_bytes(path: Path):
    """Wav -> (raw bytes, pa_format, rate, channels), converted as needed."""
    try:
        w = wave.open(str(path), "rb")
    except wave.Error:
        sys.exit(f"play.py: {path.name} is not a WAV file — mp3 previews play "
                 f"in any browser; to hear one here: ffmpeg -i {path.name} "
                 f"-ar 48000 -ac 1 /tmp/preview.wav")
    with w:
        n, sw, sr, ch = w.getnframes(), w.getsampwidth(), w.getframerate(), w.getnchannels()
        raw = w.readframes(n)
    if sw == 2:
        return raw, _PA_FORMAT[2], sr, ch
    if sw == 1:
        return raw, _PA_FORMAT[1], sr, ch
    x = np.frombuffer(raw, dtype=np.int32 if sw == 4 else np.float32)
    if sw == 4:
        x = (x.astype(np.float64) / 2147483648.0)
    x = np.clip(x, -1.0, 1.0)
    return (x * 32767).astype(np.int16).tobytes(), _PA_FORMAT[2], sr, ch


def play(path: Path):
    pcm, fmt, sr, ch = _pcm_bytes(path)
    lib = _lib()
    err = c_int(0)
    spec = _SampleSpec(fmt, sr, ch)
    pa = lib.pa_simple_new(None, b"soundman", PA_STREAM_PLAYBACK, None,
                           f"playback {path.name}".encode(), ctypes.byref(spec),
                           None, None, ctypes.byref(err))
    if not pa:
        sys.exit(f"play.py: pa_simple_new failed: "
                 f"{lib.pa_strerror(err.value).decode(errors='replace')}")
    try:
        step = 4096 * ch * (2 if fmt == _PA_FORMAT[2] else 1)
        for off in range(0, len(pcm), step):
            chunk = pcm[off:off + step]
            if lib.pa_simple_write(pa, chunk, len(chunk), ctypes.byref(err)) < 0:
                sys.exit(f"play.py: pa_simple_write failed: "
                         f"{lib.pa_strerror(err.value).decode(errors='replace')}")
        if lib.pa_simple_drain(pa, ctypes.byref(err)) < 0:
            sys.exit(f"play.py: pa_simple_drain failed: "
                     f"{lib.pa_strerror(err.value).decode(errors='replace')}")
    finally:
        lib.pa_simple_free(pa)
    print(f"played {path.name} via libpulse-simple ({sr} Hz, {ch}ch)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", help="wav file to play (one-shot, blocking)")
    a = ap.parse_args()
    wav = Path(a.wav)
    if not wav.is_file():
        sys.exit(f"play.py: no such file: {wav}")
    play(wav)


if __name__ == "__main__":
    main()
