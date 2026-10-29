"""Orchestrates the whole run: topic -> script -> voice -> visuals -> captions -> music -> mp4."""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from . import assemble, captions, music, script, tts
from .media import MediaFinder
from .util import log, run, write_json

FORMATS = {"vertical": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "video"


def thumbnail(src_img: Path, title: str, w: int, h: int, out: Path) -> None:
    img = Image.open(src_img).convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1))
    left, top = (img.width - w) // 2, (img.height - h) // 2
    img = img.crop((left, top, left + w, top + h))
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle([0, int(h * 0.55), w, h], fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img.convert("RGBA"), shade)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(assemble.FONTS_DIR / "InterDisplay-Black.otf"), int(w * 0.09))
    words, lines, cur = title.upper().split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=font) > w * 0.86 and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    lines.append(cur)
    y = int(h * 0.62)
    for line in lines[:4]:
        tw = d.textlength(line, font=font)
        d.text(((w - tw) / 2, y), line, font=font, fill=(255, 229, 0), stroke_width=6, stroke_fill=(0, 0, 0))
        y += int(font.size * 1.1)
    img.convert("RGB").save(out, quality=90)


def generate(topic: str, out_dir: Path, seconds: int = 60, fmt: str = "vertical",
             script_file: Optional[str] = None, llm: Optional[str] = None, tts_engine: Optional[str] = None,
             music_arg: Optional[str] = None, offline: bool = False,
             intro: Optional[str] = None, outro: Optional[str] = None, card_seconds: float = 2.5) -> Path:
    t0 = time.time()
    w, h = FORMATS[fmt]
    run_dir = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(topic)}"
    work = run_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    report = {"topic": topic, "format": f"{w}x{h}", "providers": {}}

    # 1. script
    if script_file:
        s = script.validate(json.loads(Path(script_file).read_text()))
        report["providers"]["script"] = f"file: {Path(script_file).name}"
    else:
        s, provider = script.write_script(topic, seconds, only=llm)
        report["providers"]["script"] = provider
    write_json(run_dir / "script.json", s)

    # 2. voice (sequential: edge-tts rate limits parallel sockets)
    speeches = [tts.synthesize(sc["narration"], work / f"voice_{i:02d}.wav", tts_engine)
                for i, sc in enumerate(s["scenes"])]
    report["providers"]["voice"] = sorted({sp.engine for sp in speeches})
    timeline = assemble.plan_timeline([sp.duration for sp in speeches],
                                      intro=card_seconds if intro else 0.0, outro=card_seconds if outro else 0.0)
    slots = [tl for tl in timeline if "voice_at" in tl]
    total = timeline[-1]["start"] + timeline[-1]["length"]

    # 3. visuals: search sequentially (dedupe), render scene clips in parallel
    finder = MediaFinder(work, w, h, offline=offline)
    assets = [finder.find(sc["search"], i, tl["length"]) for i, (sc, tl) in enumerate(zip(s["scenes"], slots))]
    report["providers"]["visuals"] = [a.source for a in assets]
    with ThreadPoolExecutor(max_workers=4) as pool:
        clips = list(pool.map(
            lambda a: assemble.render_scene(a[1], slots[a[0]]["length"], w, h, a[0], work / f"scene_{a[0]:02d}.mp4"),
            enumerate(assets)))
    if intro:
        clips.insert(0, assemble.render_card(Path(intro), timeline[0]["length"], w, h, work / "intro.mp4"))
    if outro:
        clips.append(assemble.render_card(Path(outro), timeline[-1]["length"], w, h, work / "outro.mp4"))
    cards = {name: Path(img).name for name, img in (("intro", intro), ("outro", outro)) if img}
    if cards:
        report["cards"] = cards

    # 4. captions
    cap_scenes = [{"start": tl["voice_at"], "headline_at": tl["start"], "duration": tl["length"] - assemble.LEAD,
                   "words": sp.words, "headline": sc.get("headline", "")}
                  for sc, sp, tl in zip(s["scenes"], speeches, slots)]
    captions.build(cap_scenes, w, h, work / "captions.ass", run_dir / "captions.srt")

    # 5. music
    track, music_src = music.pick_music(music_arg, total, work / "music.wav", seed=int(hashlib.md5(topic.encode()).hexdigest()[:4], 16))
    report["providers"]["music"] = music_src

    # 6. assemble
    final = run_dir / f"{slug(s['title'])}.mp4"
    assemble.assemble(clips, timeline, [sp.wav for sp in speeches], track, work / "captions.ass", final, work)

    # extras for posting
    thumb_src = next((a.path for a in assets if a.kind == "image"), None)
    if thumb_src is None:
        thumb_src = work / "thumb_frame.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", clips[0], "-frames:v", "1", thumb_src])
    thumbnail(thumb_src, s["title"], w, h, run_dir / "thumbnail.jpg")
    (run_dir / "credits.txt").write_text(
        "\n".join(f"Scene {i + 1}: {a.credit}" for i, a in enumerate(assets)) + f"\nMusic: {music_src}\n")
    report.update(duration_s=round(total, 1), render_time_s=round(time.time() - t0, 1),
                  output=final.name)
    write_json(run_dir / "report.json", report)
    log.info("done: %s (%.1fs video, built in %.0fs)", final, total, time.time() - t0)
    return final
