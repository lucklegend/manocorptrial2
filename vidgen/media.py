"""Step 3: search query -> a visual for each scene (video clip or still image).

Sources, best first. Keyed ones are free accounts:
  pexels-video, pixabay-video     real stock footage    (PEXELS_API_KEY / PIXABAY_API_KEY)
  pexels-photo, pixabay-photo     stock photos          (same keys)
  openverse, wikimedia            CC-licensed photos    (no key)
  generated                       procedural art        (offline, always works)
Every downloaded asset is logged with its source and license in credits.txt.
"""
import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

from .util import UA, env, log


@dataclass
class Asset:
    path: Path
    kind: str  # "video" | "image"
    source: str
    credit: str


class MediaFinder:
    def __init__(self, workdir: Path, width: int, height: int, offline: bool = False):
        self.dir = workdir / "media"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.w, self.h = width, height
        self.portrait = height > width
        self.offline = offline
        self.used: set[str] = set()  # never show the same clip twice
        self.dead: set[str] = set()  # sources that can't be reached this run
        self.pexels = env("PEXELS_API_KEY")
        self.pixabay = env("PIXABAY_API_KEY")

    # ---------- public ----------
    def find(self, query: str, idx: int, min_seconds: float) -> Asset:
        sources = [] if self.offline else [
            self._pexels_video, self._pixabay_video, self._pexels_photo,
            self._pixabay_photo, self._openverse, self._wikimedia]
        for q in self._queries(query):
            for src in sources:
                if src.__name__ in self.dead:
                    continue
                try:
                    asset = src(q, idx, min_seconds)
                    if asset:
                        log.info("media: scene %d '%s' -> %s", idx + 1, q, asset.source)
                        return asset
                except LookupError:
                    continue
                except requests.ConnectionError as e:
                    self.dead.add(src.__name__)
                    log.warning("media: %s unreachable, skipping it for this run (%s)", src.__name__.strip("_"), str(e)[:120])
                except Exception as e:
                    log.warning("media: %s failed for '%s': %s", src.__name__.strip("_"), q, str(e)[:160])
        log.info("media: scene %d -> generated art", idx + 1)
        return self._generated(query, idx)

    # ---------- helpers ----------
    @staticmethod
    def _queries(query: str):
        # full query first, then progressively shorter so niche queries still hit something
        words = query.split()
        yield query
        if len(words) > 2:
            yield " ".join(words[:2])
        if len(words) > 1:
            yield words[0]

    def _download(self, url: str, name: str, headers=None) -> Path:
        path = self.dir / name
        with requests.get(url, headers=headers or UA, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return path

    def _fresh(self, key: str) -> bool:
        if key in self.used:
            return False
        self.used.add(key)
        return True

    # ---------- sources ----------
    def _pexels_video(self, q, idx, min_s):
        if not self.pexels:
            raise LookupError
        r = requests.get("https://api.pexels.com/videos/search", timeout=30,
                         headers={"Authorization": self.pexels},
                         params={"query": q, "per_page": 15,
                                 "orientation": "portrait" if self.portrait else "landscape"})
        r.raise_for_status()
        for v in r.json().get("videos", []):
            if v["duration"] < min(min_s, 6) or not self._fresh(f"pexels-v{v['id']}"):
                continue
            files = [f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("height")]
            if not files:
                continue
            target = max(self.w, self.h)
            best = min(files, key=lambda f: abs(max(f["width"], f["height"]) - target))
            path = self._download(best["link"], f"s{idx:02d}_pexels_{v['id']}.mp4")
            return Asset(path, "video", "pexels-video", f"Video by {v['user']['name']} on Pexels ({v['url']})")
        return None

    def _pixabay_video(self, q, idx, min_s):
        if not self.pixabay:
            raise LookupError
        r = requests.get("https://pixabay.com/api/videos/", timeout=30,
                         params={"key": self.pixabay, "q": q, "per_page": 15, "safesearch": "true"})
        r.raise_for_status()
        for v in r.json().get("hits", []):
            if v["duration"] < min(min_s, 6) or not self._fresh(f"pixabay-v{v['id']}"):
                continue
            f = v["videos"].get("medium") or v["videos"].get("large")
            if not f or not f.get("url"):
                continue
            path = self._download(f["url"], f"s{idx:02d}_pixabay_{v['id']}.mp4")
            return Asset(path, "video", "pixabay-video", f"Video by {v['user']} on Pixabay ({v['pageURL']})")
        return None

    def _pexels_photo(self, q, idx, _):
        if not self.pexels:
            raise LookupError
        r = requests.get("https://api.pexels.com/v1/search", timeout=30,
                         headers={"Authorization": self.pexels},
                         params={"query": q, "per_page": 15,
                                 "orientation": "portrait" if self.portrait else "landscape"})
        r.raise_for_status()
        for p in r.json().get("photos", []):
            if self._fresh(f"pexels-p{p['id']}"):
                path = self._download(p["src"]["large2x"], f"s{idx:02d}_pexels_{p['id']}.jpg")
                return Asset(path, "image", "pexels-photo", f"Photo by {p['photographer']} on Pexels ({p['url']})")
        return None

    def _pixabay_photo(self, q, idx, _):
        if not self.pixabay:
            raise LookupError
        r = requests.get("https://pixabay.com/api/", timeout=30, params={
            "key": self.pixabay, "q": q, "image_type": "photo", "per_page": 15, "safesearch": "true",
            "orientation": "vertical" if self.portrait else "horizontal"})
        r.raise_for_status()
        for p in r.json().get("hits", []):
            if self._fresh(f"pixabay-p{p['id']}"):
                path = self._download(p["largeImageURL"], f"s{idx:02d}_pixabay_{p['id']}.jpg")
                return Asset(path, "image", "pixabay-photo", f"Image by {p['user']} on Pixabay ({p['pageURL']})")
        return None

    def _openverse(self, q, idx, _):
        r = requests.get("https://api.openverse.org/v1/images/", headers=UA, timeout=30, params={
            "q": q, "page_size": 20, "license_type": "commercial", "mature": "false",
            "aspect_ratio": "tall" if self.portrait else "wide"})
        r.raise_for_status()
        for p in r.json().get("results", []):
            if (p.get("width") or 0) < 900 or not self._fresh(f"ov-{p['id']}"):
                continue
            ext = (p.get("filetype") or "jpg").replace("jpeg", "jpg")
            if ext not in ("jpg", "png"):
                continue
            path = self._download(p["url"], f"s{idx:02d}_openverse.{ext}")
            lic = f"CC {p.get('license', '').upper()} {p.get('license_version', '')}".strip()
            return Asset(path, "image", "openverse",
                         f"\"{p.get('title')}\" by {p.get('creator')} ({lic}) {p.get('foreign_landing_url')}")
        return None

    def _wikimedia(self, q, idx, _):
        r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"filetype:bitmap {q}", "gsrlimit": 15, "prop": "imageinfo",
            "iiprop": "url|size|extmetadata", "iiurlwidth": 1920})
        r.raise_for_status()
        pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
        for p in pages:
            info = (p.get("imageinfo") or [{}])[0]
            if info.get("width", 0) < 900 or not self._fresh(f"wm-{p['pageid']}"):
                continue
            meta = info.get("extmetadata", {})
            lic = meta.get("LicenseShortName", {}).get("value", "")
            if not any(k in lic for k in ("CC BY", "CC0", "Public domain", "PD")):
                continue
            path = self._download(info.get("thumburl") or info["url"], f"s{idx:02d}_wikimedia.jpg")
            artist = meta.get("Artist", {}).get("value", "unknown")
            return Asset(path, "image", "wikimedia", f"{p['title']} by {artist} ({lic}) {info['descriptionurl']}")
        return None

    def _generated(self, query: str, idx: int) -> Asset:
        """Offline fallback: soft abstract 'aurora' art, palette seeded from the query."""
        seed = int(hashlib.md5(f"{query}{idx}".encode()).hexdigest(), 16)
        rnd = random.Random(seed)
        w, h = int(self.w * 1.25), int(self.h * 1.25)  # oversize so Ken Burns has room
        base_hue = rnd.random()

        def hsv(hh, s, v):
            import colorsys
            r, g, b = colorsys.hsv_to_rgb(hh % 1, s, v)
            return int(r * 255), int(g * 255), int(b * 255)

        img = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(img)
        top, bot = hsv(base_hue, 0.7, 0.18), hsv(base_hue + 0.08, 0.8, 0.05)
        for y in range(h):
            t = y / h
            d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
        glow = Image.new("RGB", (w, h))
        gd = ImageDraw.Draw(glow)
        for _ in range(7):
            r = rnd.randint(min(w, h) // 6, min(w, h) // 2)
            cx, cy = rnd.randint(0, w), rnd.randint(0, h)
            col = hsv(base_hue + rnd.uniform(-0.12, 0.25), 0.75, rnd.uniform(0.5, 0.95))
            gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) // 7))
        img = Image.blend(img, glow, 0.55)
        # fine diagonal light streaks for texture
        streaks = Image.new("L", (w, h), 0)
        sd = ImageDraw.Draw(streaks)
        for _ in range(40):
            x = rnd.randint(-h, w)
            sd.line([(x, 0), (x + int(h * math.tan(0.5)), h)], fill=rnd.randint(10, 40), width=rnd.randint(1, 4))
        streaks = streaks.filter(ImageFilter.GaussianBlur(3))
        img = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), img, streaks)
        path = self.dir / f"s{idx:02d}_generated.jpg"
        img.save(path, quality=92)
        return Asset(path, "image", "generated", "Procedurally generated background (vidgen)")
