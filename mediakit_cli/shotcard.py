from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

from .probe import probe
from .shots import detect_shots
from .util import ensure_dir


def _frames_at(cap, times: list) -> list:
    out = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(t, 0) * 1000.0)
        ok, frame = cap.read()
        if not ok:
            continue
        out.append((t, cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)))
    return out


def _dominant_colors(frame_bgr, k: int = 3) -> list:
    small = cv2.resize(frame_bgr, (80, 45), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(np.float32)
    if len(pixels) < k:
        return []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)
    colors = []
    for idx in order:
        b, g, r = [int(round(v)) for v in centers[idx]]
        colors.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "ratio": round(float(counts[idx]) / counts.sum(), 3)})
    return colors


def _motion(frames: list) -> dict:
    if len(frames) < 2:
        return {"magnitude": 0.0, "angle": 0.0, "label": "static"}
    mags, angles = [], []
    prev = cv2.cvtColor(frames[0][1], cv2.COLOR_BGR2GRAY)
    for _, frame in frames[1:]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(prev, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        dx, dy = flow[..., 0], flow[..., 1]
        mag = float(np.mean(np.sqrt(dx * dx + dy * dy)))
        ang = float(math.degrees(math.atan2(float(np.mean(dy)), float(np.mean(dx)))))
        mags.append(mag)
        angles.append(ang)
        prev = gray
    m = float(np.mean(mags)) if mags else 0.0
    label = "static" if m < 0.35 else ("slow" if m < 1.6 else "fast")
    return {"magnitude": round(m, 2), "angle": round(float(np.mean(angles)), 1), "label": label}


def analyze(
    path,
    out_dir,
    max_shots: int | None = None,
    samples: int = 5,
    use_vlm: bool = False,
    vlm_max: int = 12,
    vlm_model: str = "qwen3-vl:4b-instruct",
    progress=None,
) -> dict:
    note = progress or (lambda *_: None)
    info = probe(path)
    shots = detect_shots(path)
    if max_shots:
        shots = shots[:max_shots]
    out = ensure_dir(out_dir)
    thumb_dir = ensure_dir(out / "shots")
    cap = cv2.VideoCapture(str(path))
    results = []
    try:
        for shot in shots:
            start, end = shot["start"], shot["end"]
            span = max(end - start, 0.05)
            times = [start + span * (i + 0.5) / samples for i in range(samples)]
            frames = _frames_at(cap, times)
            if not frames:
                continue
            mid = frames[len(frames) // 2][1]
            hsv = cv2.cvtColor(mid, cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            thumb_path = thumb_dir / f"shot{shot['index']:03d}.jpg"
            cv2.imwrite(str(thumb_path), cv2.resize(mid, (640, 360)), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            entry = {
                "index": shot["index"],
                "start": start,
                "end": end,
                "dur": round(span, 3),
                "brightness": round(float(v.mean()) / 255.0, 3),
                "saturation": round(float(s.mean()) / 255.0, 3),
                "contrast": round(float(v.std()) / 255.0, 3),
                "colors": _dominant_colors(mid),
                "motion": _motion(frames),
                "thumb": str(thumb_path),
            }
            if use_vlm and len(results) < vlm_max:
                from .vlm import describe_image

                try:
                    entry["vlm"] = describe_image(thumb_path, model=vlm_model)
                    note(f"shot {shot['index']}: {entry['vlm'].get('caption', entry['vlm'].get('raw', ''))}")
                except Exception as exc:
                    entry["vlm"] = {"error": str(exc)}
                    note(f"shot {shot['index']} VLM 失败: {exc}")
            results.append(entry)
            note(f"shot {shot['index']}/{len(shots)}")
    finally:
        cap.release()

    card = {
        "path": str(Path(path).resolve()),
        "duration": info.get("duration"),
        "count": len(results),
        "summary": {
            "avg_brightness": round(float(np.mean([r["brightness"] for r in results])), 3) if results else 0,
            "avg_saturation": round(float(np.mean([r["saturation"] for r in results])), 3) if results else 0,
            "static_shots": sum(1 for r in results if r["motion"]["label"] == "static"),
            "moving_shots": sum(1 for r in results if r["motion"]["label"] != "static"),
        },
        "shots": results,
        "note": "数值来自像素统计；景别/机位/情绪这类语义需要多模态模型看 shots/*.jpg",
    }
    (out / "shotcard.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return card
