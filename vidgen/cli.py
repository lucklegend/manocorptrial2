import argparse
import logging
import os
import sys
from pathlib import Path

from .pipeline import FORMATS, generate
from .util import has


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = (x.strip() for x in line.split("=", 1))
            if k and v:
                os.environ.setdefault(k, v.strip('"').strip("'"))


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(prog="vidgen", description="Give it a topic, get back an mp4.")
    p.add_argument("topic", help='what the video is about, e.g. "why the ocean is salty"')
    p.add_argument("-d", "--duration", type=int, default=60, help="target length in seconds (default 60)")
    p.add_argument("-f", "--format", choices=FORMATS, default="vertical", help="vertical (Shorts/Reels/TikTok), landscape, square")
    p.add_argument("-o", "--out", default="output", help="output folder (default ./output)")
    p.add_argument("--script", help="use a script JSON instead of calling an LLM")
    p.add_argument("--llm", choices=["anthropic", "openai", "gemini", "ollama", "pollinations"], help="force one LLM provider")
    p.add_argument("--tts", choices=["edge", "say", "pico", "espeak"], help="force one TTS engine")
    p.add_argument("--music", help="music file, or a folder of tracks to pick from (default: composes one)")
    p.add_argument("--offline", action="store_true", help="skip all stock media lookups, use generated art")
    p.add_argument("--intro", help="image shown at the start of the video, before the first scene")
    p.add_argument("--outro", help="image shown at the end of the video, after the last scene")
    p.add_argument("--card-seconds", type=float, default=2.5, help="how long the intro/outro image is on screen (default 2.5)")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    for flag, path in (("--intro", a.intro), ("--outro", a.outro)):
        if path and not Path(path).is_file():
            p.error(f"{flag}: no such file: {path}")
    if a.card_seconds <= 0:
        p.error("--card-seconds must be greater than 0")

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not (has("ffmpeg") and has("ffprobe")):
        sys.exit("ffmpeg/ffprobe not found on PATH. Install ffmpeg first (see README).")
    out = generate(a.topic, Path(a.out), a.duration, a.format, a.script, a.llm, a.tts, a.music, a.offline,
                   intro=a.intro, outro=a.outro, card_seconds=a.card_seconds)
    print(out)


if __name__ == "__main__":
    main()
