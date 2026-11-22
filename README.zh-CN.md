# mediakit

**一条 CLI、17 个命令、统一 JSON 输出——给需要"看视频、听音乐、做字幕、剪片子"的 agent 用。**

`mediakit` 是一层薄薄的编排：不重写解码、ASR、镜头检测，而是调用成熟工具，
把结果整理成 agent 能直接读的结构化数据；同时附带 MCP server，可以挂到任何 MCP 客户端。

```
$ mk watch clip.mp4 --out work/clip --lang zh --ocr
语言 zh · 4 镜头 · 12 关键帧 · 转写 8 段 · 画面文字 2 条
$ mk search work/clip/index "穿黑裙子的女孩在草地上" --top 3
   42.50s  score 0.311  ...
```

[English README](README.md)

## 为什么还要包一层

上游工具各自都很强，但输出是给人看的：PySceneDetect 打一张表，Whisper 吐一整行，
CLIP 只给张量。agent 需要的正好相反：短小的可组合命令、稳定的 JSON、不需要 GUI。

| 上游 | 它负责 | `mk` 补的 |
|---|---|---|
| PySceneDetect | 镜头边界 | `contact.jpg`、`shots.json`、OTIO 导出 |
| faster-whisper | 分段 + 词时间 | 按停顿断句、按显示宽度收行、繁转简、卡拉OK、QA |
| ffmpeg | 编解码/切/烧 | 一份 plan 文件、xfade + acrossfade、字幕尺寸重标定 |
| RapidOCR | 文字框 | 抽帧、去重、合成 SRT |
| CLIP | 向量 | 建索引 / 搜索命令 + 缩略图 |
| librosa | BPM/拍 | tempogram 先验纠速、段落、和弦、旋律 |
| VideoCaptioner | LLM 润色字幕 | 一条命令、本机 Ollama、双语输出 |

## 安装

```bash
pip install "mediakit-cli[all]"     # 全量
pip install mediakit-cli            # 只装核心（probe / edit / auto 的计划逻辑）
```

需要 `ffmpeg` 在 `PATH` 上（或设置 `MEDIAKIT_FFMPEG`）。可选分组：

| extra | 解锁 | 依赖 |
|---|---|---|
| `asr` | `subs`、`watch`、`lyrics` | faster-whisper |
| `vision` | `shots`、`shotcard`、`ocr` | OpenCV、PySceneDetect、RapidOCR |
| `music` | `music` | librosa |
| `search` | `index`、`search` | open_clip + ViT-B-32 权重 |
| `separate` | `lyrics --separate` | audio-separator |
| `mcp` | `mediakit-mcp` | MCP SDK |
| `windows` | `dub`、`voices` | pywin32 + SAPI |
| `timeline` | `shots --otio` | OpenTimelineIO |

环境变量：`MEDIAKIT_FFMPEG`、`MEDIAKIT_AUDIO_SEPARATOR`、`MEDIAKIT_VIDEOCAPTIONER`、
`MEDIAKIT_OLLAMA_BASE`、`MEDIAKIT_VLM_MODEL`。

## 命令一览

```bash
# 看
mk probe    a.mp4
mk watch    a.mp4 --out work/a --lang zh --ocr
mk frames   a.mp4 --n 12 --out work/a/frames
mk ocr      a.mp4 --out work/a/ocr --every 2
mk index    a.mp4 --out work/a/index
mk search   work/a/index "草地上奔跑的女孩"

# 听
mk music    song.mp3 --chords --melody --engine beat-this
mk lyrics   song.mp3 --out work/lyrics --lang ja

# 拆画面
mk shots    a.mp4 --out work/a --otio
mk shotcard a.mp4 --out work/a/card --vlm

# 字幕
mk subs     a.mp4 --lang zh --out work/a --size 1080x1920 --max-chars 12 --karaoke --qa
mk subqa    work/a/subs.srt
mk polish   work/a/subs.srt --out work/a/polished.srt
mk voices
mk dub      a.mp4 --srt work/a/subs.srt --out work/dub.mp4 --voice Huihui --mix-original

# 剪
mk edit     work/plan.json --out work/final.mp4
mk auto     --music bgm.mp3 --src footage --out work/mv.mp4 --transition fade
```

所有命令都支持 `--json`；不加就输出人看的小结。

### `mk auto`：卡点混剪

分析歌曲 → 按段落能量决定每段"几拍一切"（安静段切得慢、高潮切得快）→
从素材夹挑镜头 → 切点吸到拍上 → 渲染，视频用 `xfade`、音频用 `acrossfade`。

```bash
mk auto --music bgm.mp3 --src footage --out mv.mp4 \
        --size 1080x1920 --fit crop --transition fade --seed 7
mk auto --music bgm.mp3 --src footage --out mv.mp4 --plan-only   # 只出计划
```

## MCP

```json
{
  "mcpServers": {
    "mediakit": { "command": "mediakit-mcp" }
  }
}
```

12 个工具：`probe`、`shots`、`music`、`subs`、`ocr`、`shotcard`、`index`、
`search`、`lyrics`、`dub`、`edit`、`auto`。

## 实测数据（不是拍脑袋）

下表来自本机 CPU 和 `tools/` 里的评测脚本，都是小样本，不当排行榜。

| 项目 | 结果 |
|---|---|
| 镜头切分 | 三段硬切准确切在 4.00s / 8.00s |
| 字幕 | 16.5 秒中文语音 → 9 行，繁转简，行宽受控 |
| 卡拉OK | 每个词带 `\kf`；0.2 秒时 65% 字幕像素仍是未唱色 |
| OCR | 把烧进画面的字幕读回「大家晚上好。」并合成 SRT |
| 检索（合成 8 段） | recall@1 描述句 75% / 单词 88%，recall@3 100% |
| 检索（真实 8 段） | recall@1 75%，recall@3 100% |
| 歌词 CER（对标准字幕） | 混音 89.7% → 人声 60.3%（small）→ **54.4%（medium）** |
| 节拍纠错 | librosa 默认 103.36 BPM 是 4:3 误判，tempogram 先验后 80.75 |
| 混剪 | 20 秒配乐出 7 段；加 6×0.25s 叠化后 18.50s |
| 音频交叉淡化 | 3×2s + 0.25s + keep_audio → 5.50s，音轨保留 |
| 配音 | 9 句 → 18.60s，与原片等长，2ch/48kHz |

## 已知边界

- 检索评测只有 8 段/8 clip，CLIP 对措辞敏感，纯白/纯黑这类低信息画面会错。
- 歌声转写仍然难：54% CER 已经是较好的情况。
- `dub` 用 Windows SAPI，机器人音；长句最多加速 2×。
- VLM 镜头描述只在少量帧上验证过。
- `beat_this` 与 librosa 常差几 BPM；现在用 tempogram 锚定速度，但没有证明哪个在音乐上更对。
- 镜头检测默认只对硬切稳，渐变转场会漏。

## 目录

```
mediakit/        包（17 个模块 + MCP server）
tools/           评测：检索、歌词 CER、节拍
docs/            架构与数据契约
examples/        示例 edit 计划
tests/           纯逻辑单元测试
```

## 许可

MIT
