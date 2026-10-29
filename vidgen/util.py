import json
import logging
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

log = logging.getLogger("vidgen")

UA = {"User-Agent": "vidgen/0.1 (prototype video generator)"}


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    log.debug("$ %s", " ".join(str(c) for c in cmd))
    res = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if res.returncode != 0:
        raise RuntimeError(f"command failed: {cmd[0]}\n{res.stderr[-2000:]}")
    return res


def ffprobe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", path]).stdout.strip()
    return float(out)


@lru_cache(maxsize=None)
def ffmpeg_major() -> Optional[int]:
    """Major version of the installed ffmpeg, or None for git/nightly builds ("N-12345-g...")."""
    m = re.match(r"ffmpeg version n?(\d+)\.", run(["ffmpeg", "-version"]).stdout)
    return int(m.group(1)) if m else None


def filter_script_args(path: str) -> list[str]:
    """Read a filtergraph from a file. ffmpeg 7 added `-/filter_complex`; 9 removed `-filter_complex_script`."""
    major = ffmpeg_major()
    if major is not None and major < 7:
        return ["-filter_complex_script", path]
    return ["-/filter_complex", path]


def has(binary: str) -> bool:
    return shutil.which(binary) is not None


def env(name: str) -> Optional[str]:
    v = os.environ.get(name, "").strip()
    return v or None


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
