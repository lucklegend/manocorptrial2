"""Step 1: topic -> structured script (title + scenes).

Tries LLM providers in order and falls back to an offline template, so the
pipeline never stops here. Every provider must return the same JSON shape:

{
  "title": "...",
  "scenes": [
    {"narration": "...", "search": "2-4 word stock footage query", "headline": "SHORT ON-SCREEN TEXT"}
  ]
}
"""
import json
import re
from typing import Optional

import requests

from .util import env, log

WORDS_PER_SECOND = 2.6

PROMPT = """You write scripts for short faceless explainer videos (YouTube Shorts / Reels / TikTok).

Topic: {topic}
Target length: about {seconds} seconds of narration (~{words} words total), split into {scenes} scenes.

Rules:
- Scene 1 is a hook: a surprising fact or question that stops the scroll.
- Middle scenes each deliver ONE concrete, accurate point. No filler, no "in this video".
- Last scene lands the payoff and a one-line call to action.
- Conversational, spoken English. Short sentences. No emojis, no hashtags, no stage directions.
- "search" is a 2-4 word query for stock footage that would literally show what is being said
  (concrete nouns: "ocean waves aerial", "rock erosion river"), never abstract words.
- "headline" is 1-4 punchy words shown big on screen.

Return ONLY JSON, no markdown fences:
{{"title": "...", "scenes": [{{"narration": "...", "search": "...", "headline": "..."}}]}}"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _anthropic(prompt: str) -> str:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        raise LookupError("no ANTHROPIC_API_KEY")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": env("VIDGEN_ANTHROPIC_MODEL") or "claude-sonnet-5-5", "max_tokens": 2000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=90,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def _openai(prompt: str) -> str:
    key = env("OPENAI_API_KEY")
    if not key:
        raise LookupError("no OPENAI_API_KEY")
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": env("VIDGEN_OPENAI_MODEL") or "gpt-4o-mini",
              "response_format": {"type": "json_object"},
              "messages": [{"role": "user", "content": prompt}]},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _gemini(prompt: str) -> str:
    key = env("GEMINI_API_KEY")
    if not key:
        raise LookupError("no GEMINI_API_KEY")
    model = env("VIDGEN_GEMINI_MODEL") or "gemini-3.5-flash"
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},  # not in the URL, so error messages don't leak it
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseMimeType": "application/json"}},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _ollama(prompt: str) -> str:
    """Local LLM, free, no key. Only used if an Ollama server is running."""
    host = env("OLLAMA_HOST") or "http://localhost:11434"
    r = requests.post(f"{host}/api/generate", timeout=180, json={
        "model": env("VIDGEN_OLLAMA_MODEL") or "llama3.1", "prompt": prompt,
        "format": "json", "stream": False})
    r.raise_for_status()
    return r.json()["response"]


def _pollinations(prompt: str) -> str:
    """Free keyless public endpoint. Best effort, rate limited."""
    r = requests.post("https://text.pollinations.ai/openai", timeout=90, json={
        "model": "openai", "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


PROVIDERS = [("anthropic", _anthropic), ("openai", _openai), ("gemini", _gemini),
             ("ollama", _ollama), ("pollinations", _pollinations)]


def _template(topic: str, n: int) -> dict:
    """Offline last resort. Generic, but keeps the pipeline end-to-end."""
    t = topic.strip().rstrip(".?!")
    lines = [
        (f"Most people get {t} completely wrong. Here's what's actually going on.", "WAIT, WHAT?"),
        (f"First, the basics. {t} is simpler than it looks once you see the pieces.", "THE BASICS"),
        ("Here's the part nobody tells you. The details matter more than the big idea.", "THE SECRET"),
        ("Second, small changes add up. Tiny steps, repeated, beat one big leap.", "SMALL STEPS"),
        ("Third, watch out for the common mistake. Rushing in without a plan.", "AVOID THIS"),
        (f"So next time someone brings up {t}, you'll know the real story. Follow for more.", "NOW YOU KNOW"),
    ]
    words = [w for w in re.findall(r"[A-Za-z]+", t) if len(w) > 3] or [t]
    search = " ".join(words[:3])
    return {"title": t.title(), "scenes": [
        {"narration": nar, "search": search, "headline": head} for nar, head in lines[:max(n, 3)]]}


def validate(script: dict) -> dict:
    scenes = [s for s in script.get("scenes", []) if str(s.get("narration", "")).strip()]
    if not scenes:
        raise ValueError("script has no scenes")
    for s in scenes:
        s["narration"] = " ".join(str(s["narration"]).split())
        s.setdefault("search", script.get("title", ""))
        s.setdefault("headline", "")
    return {"title": script.get("title", "Untitled"), "scenes": scenes}


def write_script(topic: str, seconds: int, only: Optional[str] = None) -> tuple[dict, str]:
    n_scenes = max(3, min(10, round(seconds / 9)))
    prompt = PROMPT.format(topic=topic, seconds=seconds, words=int(seconds * WORDS_PER_SECOND), scenes=n_scenes)
    for name, fn in PROVIDERS:
        if only and name != only:
            continue
        try:
            script = validate(_extract_json(fn(prompt)))
            log.info("script: written by %s (%d scenes)", name, len(script["scenes"]))
            return script, name
        except LookupError as e:
            log.debug("script: skip %s (%s)", name, e)
        except Exception as e:  # network, bad JSON, rate limit... try the next one
            log.warning("script: %s failed: %s", name, str(e)[:200])
    log.warning("script: all LLM providers unavailable, using offline template")
    return validate(_template(topic, n_scenes)), "template"
