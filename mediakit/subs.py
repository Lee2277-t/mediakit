from __future__ import annotations

import math
import re
from pathlib import Path

import pysubs2

from .util import ensure_dir, media_path

_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_END_PUNCT = "。！？!?…"
_MID_PUNCT = "，,、；;：:"

_MODELS: dict = {}
_CC = None


def _to_simplified(text: str) -> str:
    global _CC
    if not text:
        return text
    if _CC is None:
        try:
            from opencc import OpenCC

            _CC = OpenCC("t2s")
        except Exception:
            _CC = False
    if not _CC:
        return text
    try:
        return _CC.convert(text)
    except Exception:
        return text


def display_len(text: str) -> float:
    n = 0.0
    for ch in text or "":
        if ch.isspace():
            continue
        if _CJK.match(ch):
            n += 1.0
        elif ch in _END_PUNCT or ch in _MID_PUNCT:
            n += 0.3
        else:
            n += 0.55
    return n


def _word_text(word) -> str:
    return getattr(word, "word", "") or getattr(word, "text", "") or ""


def get_model(size: str = "small", device: str = "cpu"):
    key = (size, device)
    if key not in _MODELS:
        from faster_whisper import WhisperModel

        _MODELS[key] = WhisperModel(size, device=device, compute_type="int8")
    return _MODELS[key]


def transcribe(path, language: str | None = None, model: str = "small", vad: bool = True) -> dict:
    p = media_path(path)
    m = get_model(model)
    prompt = None
    if language and language.lower().startswith("zh"):
        prompt = "以下是简体中文普通话的句子。"
    segments, info = m.transcribe(
        str(p),
        language=language,
        vad_filter=vad,
        beam_size=5,
        word_timestamps=True,
        initial_prompt=prompt,
    )
    seg_list, words = [], []
    for seg in segments:
        text = _to_simplified((seg.text or "").strip())
        seg_list.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": text})
        for w in getattr(seg, "words", None) or []:
            wt = _to_simplified(_word_text(w))
            if not wt.strip():
                continue
            words.append({"start": round(w.start, 3), "end": round(w.end, 3), "text": wt})
    return {
        "path": str(p),
        "language": info.language,
        "language_probability": round(float(info.language_probability or 0), 3),
        "duration": round(float(info.duration or 0), 3),
        "segments": seg_list,
        "words": words,
    }


def _mk_line(words: list) -> dict:
    text = "".join(w["text"] for w in words).strip()
    return {
        "text": text,
        "start": round(words[0]["start"], 3),
        "end": round(words[-1]["end"], 3),
        "words": list(words),
    }


