from __future__ import annotations

import json
from pathlib import Path

from .probe import probe
from .util import ffmpeg, media_path


def _prepare_ass(src, width: int, height: int, dst) -> None:
    """把任意 PlayRes 的 ASS 重新按目标尺寸标定，字号随高度等比缩放。"""
    import pysubs2

    subs = pysubs2.load(str(src))
    try:
        pry = float(subs.info.get("PlayResY") or 0) or 288.0
    except Exception:
        pry = 288.0
    scale = height / pry if pry else 1.0
    if abs(scale - 1.0) > 0.01:
        for st in subs.styles.values():
            st.fontsize = max(12.0, st.fontsize * scale)
    subs.info["PlayResX"] = int(width)
    subs.info["PlayResY"] = int(height)
    subs.save(str(dst))


def load_plan(path) -> dict:
    p = media_path(path)
    plan = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or not plan.get("clips"):
        raise ValueError("edit 计划里必须有非空的 clips 数组")
    return plan


def _resolve_clips(clips: list) -> list:
    out = []
    for c in clips:
        src = media_path(c["src"])
        info = probe(src)
        src_dur = float(info.get("duration") or 0)
        start = max(float(c.get("in", 0)), 0.0)
        end = c.get("out")
        end = src_dur if end is None else min(float(end), src_dur)
        out.append(
            {
                "src": str(src),
                "info": info,
                "in": start,
                "out": end,
                "dur": max(end - start, 0.05),
            }
        )
    return out


def _nearest(value: float, beats: list):
    if not beats:
        return None
    best = beats[0]
    for b in beats:
        if abs(b - value) < abs(best - value):
            best = b
    return best


def _snap_to_beats(clips: list, beats: list, tolerance: float = 0.35):
    """把每个片段之间的切点挪到最近的拍上；挪不动（素材不够）就保持原样。"""
    durs = [c["dur"] for c in clips]
    new_durs, cuts, snapped, clamped = [], [0.0], 0, 0
    cum = 0.0
    for i, d in enumerate(durs):
        if i == len(durs) - 1:
            new_durs.append(d)
            cum += d
            cuts.append(round(cum, 3))
            continue
        target = cum + d
        beat = _nearest(target, beats)
        cand = d
        if beat is not None and abs(beat - target) <= tolerance and beat - cum >= 0.4:
            cand = beat - cum
        avail = float(clips[i]["info"].get("duration") or 0) - clips[i]["in"] - 0.02
        if avail > 0 and cand > avail:
            cand = avail
            clamped += 1
        cand = max(cand, 0.2)
        if abs(cand - d) > 1e-6:
            snapped += 1
        new_durs.append(cand)
        cum += cand
        cuts.append(round(cum, 3))
    return new_durs, cuts, snapped, clamped


