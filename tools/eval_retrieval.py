"""Retrieval recall benchmark on synthetic solid-color segments.

Usage: python tools/eval_retrieval.py [work_dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mediakit.index import build_index, search  # noqa: E402
from mediakit.util import ffmpeg  # noqa: E402

WORK = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "eval-retrieval"
SEG = 5.0
COLORS = [
    ("red", "a plain red background", "red"),
    ("orange", "a plain orange background", "orange"),
    ("yellow", "a plain yellow background", "yellow"),
    ("green", "a plain green background", "green"),
    ("blue", "a plain blue background", "blue"),
    ("purple", "a plain purple background", "purple"),
    ("white", "a plain white background", "white"),
    ("black", "a plain black background", "black darkness"),
]


def make_video(path: Path) -> None:
    n = len(COLORS)
    args = []
    for color, _, _ in COLORS:
        args += ["-f", "lavfi", "-i", f"color=c={color}:s=320x180:d={SEG}"]
    filt = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    ffmpeg(*args, "-filter_complex", filt, "-map", "[v]", "-pix_fmt", "yuv420p", str(path))


def run(idx: Path, phrasing: int) -> list:
    rows = []
    for i, item in enumerate(COLORS):
        res = search(str(idx), item[phrasing], topk=3)
        start, end = i * SEG, (i + 1) * SEG
        top = res["hits"][0]
        rows.append(
            {
                "query": item[phrasing],
                "expect": [start, end],
                "top1": top["t"],
                "hit@1": start <= top["t"] < end,
                "hit@3": any(start <= h["t"] < end for h in res["hits"]),
            }
        )
    return rows


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    video = WORK / "eval.mp4"
    if not video.exists():
        print("generating test video...")
        make_video(video)

    idx = WORK / "index"
    print("building index...")
    build_index(str(video), str(idx), every=2.5, max_frames=64, progress=lambda m: None)

    report = {"segments": len(COLORS), "segment_seconds": SEG, "phrasings": {}}
    for name, phrasing in (("descriptive", 1), ("short", 2)):
        rows = run(idx, phrasing)
        r1 = sum(r["hit@1"] for r in rows) / len(rows)
        r3 = sum(r["hit@3"] for r in rows) / len(rows)
        report["phrasings"][name] = {"recall@1": round(r1, 3), "recall@3": round(r3, 3), "rows": rows}
        print(f"[{name}] recall@1={r1:.0%} recall@3={r3:.0%}")

    (WORK / "eval.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