def lines_from_words(
    words: list,
    max_chars: float = 16.0,
    max_dur: float = 6.0,
    min_dur: float = 0.6,
    pause: float = 0.28,
    min_chars: float = 4.0,
) -> list:
    if not words:
        return []
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        text = "".join(x["text"] for x in cur)
        ended = bool(re.search(r"[。！？!?…，,、；;：:]$", w["text"].strip()))
        gap = (nxt["start"] - w["end"]) if nxt else 999.0
        if nxt is None or display_len(text) >= max_chars or gap >= pause or ended:
            lines.append(_mk_line(cur))
            cur = []

    merged = []
    for ln in lines:
        if (
            merged
            and display_len(merged[-1]["text"]) < min_chars
            and display_len(merged[-1]["text"] + ln["text"]) <= max_chars
        ):
            words_join = merged[-1]["words"] + ln["words"]
            merged[-1] = _mk_line(words_join)
        else:
            merged.append(ln)

    fixed = []
    for ln in merged:
        dur = ln["end"] - ln["start"]
        if dur > max_dur and len(ln["words"]) >= 2:
            cuts = max(2, int(dur // max_dur) + 1)
            per = max(1, math.ceil(len(ln["words"]) / cuts))
            for k in range(0, len(ln["words"]), per):
                grp = ln["words"][k:k + per]
                if grp:
                    fixed.append(_mk_line(grp))
        else:
            fixed.append(ln)

    for i, ln in enumerate(fixed):
        if i and ln["start"] < fixed[i - 1]["end"]:
            ln["start"] = round(fixed[i - 1]["end"] + 0.02, 3)
        if ln["end"] - ln["start"] < min_dur:
            ln["end"] = round(ln["start"] + min_dur, 3)
    return [ln for ln in fixed if ln["text"].strip()]


def lines_from_segments(segments: list, max_chars: float = 16.0, max_dur: float = 6.0) -> list:
    out = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        dur = max(seg["end"] - seg["start"], 0.3)
        total = max(display_len(text), 0.5)
        buf, acc = "", 0.0
        pieces = []
        for ch in text:
            buf += ch
            acc += display_len(ch)
            if acc >= max_chars or (ch in _END_PUNCT and acc >= max_chars * 0.5):
                pieces.append((buf, acc))
                buf, acc = "", 0.0
        if buf:
            pieces.append((buf, acc))
        weights = [max(p[1], 0.5) for p in pieces] or [1.0]
        wsum = sum(weights)
        cursor = seg["start"]
        for piece, w in zip(pieces, weights):
            d = dur * (w / wsum)
            out.append(
                {
                    "text": piece.strip(),
                    "start": round(cursor, 3),
                    "end": round(min(cursor + d, seg["end"]), 3),
                    "words": [],
                }
            )
            cursor += d
    return out


def build_lines(
    asr: dict,
    max_chars: float = 16.0,
    max_dur: float = 6.0,
    pause: float = 0.28,
    min_chars: float = 4.0,
) -> list:
    if asr.get("words"):
        return lines_from_words(
            asr["words"], max_chars=max_chars, max_dur=max_dur, pause=pause, min_chars=min_chars
        )
    return lines_from_segments(asr.get("segments", []), max_chars=max_chars, max_dur=max_dur)


def _style(font_size: int = 48, karaoke: bool = False):
    st = pysubs2.SSAStyle()
    st.fontname = "Microsoft YaHei"
    st.fontsize = font_size
    st.primarycolor = pysubs2.Color(255, 255, 255, 0)
    st.secondarycolor = pysubs2.Color(120, 120, 120, 0) if karaoke else pysubs2.Color(255, 255, 255, 0)
    st.outlinecolor = pysubs2.Color(0, 0, 0, 0)
    st.backcolor = pysubs2.Color(0, 0, 0, 128)
    st.bold = False
    st.outline = 2.0
    st.shadow = 0.0
    st.alignment = 2
    st.marginv = 40
    return st


def _karaoke_text(line: dict) -> str:
    parts = []
    for w in line.get("words") or []:
        txt = w["text"].replace("\n", " ")
        if not txt:
            continue
        cs = max(1, int(round((w["end"] - w["start"]) * 100)))
        parts.append(r"{\kf%d}%s" % (cs, txt))
    return "".join(parts)


def write_subtitles(
    lines: list,
    out_dir,
    stem: str = "subs",
    formats=("srt", "ass"),
    font_size: int | None = None,
    resolution=None,
    karaoke: bool = False,
) -> dict:
    out = ensure_dir(out_dir)
    res = tuple(resolution) if resolution else (1920, 1080)
    fs = int(font_size) if font_size else max(20, round(res[1] * 0.042))
    subs = pysubs2.SSAFile()
    subs.info["Title"] = stem
    subs.info["PlayResX"] = int(res[0])
    subs.info["PlayResY"] = int(res[1])
    subs.styles["Default"] = _style(fs, karaoke=karaoke)
    for ln in lines:
        if karaoke and ln.get("words"):
            text = _karaoke_text(ln)
        else:
            text = ln["text"].replace("\n", r"\N")
        subs.append(
            pysubs2.SSAEvent(
                start=int(round(ln["start"] * 1000)),
                end=int(round(max(ln["end"], ln["start"] + 0.2) * 1000)),
                text=text,
                style="Default",
            )
        )
    written = {}
    for fmt in formats:
        path = out / f"{stem}.{fmt}"
        subs.save(str(path))
        written[fmt] = str(path)
    return written


def quality_report(
    lines: list,
    max_cps_cjk: float = 9.0,
    max_cps_latin: float = 20.0,
    max_chars: float = 16.0,
    min_dur: float = 0.7,
    max_dur: float = 7.0,
) -> dict:
    issues = []
    cps_values = []
    for i, ln in enumerate(lines, 1):
        text = (ln.get("text") or "").strip()
        if not text:
            continue
        dur = max(ln["end"] - ln["start"], 1e-3)
        chars = len(re.sub(r"\s", "", text))
        cjk_ratio = sum(1 for ch in text if _CJK.match(ch)) / max(len(text), 1)
        limit = max_cps_cjk if cjk_ratio > 0.3 else max_cps_latin
        cps = chars / dur
        cps_values.append(cps)
        if cps > limit:
            issues.append(
                {
                    "line": i,
                    "type": "cps",
                    "time": round(ln["start"], 2),
                    "detail": f"{cps:.1f} 字/秒，超过 {limit:.0f}",
                }
            )
        if display_len(text) > max_chars * 1.05:
            issues.append(
                {
                    "line": i,
                    "type": "width",
                    "time": round(ln["start"], 2),
                    "detail": f"显示宽度 {display_len(text):.0f}，超过 {max_chars:.0f}",
                }
            )
        if dur < min_dur:
            issues.append(
                {
                    "line": i,
                    "type": "short",
                    "time": round(ln["start"], 2),
                    "detail": f"只停 {dur:.2f}s，短于 {min_dur}s",
                }
            )
        if dur > max_dur:
            issues.append(
                {
                    "line": i,
                    "type": "long",
                    "time": round(ln["start"], 2),
                    "detail": f"停 {dur:.2f}s，长于 {max_dur}s",
                }
            )
        if i > 1 and ln["start"] < lines[i - 2]["end"] - 0.01:
            issues.append(
                {
                    "line": i,
                    "type": "overlap",
                    "time": round(ln["start"], 2),
                    "detail": f"与上一条重叠 {lines[i - 2]['end'] - ln['start']:.2f}s",
                }
            )

    return {
        "lines": len(lines),
        "avg_cps": round(sum(cps_values) / len(cps_values), 2) if cps_values else 0.0,
        "max_cps": round(max(cps_values), 2) if cps_values else 0.0,
        "issues": issues,
        "issue_count": len(issues),
        "ok": not issues,
    }
