"""Step 5: word timings -> animated ASS subtitles.

Two layers:
  Caption   short-form style: 1-3 words at a time, big, the spoken word highlighted
  Headline  the scene's punchy on-screen text, popped in at the top for a few seconds
Also writes a plain .srt so the captions can be uploaded as a separate track.
"""
from pathlib import Path

from .tts import Word

FONT = "Inter Display Black"


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _srt_ts(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")")


def chunk(words: list[Word], max_words: int = 3, max_chars: int = 18) -> list[list[Word]]:
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(x.text for x in cur + [w])) > max_chars):
            out.append(cur)
            cur = []
        cur.append(w)
        if w.text[-1:] in ".,!?;:":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def build(scenes: list[dict], width: int, height: int, ass_path: Path, srt_path: Path) -> None:
    """scenes: [{"start": float, "duration": float, "words": [Word], "headline": str}] with
    word times relative to the scene start."""
    portrait = height > width
    cap_size = int(width * (0.085 if portrait else 0.055))
    head_size = int(width * (0.075 if portrait else 0.045))
    cap_y = int(height * (0.30 if portrait else 0.12))  # margin from bottom
    head_y = int(height * (0.12 if portrait else 0.08))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{FONT},{cap_size},&H00FFFFFF,&H0000E5FF,&H00101010,&H96000000,0,0,0,0,100,100,1,0,1,{max(4, cap_size // 11)},{max(2, cap_size // 22)},2,60,60,{cap_y},1
Style: Headline,{FONT},{head_size},&H00101010,&H00FFFFFF,&H0000D7FF,&H0000D7FF,0,0,0,0,100,100,2,0,3,{max(10, head_size // 4)},0,8,80,80,{head_y},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events, srt, n = [], [], 1
    for sc in scenes:
        base = sc["start"]
        if sc.get("headline"):
            h_start = sc.get("headline_at", base)
            h_end = h_start + min(3.2, sc["duration"] - 0.2)
            events.append(
                f"Dialogue: 1,{_ts(h_start + 0.15)},{_ts(h_end)},Headline,,0,0,0,,"
                r"{\fad(120,200)\t(0,180,\fscx108\fscy108)\t(180,320,\fscx100\fscy100)}"
                f"{_esc(sc['headline'].upper())}")
        groups = chunk(sc["words"])
        for gi, group in enumerate(groups):
            next_start = groups[gi + 1][0].start if gi + 1 < len(groups) else float("inf")
            g_start, g_end = base + group[0].start, base + group[-1].end
            srt.append(f"{n}\n{_srt_ts(g_start)} --> {_srt_ts(g_end)}\n{' '.join(w.text for w in group)}\n")
            n += 1
            for i, w in enumerate(group):
                w_start = base + w.start
                w_end = base + (group[i + 1].start if i + 1 < len(group) else min(w.end + 0.08, next_start))
                parts = []
                for j, other in enumerate(group):
                    txt = _esc(other.text.upper())
                    parts.append(r"{\c&H0000E5FF&}" + txt + r"{\c&H00FFFFFF&}" if j == i else txt)
                pop = r"{\fscx112\fscy112\t(0,90,\fscx100\fscy100)}" if i == 0 else ""
                events.append(f"Dialogue: 0,{_ts(w_start)},{_ts(w_end)},Caption,,0,0,0,,{pop}{' '.join(parts)}")
    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    srt_path.write_text("\n".join(srt), encoding="utf-8")
