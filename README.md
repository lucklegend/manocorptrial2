# vidgen: topic in, mp4 out

A prototype automated video generator. You give it a topic, and it writes the script, records the voiceover, finds footage, adds animated captions and music, and renders a ready-to-post mp4 (vertical 1080x1920 by default, so it's ready for Shorts, Reels and TikTok).

```bash
python -m vidgen "why the ocean is salty"
```

## What it does on its own

| Step | What happens | Providers (tried in order) |
|---|---|---|
| 1. Script | LLM writes a hook, 4 to 8 scenes and a call to action. Each scene gets narration, a stock-footage search query and a short on-screen headline. The output is strict JSON. | Claude, OpenAI, Gemini, local Ollama, Pollinations (free, no key), then an offline template |
| 2. Voiceover | Each scene's narration becomes speech, along with **per-word timestamps** for the captions | edge-tts (free neural voices, no key), macOS `say`, pico2wave, espeak-ng |
| 3. Visuals | Searches stock footage per scene. It never reuses a clip, tries shorter queries if nothing matches, and skips any source that's down. | Pexels video, Pixabay video, Pexels photo, Pixabay photo, Openverse (CC, no key), Wikimedia Commons (CC, no key), then generated art |
| 4. Motion | Video clips are cropped to fit the frame and color-graded. Stills get a Ken Burns zoom/pan that alternates direction between scenes. Scenes are joined with crossfades and slide transitions. | ffmpeg (`zoompan`, `xfade`) |
| 5. Captions | Short-form style: 1 to 3 words on screen, with the spoken word highlighted and a little pop on each new group. A headline badge appears at the top of each scene. Also writes an `.srt` file. | ASS subtitles burned in with libass, using the bundled Inter font |
| 6. Music | Uses your track or folder if you give one. Otherwise it **composes a royalty-free lo-fi bed** (chords, bass, arpeggio, soft drums) with numpy, so there's no licensing risk. | numpy synth |
| 7. Mix and render | The voice is loudness-normalised and the music is **side-chain ducked** under it. Output is H.264/AAC at -15 LUFS with faststart. | ffmpeg |
| 8. Extras | `thumbnail.jpg` with the title, `credits.txt` (attribution for every asset), `script.json`, and `report.json` (which provider handled each step and how long the render took) | Pillow |

Every step has a free or offline fallback, so **it always finishes with an mp4, even with no API keys and no internet.** Keys only make the result better.

## Setup

Needs Python 3.9+ and ffmpeg.

```bash
# macOS:   brew install ffmpeg
# Ubuntu:  sudo apt install ffmpeg            (optional offline voice: libttspico-utils)
# Windows: winget install ffmpeg

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # optional: paste in any keys you have
```

### API keys (all optional)

| Key | What it unlocks | Cost |
|---|---|---|
| `PEXELS_API_KEY` | Real stock **video** and photos (the biggest quality jump) | Free: pexels.com/api |
| `PIXABAY_API_KEY` | A second stock video and photo library | Free: pixabay.com/api/docs |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | Topic-specific scripts written by an LLM (Gemini has a free tier) | Pay-as-you-go or free tier |

No key is needed for the neural voice (edge-tts), the CC photos (Openverse and Wikimedia), or the music.

### Local LLM with Ollama (free, no key, works offline)

[Ollama](https://ollama.com) runs an LLM on your own machine, so you get topic-specific scripts with no API key, no usage limits and no internet. vidgen tries it automatically whenever an Ollama server is running at `localhost:11434`.

1. Install Ollama from [ollama.com/download](https://ollama.com/download). On Windows and macOS it runs in the background after installing (look for the llama icon in the tray or menu bar). On Linux, or if it isn't running, start it with `ollama serve` in a separate terminal.
2. Download the model vidgen uses by default (about 4.9 GB, needs about 8 GB of RAM):

   ```bash
   ollama pull llama3.1
   ```

   On a machine with less memory, use a smaller model and point vidgen at it in `.env`:

   ```bash
   ollama pull llama3.2                 # about 2 GB
   # in .env: VIDGEN_OLLAMA_MODEL=llama3.2
   ```

3. Check the server is up. `curl http://localhost:11434` should print `Ollama is running`, and `ollama list` should show the model.
4. Run vidgen as usual. To make sure Ollama writes the script even when other LLM keys are set, force it:

   ```bash
   python -m vidgen "why the ocean is salty" --llm ollama
   ```

Notes:

- Hosted LLMs come first in the provider order. If `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GEMINI_API_KEY` is set, that provider is used and Ollama only runs when it fails. Leave them empty or pass `--llm ollama` to always use the local model.
- The first request after Ollama starts is slow (the model has to load into memory). Later runs take a few seconds per script on a GPU, longer on CPU only.
- Use `OLLAMA_HOST` in `.env` if the server runs on another machine or port, for example `OLLAMA_HOST=http://192.168.1.20:11434`.
- If a run logs `script: ollama failed`, the server isn't running or the model hasn't been pulled. Check with steps 1 and 3.

## Usage

```bash
python -m vidgen "how bees make honey"                    # 60s vertical
python -m vidgen "the history of coffee" -d 90 -f landscape
python -m vidgen "black holes" --music ~/Music/royalty-free/   # pick a track from a folder
python -m vidgen "x" --script examples/ocean-salty.json      # skip the LLM, use your own script
python -m vidgen "black holes" --llm ollama                  # script from your local Ollama model
python -m vidgen "black holes" --offline --llm ollama --tts pico   # fully offline (pico2wave or espeak for the voice)
```

Each run creates its own output folder:

```
output/20261028-234541-why-the-ocean-is-salty/
  why-is-the-ocean-salty.mp4   final video
  thumbnail.jpg                 cover image with the title
  captions.srt                  separate caption track for uploading
  script.json                   the script that was used
  credits.txt                   attribution for every asset
  report.json                   which provider did each step, plus timings
  work/                         intermediate files (scene clips, voice wavs, .ass, filtergraph)
```

## About the sample video

`sample/why-is-the-ocean-salty.mp4` was rendered in a sandbox that had **no internet access to the stock or TTS APIs and no API keys**. So it shows the full fallback path:

- the script came from `examples/ocean-salty.json` (the `--script` option), because no LLM key was available
- the voice is offline pico2wave, not the edge-tts neural voice
- the visuals are generated art, because Pexels, Pixabay, Openverse and Wikimedia were all unreachable
- the music, captions, headlines, transitions, ducking and thumbnail are exactly what you get in every run

With a Pexels key and a normal internet connection, the same command gives real stock footage and a natural neural voice.

## Code map

```
vidgen/
  cli.py        argument parsing and .env loading
  pipeline.py   orchestration, thumbnail, report
  script.py     LLM providers, prompt, JSON validation, offline template
  tts.py        TTS engines and word-timing estimation
  media.py      stock search/download, dedupe, dead-source skipping, generated art
  captions.py   ASS word-highlight captions, headlines, SRT
  music.py      procedural lo-fi composer, or a user track
  assemble.py   timeline maths, per-scene render, xfade chain, audio mix
  fonts/        Inter (SIL OFL)
```

## Known limits

- Without edge-tts, word timings are estimated from syllables, so captions can drift slightly. Forced alignment (whisperX) would fix that.
- Stock search is keyword-based. Picking the best clip from the results is the next big improvement (see TICKET.md).
- The `zoompan` render is CPU-bound. A 60 second video takes about 1.5 minutes on 4 cores.
