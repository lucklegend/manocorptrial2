"""Step 6: everything -> final mp4 with ffmpeg.

Timeline: scene clips overlap by XFADE seconds and are joined with crossfades.
Narration for each scene is placed at that scene's start (+ a short lead) so
audio, captions and visuals stay in sync. Music is looped/trimmed and
side-chain ducked under the voice.
"""
import re
from pathlib import Path

from .util import ffprobe_duration, filter_script_args, log, run

FPS = 30
XFADE = 0.4
LEAD = 0.35   # silence before narration starts in each scene
TAIL = 0.35   # breathing room after each scene's narration
TRANSITIONS = ["fade", "slideleft", "smoothup", "circleopen", "fadeblack", "slideup", "radial"]
FONTS_DIR = Path(__file__).parent / "fonts"


def plan_timeline(speech_durations: list[float], intro: float = 0.0, outro: float = 0.0) -> list[dict]:
    """Return per-slot start/length in the final video timeline.

    Narrated scenes carry "voice_at". Optional intro/outro cards are slots with a
    "card" key and no narration; a length of 0 leaves the card out.
    """
    out, start = [], 0.0
    if intro:
        out.append({"start": 0.0, "length": intro + XFADE, "card": "intro"})
        start = intro
    for i, d in enumerate(speech_durations):
        last = i == len(speech_durations) - 1 and not outro
        length = LEAD + d + TAIL + (0.6 if last else XFADE)
        out.append({"start": start, "length": length, "voice_at": start + LEAD})
        start += length - XFADE
    if outro:
        out.append({"start": start, "length": outro, "card": "outro"})
    return out


def _filter_path(p: Path) -> str:
    """A path as a filter option value: escaped for the option parser (\\ ' :), then quoted for the graph parser."""
    opt = re.sub(r"([\\':])", r"\\\1", p.as_posix())
    return "'" + opt.replace("'", r"'\''") + "'"


def _cover(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def render_scene(asset, length: float, w: int, h: int, idx: int, out: Path) -> Path:
    grade = "eq=saturation=1.08:contrast=1.04,vignette=PI/5"
    if asset.kind == "video":
        src_len = ffprobe_duration(asset.path)
        # start a little into the clip (stock clips often open on a static frame)
        ss = min(1.0, max(0.0, src_len - length)) if src_len > length else 0
        vf = f"{_cover(w, h)},fps={FPS},{grade},format=yuv420p"
        cmd = ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-ss", f"{ss:.2f}", "-i", asset.path,
               "-t", f"{length:.3f}", "-vf", vf, "-an"]
    else:
        frames = int(length * FPS) + 1
        # Ken Burns: alternate zoom-in / zoom-out and pan direction per scene.
        # Upscale first so zoompan's integer rounding doesn't jitter.
        z_in = idx % 2 == 0
        z = f"min(1.0+0.12*on/{frames},1.12)" if z_in else f"max(1.12-0.12*on/{frames},1.0)"
        x = "iw/2-(iw/zoom/2)" if idx % 3 == 0 else ("(iw-iw/zoom)*on/%d" % frames if idx % 3 == 1
                                                     else "(iw-iw/zoom)*(1-on/%d)" % frames)
        y = "ih/2-(ih/zoom/2)"
        vf = (f"{_cover(w * 2, h * 2)},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS},"
              f"{grade},format=yuv420p")
        cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", asset.path, "-t", f"{length:.3f}", "-vf", vf]
    run(cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-r", str(FPS), out])
    return out


def render_card(image: Path, length: float, w: int, h: int, out: Path) -> Path:
    """A still intro/outro card shown as-is: fit inside the frame (no crop, no grade), black bars if needed."""
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
          f"setsar=1,fps={FPS},format=yuv420p")
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", image, "-t", f"{length:.3f}", "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-r", str(FPS), out])
    return out


def assemble(clips: list[Path], timeline: list[dict], voices: list[Path], music: Path,
             ass: Path, out: Path, workdir: Path, music_volume: float = 0.22) -> Path:
    total = timeline[-1]["start"] + timeline[-1]["length"]
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c.resolve())]
    for v in voices:
        inputs += ["-i", str(v.resolve())]
    inputs += ["-stream_loop", "-1", "-i", str(music.resolve())]
    n = len(clips)
    f = []

    # video: crossfade chain
    last = "[0:v]"
    for i in range(1, n):
        off = timeline[i]["start"]
        tr = TRANSITIONS[(i - 1) % len(TRANSITIONS)]
        f.append(f"{last}[{i}:v]xfade=transition={tr}:duration={XFADE}:offset={off:.3f}[vx{i}]")
        last = f"[vx{i}]"
    ass_rel = ass.relative_to(workdir)
    f.append(f"{last}subtitles={_filter_path(ass_rel)}:fontsdir={_filter_path(FONTS_DIR)},"
             f"fade=t=in:st=0:d=0.4,fade=t=out:st={total - 0.6:.3f}:d=0.6[vout]")

    # narration: delay each scene's voice to its slot (cards have none), then mix
    voiced = [tl for tl in timeline if "voice_at" in tl]
    nv = len(voices)
    for i, tl in enumerate(voiced):
        ms = int(tl["voice_at"] * 1000)
        f.append(f"[{n + i}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
    f.append("".join(f"[v{i}]" for i in range(nv)) +
             f"amix=inputs={nv}:normalize=0:duration=longest,apad,atrim=0:{total:.3f},"
             "loudnorm=I=-15:TP=-1.5:LRA=7[voice]")
    f.append("[voice]asplit=2[voice1][voice2]")
    # music: trim, lower, fade, duck under the voice
    mi = n + nv
    f.append(f"[{mi}:a]aformat=sample_rates=44100:channel_layouts=stereo,atrim=0:{total:.3f},"
             f"volume={music_volume},afade=t=in:d=1,afade=t=out:st={max(0, total - 2):.3f}:d=2[mus]")
    f.append("[mus][voice1]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[ducked]")
    f.append("[voice2][ducked]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[aout]")

    graph = workdir / "filtergraph.txt"
    graph.write_text(";\n".join(f))
    log.info("assemble: rendering %.1fs final video", total)
    run(["ffmpeg", "-y", "-v", "error", *inputs, *filter_script_args(graph.name),
         "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out.resolve()], cwd=workdir)
    return out
