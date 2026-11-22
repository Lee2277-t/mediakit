from __future__ import annotations

import json
import random
from pathlib import Path

from .edit import render
from .music import analyze
from .util import ensure_dir, media_path

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def collect_sources(srcs) -> list:
    files = []
    for raw in srcs:
        p = Path(raw).expanduser()
        if p.is_dir():
            files += [f for f in sorted(p.rglob("*")) if f.suffix.lower() in VIDEO_EXT]
        elif p.suffix.lower() in VIDEO_EXT:
            files.append(media_path(p))
    # 去重且保持顺序
    seen, out = set(), []
    for f in files:
        key = str(f.resolve()).lower()
        if key not in seen:
            seen.add(key)
            out.append(f.resolve())
    return out


def pace_map(sections: list, default_k: int = 4, k_fast: int = 3, k_slow: int = 8) -> list:
    """按段落能量定每段的“几拍一切”：能量越高切得越密。

    能量差小于 15% 时视为同一档，避免两段几乎一样响却切出 6 拍 vs 2 拍。
    """
    if not sections or len(sections) < 2:
        return []
    energies = [float(s.get("energy") or 0) for s in sections]
    lo, hi = min(energies), max(energies)
    spread = (hi - lo) / max(hi, 1e-9)
    uniform = spread < 0.15
    out = []
    for s, e in zip(sections, energies):
        if uniform:
            k = default_k
        else:
            norm = (e - lo) / (hi - lo) if hi > lo else 0.5
            k = int(round(k_slow + (k_fast - k_slow) * norm))
        out.append(
            {
                "start": s["start"],
                "end": s["end"],
                "energy": e,
                "beats_per_cut": max(1, min(k, k_slow)),
            }
        )
    return out


def cut_points(
    beats: list,
    duration: float,
    beats_per_cut: int,
    pmap: list | None = None,
    fallback: float = 2.5,
) -> list:
    if not beats:
        n = max(1, int(duration // fallback))
        return [round(i * fallback, 3) for i in range(n + 1)] + [round(duration, 3)]
    cuts = [0.0]
    if pmap:
        for sec in pmap:
            k = int(sec["beats_per_cut"])
            bs = [b for b in beats if sec["start"] <= b < sec["end"]]
            for i, b in enumerate(bs):
                if (i + 1) % k == 0 and b > cuts[-1] + 0.4 and b < duration - 0.4:
                    cuts.append(round(b, 3))
    else:
        for i, b in enumerate(beats):
            if (i + 1) % max(1, beats_per_cut) == 0 and b > cuts[-1] + 0.4 and b < duration - 0.4:
                cuts.append(round(b, 3))
    cuts.append(round(duration, 3))
    return cuts


def build_pool(files: list, limit: int, min_shot: float, progress) -> list:
    from .shots import detect_shots

    pool = []
    for idx, f in enumerate(files[:limit], 1):
        try:
            shots = detect_shots(f)
        except Exception as exc:
            progress(f"跳过 {f.name}: {exc}")
            continue
        kept = [s for s in shots if s["dur"] >= min_shot]
        progress(f"[{idx}/{min(len(files), limit)}] {f.name}: {len(shots)} 镜头，{len(kept)} 个可用")
        for s in kept:
            pool.append({"src": str(f), "start": s["start"], "end": s["end"], "dur": s["dur"]})
    return pool


def select_clips(cuts: list, pool: list, seed: int, progress) -> tuple:
    if not pool:
        raise RuntimeError("素材里没有可用镜头：检查 --src 路径或降低 --min-shot")
    rng = random.Random(seed)
    clips, used, last_key = [], set(), None
    clamped, reused = 0, 0
    cursor = 0.0
    for cut in cuts[1:]:
        need = cut - cursor
        if need < 0.4:
            continue
        cands = [s for s in pool if s["dur"] >= need - 1e-3]
        if not cands:
            cands = [max(pool, key=lambda s: s["dur"])]
            clamped += 1
        fresh = [s for s in cands if (s["src"], s["start"]) not in used]
        avoid_last = [s for s in (fresh or cands) if (s["src"], s["start"]) != last_key]
        pick_pool = avoid_last or fresh or cands
        shot = rng.choice(pick_pool)
        if shot["dur"] < need:
            need = shot["dur"]
        key = (shot["src"], shot["start"])
        if key in used:
            reused += 1
        used.add(key)
        last_key = key
        hi = max(shot["start"], shot["end"] - need)
        in_t = rng.uniform(shot["start"], hi)
        clips.append(
            {
                "src": shot["src"],
                "in": round(in_t, 3),
                "out": round(in_t + need, 3),
            }
        )
        cursor += need
    progress(f"选了 {len(clips)} 段，复用 {reused} 次，素材不够被压短 {clamped} 次")
    return clips, {"reused": reused, "clamped": clamped, "filled": round(cursor, 3)}


def generate(
    music,
    srcs,
    out,
    size=(1080, 1920),
    fps: int = 30,
    fit: str = "crop",
    beats_per_cut: int = 4,
    pace: str = "auto",
    transition: str = "none",
    transition_duration: float = 0.25,
    max_sources: int = 12,
    min_shot: float = 0.8,
    seed: int = 7,
    gain_db: float = -14.0,
    plan_only: bool = False,
    progress=None,
) -> dict:
    note = progress or (lambda *_: None)
    m_path = media_path(music)
    note(f"分析音乐 {m_path.name}")
    m = analyze(m_path, with_beats=True)
    pmap = pace_map(m.get("sections") or [], default_k=beats_per_cut) if pace == "auto" else []
    cuts = cut_points(m["beats"], m["duration"], beats_per_cut, pmap=pmap)
    if pace == "auto" and len(cuts) < 3:
        cuts = cut_points(m["beats"], m["duration"], beats_per_cut)
        pmap = []
        note("段落变化不足，退回固定拍数")
    note(f"{m['tempo_bpm']} BPM，{len(m['beats'])} 拍，切点 {len(cuts) - 1} 个，节奏 {pace}")

    files = collect_sources(srcs)
    note(f"素材 {len(files)} 个文件，本次扫描前 {min(len(files), max_sources)} 个")
    pool = build_pool(files, max_sources, min_shot, note)
    clips, stats = select_clips(cuts, pool, seed, note)

    plan = {
        "size": list(size),
        "fps": fps,
        "fit": fit,
        "crf": 20,
        "clips": clips,
        "music": {"src": str(m_path), "gain_db": gain_db, "loop": True},
        "keep_audio": False,
    }
    if transition and transition != "none":
        plan["transition"] = {"type": transition, "duration": transition_duration}
    out_path = Path(out).resolve()
    ensure_dir(out_path.parent)
    plan_path = out_path.with_suffix(out_path.suffix + ".plan.json")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    note(f"计划已写入 {plan_path}")

    result = {
        "out": None,
        "plan": str(plan_path),
        "duration": m["duration"],
        "tempo_bpm": m["tempo_bpm"],
        "beats": len(m["beats"]),
        "cuts": cuts,
        "segments": len(clips),
        "sources": len(files),
        "pool_shots": len(pool),
        "seed": seed,
        "stats": stats,
        "pace": {"mode": pace, "sections": pmap},
        "transition": transition if transition != "none" else None,
    }
    if plan_only:
        return result

    note("开始渲染")
    rendered = render(plan, out_path)
    result.update({"out": rendered["out"], "duration": rendered["duration"]})
    return result
