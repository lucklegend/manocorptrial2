# Trial task: automated video generator (Janno)

**How it works**
It's a Python CLI, `python -m vidgen "<topic>"`, and it runs a 6-step pipeline. First an LLM writes a scene-by-scene script as JSON (narration, a footage search query and an on-screen headline for each scene). Then edge-tts records the voiceover and gives me word-level timestamps. Next it pulls matching stock clips from Pexels or Pixabay (or CC photos from Openverse or Wikimedia), never repeating a clip. It burns in TikTok-style captions with the spoken word highlighted, composes a royalty-free music bed, ducks the music under the voice, and renders everything with ffmpeg using crossfade transitions. It also writes a thumbnail, an .srt, a credits file and a report of which provider handled each step.

I designed it so every step has a free or offline fallback. With zero API keys and no internet it still produces a full mp4 (template script, offline TTS, generated visuals). Adding keys only makes it better. The sample I attached was rendered that way, in a sandbox with no network access to the media APIs. With a free Pexels key it uses real stock footage.

**Tools and AI used**
- Python 3, ffmpeg (xfade, zoompan, libass subtitles, sidechaincompress, loudnorm), Pillow, numpy
- LLM for the script: Claude, OpenAI or Gemini (whichever key is set), local Ollama, or Pollinations as a keyless fallback
- TTS: Microsoft Edge neural voices via edge-tts (free, gives word boundaries), with pico2wave, espeak-ng and macOS `say` as fallbacks
- Media: Pexels API, Pixabay API, Openverse API, Wikimedia Commons API
- I used Claude as a pair programmer while building it

**What I'd add next**
1. Let a vision model look at frames from the top 5 search results and pick the clip that actually matches the line being spoken, instead of trusting keyword search.
2. Forced alignment (whisperX) so captions are frame-accurate with any TTS, plus ElevenLabs as a premium voice option.
3. AI-generated b-roll (image or video models) for scenes that stock footage can't cover, with a consistent style or character across the video.
4. A small web UI and job queue (FastAPI plus a worker) so non-devs can submit topics, preview the script, swap a clip, and re-render one scene without redoing the whole video.
5. Auto-publishing to YouTube, TikTok and Instagram with an LLM-written title, description and hashtags, then pulling the analytics back in to learn which hooks perform.
