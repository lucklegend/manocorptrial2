"""Step 4: background music.

Uses --music (a file, or a folder of royalty-free tracks to pick from) when given.
Otherwise it composes a royalty-free lo-fi ambient bed from scratch with numpy,
so every video has music with zero licensing risk.
"""
import random
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from .util import log

SR = 44100
# i - vi - IV - V in a few keys, as semitone offsets from A3
PROGRESSIONS = [
    [[0, 4, 7, 11], [-3, 0, 4, 7], [-7, -3, 0, 4], [-5, -1, 2, 5]],   # Imaj7 vi IV V
    [[0, 3, 7, 10], [-4, 0, 3, 7], [-9, -5, -2, 2], [-2, 2, 5, 9]],   # minor: i VI III VII
]


def _hz(semi: float) -> float:
    return 220.0 * 2 ** (semi / 12)


def _env(n: int, attack: float, release: float) -> np.ndarray:
    a, r = min(int(attack * SR), n // 2), min(int(release * SR), n // 2)
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def compose(seconds: float, out: Path, seed: int = 0) -> Path:
    rnd = random.Random(seed)
    prog = rnd.choice(PROGRESSIONS)
    key = rnd.choice([-5, -3, 0, 2, 3])
    bpm = rnd.choice([72, 76, 80, 84])
    beat = 60 / bpm
    bar = beat * 4
    n_total = int((seconds + 2) * SR)
    mix = np.zeros(n_total)
    t_bar = np.arange(int(bar * 2 * SR)) / SR  # each chord lasts 2 bars

    pos, ci = 0, 0
    while pos < n_total:
        chord = [s + key for s in prog[ci % len(prog)]]
        n = min(len(t_bar), n_total - pos)
        t = t_bar[:n]
        # warm pad: detuned sines + soft 2nd harmonic, slow swell
        pad = np.zeros(n)
        for s in chord:
            f = _hz(s)
            for det in (-0.12, 0.0, 0.12):
                ff = f * 2 ** (det / 12)
                pad += np.sin(2 * np.pi * ff * t) + 0.25 * np.sin(4 * np.pi * ff * t)
        pad *= _env(n, 0.8, 0.8) * 0.035
        # sub bass on the root
        bass = np.sin(2 * np.pi * _hz(chord[0] - 12) * t) * _env(n, 0.05, 0.5) * 0.12
        # plucked arpeggio, eighth notes, upper octave
        arp = np.zeros(n)
        step = int(beat / 2 * SR)
        pattern = [0, 2, 1, 3, 2, 1, 3, 2]
        for k in range(0, n // step):
            s0 = k * step
            note = chord[pattern[k % 8] % len(chord)] + 12
            m = min(step * 2, n - s0)
            tt = np.arange(m) / SR
            pluck = np.sin(2 * np.pi * _hz(note) * tt) * np.exp(-tt * 7)
            arp[s0:s0 + m] += pluck * (0.045 if k % 2 == 0 else 0.03)
        # soft kick + hat for a lo-fi pulse
        drums = np.zeros(n)
        for k in range(int(n / (beat * SR))):
            s0 = int(k * beat * SR)
            m = min(int(0.25 * SR), n - s0)
            tt = np.arange(m) / SR
            if k % 2 == 0:
                drums[s0:s0 + m] += np.sin(2 * np.pi * (50 + 60 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 12) * 0.18
            h0 = s0 + int(beat / 2 * SR)
            hm = min(int(0.05 * SR), n - h0)
            if hm > 0:
                drums[h0:h0 + hm] += np.random.default_rng(k).uniform(-1, 1, hm) * np.exp(-np.arange(hm) / SR * 80) * 0.02
        mix[pos:pos + n] += pad + bass + arp + drums
        pos += n
        ci += 1

    # gentle low-pass (one-pole) for the lo-fi feel, then fades + normalise
    alpha = 0.35
    y = np.empty_like(mix)
    acc = 0.0
    for i, x in enumerate(mix):
        acc += alpha * (x - acc)
        y[i] = acc
    y = y[: int(seconds * SR)]
    fade = int(1.5 * SR)
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    y /= max(1e-6, np.abs(y).max()) / 0.7
    stereo = np.stack([y, np.roll(y, 300)], axis=1)  # tiny Haas delay for width
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    log.info("music: composed %.0fs lo-fi bed (%d bpm)", seconds, bpm)
    return out


def pick_music(music_arg: Optional[str], seconds: float, out: Path, seed: int) -> tuple[Path, str]:
    if music_arg:
        p = Path(music_arg).expanduser()
        if p.is_dir():
            tracks = [f for f in p.iterdir() if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")]
            if tracks:
                choice = random.Random(seed).choice(tracks)
                log.info("music: using %s", choice.name)
                return choice, f"track: {choice.name}"
        elif p.is_file():
            return p, f"track: {p.name}"
        log.warning("music: %s not usable, composing instead", music_arg)
    return compose(seconds, out, seed), "composed by vidgen (numpy synth)"
