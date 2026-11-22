"""Compare lyric transcription against a reference subtitle file.

Reports both line-level similarity (matched by time overlap) and a line-break
independent character error rate (CER) over the whole window.

Example:
  python tools/eval_lyrics.py --media song.mp4 --reference lyrics.ass \
      --start 60 --end 100 --lang ja --models small medium
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pysubs2  # noqa: E402

from mediakit_cli.subs import build_lines, transcribe  # noqa: E402
from mediakit_cli.util import ffmpeg  # noqa: E402


def norm(text: str) -> str:
    return re.sub(r"[\s、。，．！？!?・…「」『』（）()]+", "", text or "")


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def reference_lines(path: Path, start: float, end: float, style: str | None) -> list:
    subs = pysubs2.load(str(path))
    out = []
    for ev in subs:
        if style and ev.style != style:
            continue
        s, e = ev.start / 1000.0, ev.end / 1000.0
        if s < start or e > end + 0.5:
            continue
        out.append({"start": s - start, "end": e - start, "text": ev.plaintext.replace("\\N", "")})
    return out


def compare(gt: list, asr: list) -> list:
    rows = []
    for g in gt:
        best, overlap = None, 0.0
        for a in asr:
            ov = max(0.0, min(g["end"], a["end"]) - max(g["start"], a["start"]))
            if ov > overlap:
                best, overlap = a, ov
        ratio = (
            difflib.SequenceMatcher(None, norm(best["text"]), norm(g["text"])).ratio()
            if best and overlap > 0.3
            else 0.0
        )
        rows.append({"gt": g["text"], "asr": best["text"] if best else "", "ratio": round(ratio, 3)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--media", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--lang", default=None)
    ap.add_argument("--models", nargs="+", default=["small"])
    ap.add_argument("--style", default=None, help="only events with this ASS style")
    ap.add_argument("--vocals", default=None, help="pre-separated vocals to reuse")
    ap.add_argument("--skip-mix", action="store_true")
    ap.add_argument("--out", default="eval-lyrics.json")
    args = ap.parse_args()

    work = Path(args.out).parent
    work.mkdir(parents=True, exist_ok=True)
    end = args.end or (args.start + 40.0)
    wav = work / "excerpt.wav"
    ffmpeg("-ss", str(args.start), "-t", str(end - args.start), "-i", args.media,
           "-vn", "-ac", "1", "-ar", "16000", str(wav))

    gt = reference_lines(Path(args.reference), args.start, end, args.style)
    print(f"reference lines: {len(gt)}")
    report = {"window": [args.start, end], "lines": len(gt), "variants": {}}

    sources = []
    if not args.skip_mix:
        sources.append(("mix", str(wav)))
    if args.vocals:
        sources.append(("vocals", args.vocals))

    for model in args.models:
        for name, src in sources:
            asr = transcribe(src, language=args.lang, model=model)
            lines = build_lines(asr, max_chars=20.0, max_dur=8.0, pause=0.4, min_chars=2.0)
            rows = compare(gt, lines)
            mean = sum(r["ratio"] for r in rows) / max(len(rows), 1)
            ref_text = norm("".join(r["gt"] for r in rows))
            hyp_text = norm("".join(r["asr"] for r in rows))
            cer = levenshtein(ref_text, hyp_text) / max(len(ref_text), 1)
            report["variants"][f"{name}-{model}"] = {
                "mean_line_ratio": round(mean, 3),
                "cer": round(cer, 3),
                "rows": rows,
            }
            print(f"[{name}/{model}] line-ratio={mean:.1%}  CER={cer:.1%}")

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
