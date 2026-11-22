from __future__ import annotations

import subprocess
from pathlib import Path

from .config import find_tool
from .subs import build_lines, transcribe, write_subtitles
from .util import ensure_dir, media_path


def separate_vocals(song, out_dir, model: str | None = None, progress=None) -> Path:
    note = progress or (lambda *_: None)
    out = ensure_dir(out_dir)
    exe = find_tool("audio-separator", "MEDIAKIT_AUDIO_SEPARATOR")
    if not exe:
        raise RuntimeError(
            "找不到 audio-separator：pip install audio-separator，或设置 MEDIAKIT_AUDIO_SEPARATOR"
        )
    cmd = [
        exe,
        str(song),
        "--output_dir", str(out),
        "--output_format", "wav",
    ]
    if model:
        cmd += ["--model_filename", model]
    note("分轨中（首次会下载模型）")
    p = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=7200
    )
    vocals = sorted(out.glob("*Vocals*.wav"))
    if not vocals:
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError("没有产出人声轨: " + " | ".join(tail))
    return vocals[0]


def _lrc_time(sec: float) -> str:
    m, s = divmod(max(sec, 0.0), 60)
    return f"[{int(m):02d}:{s:05.2f}]"


def write_lrc(lines: list, path) -> Path:
    path = Path(path)
    ensure_dir(path.parent)
    body = "\n".join(f"{_lrc_time(ln['start'])}{ln['text']}" for ln in lines)
    path.write_text(body + "\n", encoding="utf-8")
    return path


def make_lyrics(
    song,
    out_dir,
    lang: str | None = None,
    model: str = "small",
    separate: bool = True,
    max_chars: float = 18.0,
    pause: float = 0.35,
    karaoke: bool = True,
    resolution=(1920, 1080),
    sep_model: str | None = None,
    progress=None,
) -> dict:
    note_impl = progress or (lambda *_: None)
    note = note_impl
    src = media_path(song)
    out = ensure_dir(out_dir)

    audio = src
    vocals = None
    if separate:
        vocals = separate_vocals(src, out / "stems", model=sep_model, progress=note_impl)
        audio = vocals
        note_impl(f"人声: {vocals.name}")

    asr = transcribe(audio, language=lang, model=model)
    lines = build_lines(asr, max_chars=max_chars, max_dur=8.0, pause=pause, min_chars=2.0)
    files = write_subtitles(
        lines, out, stem="lyrics", formats=("srt", "ass"), resolution=resolution, karaoke=karaoke
    )
    files["lrc"] = str(write_lrc(lines, out / "lyrics.lrc"))

    return {
        "song": str(src),
        "vocals": str(vocals) if vocals else None,
        "language": asr["language"],
        "duration": asr["duration"],
        "words": len(asr["words"]),
        "lines": len(lines),
        "files": files,
        "preview": lines[:6],
    }
