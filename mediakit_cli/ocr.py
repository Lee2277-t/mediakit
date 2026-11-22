from __future__ import annotations

import re
import tempfile
from pathlib import Path

from .probe import probe
from .util import ensure_dir, ffmpeg

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def ocr_image(path, min_score: float = 0.5) -> list:
    out = _engine()(str(path))
    rows = out[0] if isinstance(out, tuple) else out
    items = []
    for row in rows or []:
        try:
            box, text, score = row[0], row[1], float(row[2])
        except Exception:
            continue
        if score < min_score or not str(text).strip():
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append(
            {
                "text": str(text).strip(),
                "score": round(score, 3),
                "box": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))],
            }
        )
    items.sort(key=lambda x: (x["box"][1], x["box"][0]))
    return items


def _norm(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;]+", "", text or "")


def ocr_video(
    path,
    every: float = 2.0,
    max_frames: int = 60,
    min_score: float = 0.5,
    progress=None,
) -> dict:
    note = progress or (lambda *_: None)
    info = probe(path)
    duration = float(info.get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("读不到视频时长")

    every = max(float(every), 0.2)
    tmp = Path(tempfile.mkdtemp(prefix="mkocr_"))
    try:
        ffmpeg(
            "-i", path,
            "-vf", f"fps={1.0 / every:.6f}",
            "-frames:v", str(max_frames),
            "-q:v", "3",
            str(tmp / "%05d.jpg"),
        )
        frames = sorted(tmp.glob("*.jpg"))
        note(f"抽了 {len(frames)} 帧（每 {every}s）")
        result_frames = []
        for i, f in enumerate(frames):
            t = round(i * every, 3)
            texts = ocr_image(f, min_score=min_score)
            result_frames.append({"t": t, "texts": texts})
            if i % 10 == 0:
                note(f"OCR {i + 1}/{len(frames)}")
    finally:
        for f in tmp.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            tmp.rmdir()
        except OSError:
            pass

    segments = []
    for item in result_frames:
        text = " ".join(x["text"] for x in item["texts"]).strip()
        if not text:
            continue
        start = item["t"]
        end = min(start + every, duration)
        if segments and _norm(segments[-1]["text"]) == _norm(text):
            segments[-1]["end"] = round(end, 3)
        else:
            segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})

    return {
        "path": str(Path(path).resolve()),
        "duration": round(duration, 3),
        "every": every,
        "frames": result_frames,
        "segments": segments,
        "engine": "RapidOCR",
    }


def to_lines(segments: list) -> list:
    return [
        {"text": s["text"], "start": s["start"], "end": s["end"], "words": []}
        for s in segments
        if s.get("text")
    ]


def write_ocr_srt(result: dict, out_path) -> str:
    from .subs import write_subtitles

    out = Path(out_path).resolve()
    ensure_dir(out.parent)
    write_subtitles(to_lines(result["segments"]), out.parent, stem=out.stem, formats=("srt",))
    return str(out)
