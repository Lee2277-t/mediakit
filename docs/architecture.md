# Architecture

`mediakit` is a thin orchestration layer. It does not reimplement media
processing; it calls mature tools and turns their results into JSON that an
agent can reason about.

```
            ┌─────────────┐
 video ───▶ │ probe/shots │ ──▶ shots.json + contact.jpg + timeline.otio
            └─────────────┘
                        │
                        ▼
            ┌─────────────┐
            │  shotcard   │ ──▶ brightness / saturation / colors / motion (+ VLM)
            └─────────────┘
                        │
 audio ───▶ ┌─────────────┐
            │    music    │ ──▶ bpm / beats / downbeats / key / sections / chords
            └─────────────┘
                        │
 speech ──▶ ┌─────────────┐
            │ subs / ocr  │ ──▶ srt / ass (+ karaoke) / ocr.json / lyrics.lrc
            └─────────────┘
                        │
 plan.json ▶┌─────────────┐
            │    edit     │ ──▶ final.mp4  (xfade + acrossfade + burned subs)
            └─────────────┘
 music+dir ▶┌─────────────┐
            │    auto     │ ──▶ montage.mp4 + plan.json
            └─────────────┘
```

## Modules

| Module | Responsibility | Optional dependency |
|---|---|---|
| `config.py` | tool discovery, env overrides, local model endpoints | — |
| `util.py` | ffmpeg wrappers, JSON output, path helpers | — |
| `probe.py` | ffprobe JSON with a PyAV fallback | `av` |
| `shots.py` | scene detection, contact sheet, OTIO export | `scenedetect`, `opencv-python`, `opentimelineio` |
| `shotcard.py` | per-shot pixel statistics and optical flow | `opencv-python` |
| `subs.py` | transcription, line breaking, ASS/SRT, karaoke, QA | `faster-whisper`, `pysubs2`, `opencc` |
| `ocr.py` | frame sampling + RapidOCR + segment merge | `rapidocr-onnxruntime` |
| `index.py` | CLIP frame embeddings and text search | `open-clip-torch` |
| `vlm.py` | local Ollama vision calls for shot descriptions | — (HTTP) |
| `music.py` | tempo/beats/key/sections/chords/melody | `librosa`, `scipy` |
| `lyrics.py` | vocal separation + lyric transcription + LRC | `audio-separator` |
| `dub.py` | SAPI speech synthesis + timeline mixing | `pywin32` (Windows) |
| `watch.py` | one-shot "video card" bundle | as above |
| `auto.py` | beat-synced montage planning and selection | — |
| `edit.py` | plan renderer (concat/xfade/acrossfade/subtitles) | `pysubs2` |
| `polish.py` | VideoCaptioner bridge (LLM line breaking/translation) | external exe |
| `mcp_server.py` | MCP tools over stdio | `mcp` |

## Data contracts

Every command returns a dict; `--json` prints it verbatim.

- `shots`: `{path, duration, count, shots:[{index,start,end,dur}]}`
- `subs`: `{path, language, lines, files:{srt,ass}, preview:[...]}`
- `music`: `{tempo_bpm, beats[], downbeats[], key{...}, sections[], chords[]?}`
- `edit` plan: `{size, fps, clips[{src,in,out}], subtitle?, music?, transition?, beat_sync?}`
- `auto`: `{out, segments, duration, cuts[], plan, stats{reused,clamped,filled}}`

## Design rules

1. **No silent success.** When a step cannot do what was asked (no audio,
   clip too short, model missing) it is recorded in the result instead of
   being dropped.
2. **Heavy imports are lazy.** `mk probe` does not import torch.
3. **Local first.** Ollama, SAPI and ffmpeg are local; cloud keys are optional
   and never required for the core path.
4. **Paths never hard-coded.** Executables come from PATH or `MEDIAKIT_*`
   environment variables.
