from __future__ import annotations

import math
from pathlib import Path

from .probe import probe
from .util import ensure_dir, grab_frame

import cv2
import numpy as np


def detect_shots(path, threshold: float = 27.0, min_seconds: float = 0.5) -> list:
    from scenedetect import ContentDetector, SceneManager, open_video

    info = probe(path)
    fps = (info.get("video") or {}).get("fps") or 30.0
    duration = info.get("duration") or 0.0

    video = open_video(str(path))
    manager = SceneManager()
    manager.add_detector(
        ContentDetector(threshold=float(threshold), min_scene_len=max(1, int(fps * min_seconds)))
    )
    manager.detect_scenes(video)
    scene_list = manager.get_scene_list()

    shots = []
    for i, (start, end) in enumerate(scene_list, 1):
        s = round(start.get_seconds(), 3)
        e = round(end.get_seconds(), 3)
        shots.append({"index": i, "start": s, "end": e, "dur": round(max(e - s, 0.0), 3)})

    if not shots:
        shots = [{"index": 1, "start": 0.0, "end": round(duration, 3), "dur": round(duration, 3)}]
    return shots


def _label(img, text: str) -> None:
    cv2.rectangle(img, (0, 0), (img.shape[1], 26), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


def contact_sheet(path, shots: list, dst, limit: int = 9, thumb_w: int = 320) -> Path:
    dst = Path(dst)
    ensure_dir(dst.parent)
    picked = shots
    if limit and len(shots) > limit:
        step = len(shots) / float(limit)
        picked = [shots[min(int(i * step), len(shots) - 1)] for i in range(limit)]

    thumbs = []
    tmp_dir = ensure_dir(dst.parent / "_tmp_frames")
    for shot in picked:
        mid = (shot["start"] + shot["end"]) / 2.0
        frame_path = tmp_dir / f"f{shot['index']:04d}.jpg"
        try:
            grab_frame(path, mid, frame_path, width=thumb_w)
            img = cv2.imread(str(frame_path))
        except Exception:
            img = None
        if img is None:
            img = np.zeros((int(thumb_w * 9 / 16), thumb_w, 3), dtype=np.uint8)
        img = cv2.resize(img, (thumb_w, int(thumb_w * 9 / 16)), interpolation=cv2.INTER_AREA)
        _label(img, f"{shot['index']:02d}  {shot['start']:.2f}-{shot['end']:.2f}s")
        thumbs.append(img)

    if not thumbs:
        raise RuntimeError("没有可用帧，无法生成联系表")

    cols = 3
    rows = math.ceil(len(thumbs) / cols)
    h, w = thumbs[0].shape[:2]
    sheet = np.full((rows * h, cols * w, 3), 24, dtype=np.uint8)
    for i, img in enumerate(thumbs):
        r, c = divmod(i, cols)
        sheet[r * h:(r + 1) * h, c * w:(c + 1) * w] = img[:h, :w]
    cv2.imwrite(str(dst), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    for f in tmp_dir.glob("*.jpg"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        tmp_dir.rmdir()
    except OSError:
        pass
    return dst


def write_otio(path, shots: list, dst) -> Path:
    import opentimelineio as otio

    dst = Path(dst)
    timeline = otio.schema.Timeline(name=Path(path).stem)
    track = otio.schema.Track(kind=otio.schema.TrackKind.Video)
    for shot in shots:
        clip = otio.schema.Clip(
            name=f"shot{shot['index']:02d}",
            source_range=otio.opentime.TimeRange(
                otio.opentime.RationalTime(shot["start"], 1),
                otio.opentime.RationalTime(shot["dur"], 1),
            ),
            media_reference=otio.schema.ExternalReference(target_url=str(Path(path).resolve())),
        )
        track.append(clip)
    timeline.tracks.append(track)
    otio.adapters.write_to_file(timeline, str(dst))
    return dst
