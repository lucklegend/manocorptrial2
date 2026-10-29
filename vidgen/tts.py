"""Step 2: narration text -> voice audio + per-word timings (for captions).

Engines, best first:
  edge-tts   free neural voices, no key, gives exact word timings (needs internet)
  say        macOS built-in
  pico2wave  offline (apt install libttspico-utils)
  espeak-ng  offline, robotic, always installable
Word timings from engines that don't report them are estimated from syllable weight.
"""
import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .util import env, ffprobe_duration, has, log, run


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Speech:
    wav: Path
    duration: float
    words: list[Word]
    engine: str


def _weight(word: str) -> float:
    syll = max(1, len(re.findall(r"[aeiouy]+", word.lower())))
    pause = 1.2 if word[-1:] in ",;:" else 2.0 if word[-1:] in ".!?" else 0
    return syll + pause


def estimate_words(text: str, duration: float, lead: float = 0.05) -> list[Word]:
    words = text.split()
    weights = [_weight(w) for w in words]
    total = sum(weights) or 1
    t, out = lead, []
    span = max(0.1, duration - lead - 0.1)
    for w, wt in zip(words, weights):
        d = span * wt / total
        out.append(Word(w, t, t + d))
        t += d
    return out


def _to_wav(src: Path, dst: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ar", "44100", "-ac", "1", dst])


async def _edge(text: str, voice: str, mp3: Path) -> list[Word]:
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=env("VIDGEN_TTS_RATE") or "+8%", boundary="WordBoundary")
    words = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append(Word(chunk["text"], s, s + chunk["duration"] / 1e7))
    return words


def synthesize(text: str, out_wav: Path, engine: str | None = None) -> Speech:
    order = [engine] if engine else ["edge", "say", "pico", "espeak"]
    for eng in order:
        try:
            if eng == "edge":
                mp3 = out_wav.with_suffix(".mp3")
                voice = env("VIDGEN_VOICE") or "en-US-AndrewMultilingualNeural"
                words = asyncio.run(_edge(text, voice, mp3))
                _to_wav(mp3, out_wav)
                dur = ffprobe_duration(out_wav)
                # edge drops punctuation from word text; re-attach it from the source for captions
                src = text.split()
                if len(src) == len(words):
                    for w, s in zip(words, src):
                        w.text = s
                return Speech(out_wav, dur, words or estimate_words(text, dur), "edge-tts")
            if eng == "say" and sys.platform == "darwin" and has("say"):
                aiff = out_wav.with_suffix(".aiff")
                run(["say", "-o", aiff, text])
                _to_wav(aiff, out_wav)
            elif eng == "pico" and has("pico2wave"):
                raw = out_wav.with_suffix(".pico.wav")
                run(["pico2wave", "-l", "en-US", "-w", raw, text])
                # pico is a little slow and thin: speed up slightly, warm it with a low shelf
                run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af",
                     "atempo=1.08,bass=g=3:f=180,highpass=f=70,loudnorm=I=-16",
                     "-ar", "44100", "-ac", "1", out_wav])
            elif eng == "espeak" and has("espeak-ng"):
                run(["espeak-ng", "-v", "en-us", "-s", "160", "-w", out_wav, text])
            else:
                continue
            dur = ffprobe_duration(out_wav)
            return Speech(out_wav, dur, estimate_words(text, dur), eng)
        except Exception as e:
            log.warning("tts: %s failed: %s", eng, str(e)[:200])
    raise RuntimeError("no TTS engine worked; install edge-tts (pip) or espeak-ng")