def render(plan: dict, out_path) -> dict:
    clips = _resolve_clips(plan["clips"])
    width, height = plan.get("size", [1080, 1920])
    fps = int(plan.get("fps", 30))
    crf = int(plan.get("crf", 20))
    preset = plan.get("preset", "medium")
    keep_audio = bool(plan.get("keep_audio", False))
    music = plan.get("music") or None
    subtitle = plan.get("subtitle")
    fit = plan.get("fit", "pad")
    beat_sync = bool(plan.get("beat_sync") or (music or {}).get("beat_sync"))
    log = []

    beat_info = None
    if beat_sync:
        if not music:
            log.append("beat_sync 需要同时给 music，已忽略")
        else:
            from .music import analyze

            mres = analyze(music["src"], with_beats=True)
            beats = mres.get("beats") or []
            durs, cuts, snapped, clamped = _snap_to_beats(
                clips, beats, float(plan.get("beat_tolerance", 0.35))
            )
            for clip, d in zip(clips, durs):
                clip["dur"] = d
            beat_info = {
                "source_bpm": mres.get("tempo_bpm"),
                "beats": len(beats),
                "snapped": snapped,
                "clamped": clamped,
                "cuts": cuts,
            }
            log.append(
                f"卡点：{snapped}/{max(len(clips) - 1, 1)} 个切点落在拍上"
                + (f"，{clamped} 个因素材不够未能延长" if clamped else "")
            )

    args: list = []
    filters: list = []
    total = 0.0
    audios_ok = True

    for i, clip in enumerate(clips):
        dur = clip["dur"]
        total += dur
        args += ["-ss", f"{clip['in']:.3f}", "-t", f"{dur:.3f}", "-i", clip["src"]]
        if fit == "crop":
            filters.append(
                f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p[v{i}]"
            )
        else:
            filters.append(
                f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]"
            )
        if not clip["info"].get("audio"):
            audios_ok = False

    n = len(clips)
    durs = [c["dur"] for c in clips]
    transition = plan.get("transition") or {}
    ttype = (transition.get("type") or "").strip().lower()
    tdur = float(transition.get("duration", 0.3) or 0)
    use_xfade = (
        bool(ttype)
        and ttype != "none"
        and n > 1
        and tdur > 0
        and min(durs) > tdur + 0.1
    )
    if ttype and ttype != "none" and not use_xfade:
        log.append(f"转场 {ttype} 未启用：片段太短或参数不合法")

    if use_xfade:
        offset = durs[0] - tdur
        cur = "[v0]"
        for i in range(1, n):
            label = f"[vx{i}]"
            filters.append(
                f"{cur}[v{i}]xfade=transition={ttype}:duration={tdur:.3f}:offset={offset:.3f}{label}"
            )
            cur = label
            offset += durs[i] - tdur
        vcat = cur
        total = sum(durs) - (n - 1) * tdur
    else:
        filters.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
        vcat = "[vcat]"
        total = sum(durs)

    if keep_audio and not audios_ok:
        log.append("有片段没有音轨，已忽略 keep_audio")
        keep_audio = False

    audio_out = None
    if keep_audio:
        for i in range(n):
            filters.append(
                f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]"
            )
        if use_xfade:
            cur = "[a0]"
            for i in range(1, n):
                label = f"[ax{i}]"
                filters.append(f"{cur}[a{i}]acrossfade=d={tdur:.3f}:c1=tri:c2=tri{label}")
                cur = label
            audio_out = cur
        else:
            filters.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[acat]")
            audio_out = "[acat]"

    music_index = n
    if music:
        m_src = media_path(music["src"])
        if music.get("loop", True):
            args += ["-stream_loop", "-1"]
        args += ["-i", str(m_src)]
        gain = float(music.get("gain_db", -14))
        filters.append(
            f"[{music_index}:a]volume={gain}dB,atrim=0:{total:.3f},asetpts=PTS-STARTPTS[ma]"
        )
        if audio_out:
            filters.append(f"{audio_out}[ma]amix=inputs=2:duration=first:dropout_transition=0[aout]")
        else:
            filters.append("[ma]anull[aout]")
        audio_out = "[aout]"

    vout = vcat
    workdir = None
    if subtitle:
        import shutil
        import tempfile

        src_sub = media_path(subtitle)
        out_dir = Path(out_path).resolve().parent
        out_dir.mkdir(parents=True, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix="mkburn_", dir=str(out_dir))
        suffix = src_sub.suffix.lower()
        if suffix == ".ass":
            _prepare_ass(src_sub, width, height, Path(workdir) / "burn.ass")
            filters.append(f"{vcat}ass=burn.ass[vsub]")
        else:
            shutil.copy2(src_sub, Path(workdir) / f"burn{suffix}")
            filters.append(f"{vcat}subtitles=burn" + suffix + "[vsub]")
        vout = "[vsub]"

    cmd = args + ["-filter_complex", ";".join(filters), "-map", vout]
    if audio_out:
        cmd += ["-map", audio_out, "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-t", f"{total:.3f}",
        "-movflags", "+faststart",
        str(Path(out_path).resolve()),
    ]
    try:
        ffmpeg(*cmd, timeout=7200, cwd=workdir)
    finally:
        if workdir:
            import shutil as _shutil

            _shutil.rmtree(workdir, ignore_errors=True)

    return {
        "out": str(Path(out_path).resolve()),
        "clips": len(clips),
        "duration": round(total, 3),
        "size": [width, height],
        "fps": fps,
        "fit": fit,
        "transition": ttype if use_xfade else None,
        "subtitled": bool(subtitle),
        "music": bool(music),
        "keep_audio": keep_audio,
        "beat_sync": beat_info,
        "notes": log,
    }
