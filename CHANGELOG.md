# Changelog

## 0.1.0 — 2026-11-22

First public release.

- 17 CLI subcommands: `probe`, `shots`, `frames`, `shotcard`, `ocr`, `index`,
  `search`, `watch`, `subs`, `subqa`, `polish`, `voices`, `dub`, `lyrics`,
  `music`, `edit`, `auto`.
- MCP server (`mediakit-mcp`) exposing 12 tools over stdio.
- Pause-aware subtitle line breaking with word timestamps, karaoke `\kf`
  output, PlayRes calibration and a reading-speed QA pass.
- Beat-synced montage generator with section-aware pacing, `xfade` video
  transitions and `acrossfade` audio transitions.
- Local VLM shot descriptions, CLIP frame search, SAPI dubbing,
  vocal-separation lyric pipeline.
- Benchmarks in `tools/` for retrieval recall, lyric CER and beat tracking.

Known limitations are listed in the README; they are measured, not assumed.
