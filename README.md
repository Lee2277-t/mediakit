# mediakit

**One CLI, 17 commands, JSON out — for agents that need to watch, listen, subtitle and cut.**

`mediakit` is a thin orchestration layer over mature media tools. It does not
reimplement decoding, ASR or scene detection; it calls them and returns
structured results an agent can reason about, plus an MCP server so the whole
toolkit can be attached to any MCP client.

```
$ mk watch clip.mp4 --out work/clip --lang zh --ocr
语言 zh · 4 镜头 · 12 关键帧 · 转写 8 段 · 画面文字 2 条
$ mk search work/clip/index "穿黑裙子的女孩在草地上" --top 3
   42.50s  score 0.311  ...
```

[中文说明](README.zh-CN.md)

## Why another wrapper?

Most tools are excellent at one step and then stop: PySceneDetect prints a
table, Whisper emits one long line, CLIP libraries return tensors. An agent
needs the opposite: short, composable commands with stable JSON, and no GUI.

| Upstream | What it does | What `mk` adds |
|---|---|---|
| PySceneDetect | shot boundaries | `contact.jpg`, `shots.json`, OTIO export |
| faster-whisper | segments + words | pause-based line breaking, width limits, 繁→简, karaoke, QA |
| ffmpeg | encode/cut/burn | one plan file, xfade + acrossfade, subtitle rescaling |
| RapidOCR | text boxes | frame sampling, de-dup, SRT output |
| CLIP | embeddings | index/search commands with thumbnails |
| librosa | tempo/beats | tempogram tempo prior, sections, chords, melody |
| VideoCaptioner | LLM subtitle polish | one command, local Ollama, bilingual output |

## Install

```bash
pip install "mediakit-cli[all]"     # everything
pip install mediakit-cli            # core only: probe, edit, auto, plan logic
```

`ffmpeg` must be on `PATH` (or set `MEDIAKIT_FFMPEG`). Optional groups:

| Extra | Enables | Install |
|---|---|---|
| `asr` | `subs`, `watch`, `lyrics` | `faster-whisper` |
| `vision` | `shots`, `shotcard`, `ocr` | OpenCV, PySceneDetect, RapidOCR |
| `music` | `music` | librosa |
| `search` | `index`, `search` | open_clip + ViT-B-32 weights |
| `separate` | `lyrics --separate` | audio-separator |
| `mcp` | `mediakit-mcp` | MCP SDK |
| `windows` | `dub`, `voices` | pywin32 + SAPI |
| `timeline` | `shots --otio` | OpenTimelineIO |

Environment overrides: `MEDIAKIT_FFMPEG`, `MEDIAKIT_AUDIO_SEPARATOR`,
`MEDIAKIT_VIDEOCAPTIONER`, `MEDIAKIT_OLLAMA_BASE`, `MEDIAKIT_VLM_MODEL`.

## Commands

```bash
# look
mk probe    a.mp4
mk watch    a.mp4 --out work/a --lang zh --ocr
mk frames   a.mp4 --n 12 --out work/a/frames
mk ocr      a.mp4 --out work/a/ocr --every 2
mk index    a.mp4 --out work/a/index
mk search   work/a/index "a girl running on grass"

# listen
mk music    song.mp3 --chords --melody --engine beat-this
mk lyrics   song.mp3 --out work/lyrics --lang ja

# dissect
mk shots    a.mp4 --out work/a --otio
mk shotcard a.mp4 --out work/a/card --vlm

# subtitle
mk subs     a.mp4 --lang zh --out work/a --size 1080x1920 --max-chars 12 --karaoke --qa
mk subqa    work/a/subs.srt
mk polish   work/a/subs.srt --out work/a/polished.srt
mk voices
mk dub      a.mp4 --srt work/a/subs.srt --out work/dub.mp4 --voice Huihui --mix-original

# cut
mk edit     work/plan.json --out work/final.mp4
mk auto     --music bgm.mp3 --src footage --out work/mv.mp4 --transition fade
```

Every command accepts `--json`. Without it you get a short human summary.

### `mk auto` — beat-synced montage

Analyzes the track, decides how many beats per cut per section (quiet sections
get longer cuts, loud ones shorter), picks shots from a folder, snaps cuts to
beats and renders `xfade` transitions with matching `acrossfade` audio.

```bash
mk auto --music bgm.mp3 --src footage --out mv.mp4 \
        --size 1080x1920 --fit crop --transition fade --seed 7
mk auto --music bgm.mp3 --src footage --out mv.mp4 --plan-only   # plan only
```

## MCP server

```json
{
  "mcpServers": {
    "mediakit": { "command": "mediakit-mcp" }
  }
}
```

12 tools: `probe`, `shots`, `music`, `subs`, `ocr`, `shotcard`, `index`,
`search`, `lyrics`, `dub`, `edit`, `auto`.

## Measured, not assumed

Numbers below were produced on a local machine (CPU) with the benchmark
scripts in `tools/`. They are small-sample results, not leaderboard claims.

| Area | Result |
|---|---|
| Shot detection | 3 hard cuts detected at exactly 4.00s / 8.00s |
| Subtitles | 16.5s Chinese speech → 9 lines, traditional→simplified, width capped |
| Karaoke | `\kf` per word; at 0.2s 65% of subtitle pixels still unsung color |
| OCR | read burned subtitles back as 「大家晚上好。」and merged into SRT |
| Retrieval (synthetic, 8 segments) | recall@1 75% descriptive / 88% short, recall@3 100% |
| Retrieval (real footage, 8 clips) | recall@1 75%, recall@3 100% |
| Lyric CER vs reference subs | mix 89.7% → vocals 60.3% (small) → **54.4% (medium)** |
| Tempo correction | librosa default 103.36 BPM was a 4:3 artifact; tempogram prior → 80.75 BPM |
| Montage | 7 segments from a 20s track; 18.50s with 6×0.25s fades |
| Audio crossfade | 3×2s clips + 0.25s fade + keep_audio → 5.50s, audio kept |
| Dubbing | 9 lines → 18.60s output, full length, 2ch/48kHz |

## Known limits

- Retrieval benchmarks are small (8 segments/clips) and CLIP is
  phrasing-sensitive; low-information frames (pure white/black) fail.
- Singing transcription is still hard: 54% CER is the good case.
- `dub` uses Windows SAPI — robotic, and long lines are time-compressed at most 2×.
- VLM shot descriptions were validated on a handful of frames.
- `beat_this` and librosa often disagree by a few BPM; the package now anchors
  tempo with a tempogram prior but does not prove which tracker is musically right.
- Transition handling assumes hard cuts when detecting shots.

## Layout

```
mediakit/        package (17 modules + MCP server)
tools/           benchmarks: retrieval, lyrics CER, tempo
docs/            architecture and data contracts
examples/        sample edit plan
tests/           unit tests for pure logic
```

## License

MIT
