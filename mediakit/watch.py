from __future__ import annotations

import json
import sys
from pathlib import Path

from .probe import has_audio, probe
from .shots import contact_sheet, detect_shots
from .subs import build_lines, transcribe, write_subtitles
from .util import ensure_dir, grab_frame


def _pick_times(shots: list, max_frames: int) -> list:
    duration = max(s["end"] for s in shots) if shots else 0.0
    if len(shots) <= 1:
        n = min(max_frames, max(3, int(duration // 2) or 3))
        return [round(duration * (i + 1) / (n + 1), 3) for i in range(n)]
    picked = shots
    if len(shots) > max_frames:
        step = len(shots) / float(max_frames)
        picked = [shots[min(int(i * step), len(shots) - 1)] for i in range(max_frames)]
    return [round((s["start"] + s["end"]) / 2, 3) for s in picked]


def build_card(
    path,
    out_dir,
    lang: str | None = None,
    model: str = "small",
    max_frames: int = 12,
    do_asr: bool = True,
    do_subs: bool = True,
    do_ocr: bool = False,
    progress=None,
) -> dict:
    note = progress or (lambda *_: None)
    info = probe(path)
    note("probe ok")

    shots = detect_shots(path)
    note(f"shots: {len(shots)}")

    out = ensure_dir(out_dir)
    frames_dir = ensure_dir(out / "frames")
    times = _pick_times(shots, max_frames)
    frames = []
    for i, t in enumerate(times, 1):
        dst = frames_dir / f"f{i:03d}.jpg"
        try:
            grab_frame(path, t, dst, width=960)
            frames.append({"t": t, "path": str(dst)})
        except Exception as exc:
            note(f"frame {i} failed: {exc}")

    sheet = None
    try:
        sheet = contact_sheet(path, shots, out / "contact.jpg", limit=9)
    except Exception as exc:
        note(f"contact sheet failed: {exc}")

    onscreen = None
    if do_ocr:
        from .ocr import ocr_image

        onscreen = []
        for fr in frames:
            try:
                texts = ocr_image(fr["path"])
            except Exception as exc:
                note(f"ocr failed at {fr['t']}: {exc}")
                texts = []
            onscreen.append({"t": fr["t"], "texts": texts})
        note(f"ocr ok: {sum(len(x['texts']) for x in onscreen)} 条文字")

    transcript, subs_files, asr_error = [], {}, None
    if do_asr and has_audio(info):
        try:
            note(f"asr: model={model} lang={lang or 'auto'}")
            asr = transcribe(path, language=lang, model=model)
            transcript = asr["segments"]
            if do_subs:
                lines = build_lines(asr)
                subs_files = write_subtitles(lines, out, stem="subs")
            note(f"asr ok: {len(transcript)} segments")
        except Exception as exc:  # network / model failure should not kill the card
            asr_error = str(exc)
            note(f"asr failed: {exc}")

    card = {
        "probe": info,
        "shots": shots,
        "keyframes": frames,
        "transcript": transcript,
        "onscreen": onscreen,
        "files": {
            "dir": str(out),
            "contact": str(sheet) if sheet else None,
            "subtitles": subs_files,
            "card": str(out / "card.json"),
        },
        "asr_error": asr_error,
        "generator": "mediakit watch",
    }
    (out / "card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return card


def main_watch(args) -> dict:
    card = build_card(
        args.file,
        args.out,
        lang=args.lang,
        model=args.model,
        max_frames=args.frames,
        do_asr=not args.no_asr,
        do_subs=not args.no_subs,
        progress=(lambda m: print(f"[watch] {m}", file=sys.stderr)),
    )
    return card
