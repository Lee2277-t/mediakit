from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ollama_base, vlm_model
from .util import ensure_dir, human_duration, out_json, grab_frame


def _cmd_probe(args) -> dict:
    from .probe import probe

    return probe(args.file)


def _cmd_shots(args) -> dict:
    from .shots import contact_sheet, detect_shots, write_otio
    from .util import media_path

    src = media_path(args.file)
    shots = detect_shots(src, threshold=args.threshold, min_seconds=args.min_len)
    result = {"path": str(src), "count": len(shots), "shots": shots, "files": {}}
    if args.out:
        out = ensure_dir(args.out)
        (out / "shots.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["files"]["shots"] = str(out / "shots.json")
        if args.sheet:
            sheet = contact_sheet(src, shots, out / "contact.jpg", limit=args.sheet)
            result["files"]["contact"] = str(sheet)
        if args.otio:
            otio = write_otio(src, shots, out / "timeline.otio")
            result["files"]["otio"] = str(otio)
    return result


def _cmd_frames(args) -> dict:
    from .probe import probe
    from .util import media_path

    src = media_path(args.file)
    info = probe(src)
    duration = float(info.get("duration") or 0)
    out = ensure_dir(args.out)
    n = max(1, args.n)
    items = []
    for i in range(n):
        t = round(duration * (i + 0.5) / n, 3)
        dst = out / f"f{i + 1:03d}.jpg"
        grab_frame(src, t, dst, width=args.width)
        items.append({"t": t, "path": str(dst)})
    return {"path": str(src), "duration": round(duration, 3), "count": n, "frames": items}


def _cmd_subs(args) -> dict:
    from .subs import build_lines, transcribe, write_subtitles
    from .util import media_path

    src = media_path(args.file)
    asr = transcribe(src, language=args.lang, model=args.model, vad=not args.no_vad)
    lines = build_lines(
        asr, max_chars=args.max_chars, max_dur=args.max_dur, pause=args.pause
    )
    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    res = None
    if args.size:
        try:
            w, h = args.size.lower().replace("*", "x").split("x")
            res = (int(w), int(h))
        except Exception:
            raise ValueError("--size 要写成 1080x1920 这种形式")
    out = ensure_dir(args.out)
    files = write_subtitles(
        lines,
        out,
        stem=args.stem,
        formats=formats,
        font_size=args.font_size,
        resolution=res,
        karaoke=args.karaoke,
    )
    result = {
        "path": str(src),
        "language": asr["language"],
        "duration": asr["duration"],
        "segments": len(asr["segments"]),
        "words": len(asr["words"]),
        "lines": len(lines),
        "files": files,
        "preview": lines[:8],
        "asr_segments": asr["segments"],
    }
    if args.qa:
        from .subs import quality_report

        result["qa"] = quality_report(lines, max_chars=args.max_chars)
    return result


def _cmd_subqa(args) -> dict:
    import pysubs2

    from .subs import quality_report
    from .util import media_path

    subs = pysubs2.load(str(media_path(args.file)))
    lines = [
        {"text": ev.plaintext, "start": ev.start / 1000.0, "end": ev.end / 1000.0}
        for ev in subs
        if ev.plaintext.strip()
    ]
    report = quality_report(
        lines,
        max_cps_cjk=args.max_cps_cjk,
        max_cps_latin=args.max_cps_latin,
        max_chars=args.max_chars,
    )
    report["file"] = str(args.file)
    return report


def _cmd_ocr(args) -> dict:
    import json

    from .ocr import ocr_video, write_ocr_srt

    result = ocr_video(
        args.file,
        every=args.every,
        max_frames=args.max_frames,
        min_score=args.min_score,
        progress=lambda m: print(f"[ocr] {m}", file=sys.stderr),
    )
    out = ensure_dir(args.out)
    json_path = out / "ocr.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["files"] = {"json": str(json_path)}
    if result["segments"]:
        result["files"]["srt"] = write_ocr_srt(result, out / "ocr.srt")
    return result


def _cmd_index(args) -> dict:
    from .index import build_index

    return build_index(
        args.file,
        args.out,
        every=args.every,
        max_frames=args.max_frames,
        progress=lambda m: print(f"[index] {m}", file=sys.stderr),
    )


def _cmd_search(args) -> dict:
    from .index import search

    return search(args.dir, args.query, topk=args.top)


def _cmd_lyrics(args) -> dict:
    from .lyrics import make_lyrics

    return make_lyrics(
        args.file,
        args.out,
        lang=args.lang,
        model=args.model,
        separate=not args.no_separate,
        max_chars=args.max_chars,
        pause=args.pause,
        karaoke=not args.no_karaoke,
        resolution=_parse_size(args.size, (1920, 1080)),
        sep_model=args.sep_model,
        progress=lambda m: print(f"[lyrics] {m}", file=sys.stderr),
    )


def _cmd_dub(args) -> dict:
    from .dub import dub

    return dub(
        args.file,
        args.srt,
        args.out,
        voice_name=args.voice,
        rate=args.rate,
        mix_original=args.mix_original,
        fit=not args.no_fit,
        progress=lambda m: print(f"[dub] {m}", file=sys.stderr),
    )


def _cmd_voices(args) -> dict:
    from .dub import list_voices

    return {"voices": list_voices()}


def _cmd_shotcard(args) -> dict:
    from .shotcard import analyze

    return analyze(
        args.file,
        args.out,
        max_shots=args.max_shots,
        use_vlm=args.vlm,
        vlm_max=args.vlm_max,
        vlm_model=args.vlm_model,
        progress=lambda m: print(f"[shotcard] {m}", file=sys.stderr),
    )


def _cmd_music(args) -> dict:
    from .music import analyze
    from .util import media_path

    result = analyze(
        media_path(args.file),
        with_beats=not args.no_beats,
        with_chords=args.chords,
        with_melody=args.melody,
        melody_max=args.melody_max,
        engine=args.engine,
    )
    if args.out:
        out = Path(args.out)
        ensure_dir(out.parent)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["out"] = str(out.resolve())
    return result


def _cmd_watch(args) -> dict:
    from .watch import build_card

    return build_card(
        args.file,
        args.out,
        lang=args.lang,
        model=args.model,
        max_frames=args.frames,
        do_asr=not args.no_asr,
        do_subs=not args.no_subs,
        do_ocr=args.ocr,
        progress=lambda m: print(f"[watch] {m}", file=sys.stderr),
    )


def _cmd_edit(args) -> dict:
    from .edit import load_plan, render

    plan = load_plan(args.plan)
    return render(plan, args.out)


def _parse_size(text: str, default=(1080, 1920)):
    if not text:
        return default
    try:
        w, h = text.lower().replace("*", "x").split("x")
        return (int(w), int(h))
    except Exception:
        raise ValueError("尺寸要写成 1080x1920 这种形式")


def _cmd_auto(args) -> dict:
    from .auto import generate

    return generate(
        args.music,
        args.src,
        args.out,
        size=_parse_size(args.size),
        fps=args.fps,
        fit=args.fit,
        beats_per_cut=args.beats_per_cut,
        pace=args.pace,
        transition=args.transition,
        transition_duration=args.transition_duration,
        max_sources=args.max_sources,
        min_shot=args.min_shot,
        seed=args.seed,
        gain_db=args.gain_db,
        plan_only=args.plan_only,
        progress=lambda m: print(f"[auto] {m}", file=sys.stderr),
    )


def _cmd_polish(args) -> dict:
    from .polish import polish

    return polish(
        args.file,
        args.out,
        model=args.model,
        endpoint=args.endpoint,
        max_cjk=args.max_cjk,
        split=not args.no_split,
        optimize=not args.no_optimize,
    )


# ---------- human-readable output ----------

def _print_probe(info: dict) -> None:
    v = info.get("video") or {}
    a = info.get("audio") or {}
    print(f"文件   {info['path']}")
    print(f"时长   {human_duration(info['duration'])}  ({info['duration']}s)")
    print(f"体积   {info['size_bytes'] / 1024 / 1024:.2f} MB   码率 {info['bit_rate'] // 1000} kbps")
    if v:
        print(f"画面   {v['width']}x{v['height']} @ {v['fps']}fps  {v['codec']}  {v['pix_fmt']}")
    if a:
        print(f"声音   {a['channels']}ch {a['sample_rate']}Hz {a['codec']}")
    if not a:
        print("声音   （无音轨）")


def _print_shots(res: dict) -> None:
    print(f"共 {res['count']} 个镜头")
    for s in res["shots"][:15]:
        print(f"  {s['index']:02d}  {human_duration(s['start'])} → {human_duration(s['end'])}   {s['dur']:.2f}s")
    if res["count"] > 15:
        print(f"  … 其余 {res['count'] - 15} 个")
    for k, v in (res.get("files") or {}).items():
        print(f"  {k}: {v}")


def _print_subs(res: dict) -> None:
    print(f"语言 {res['language']}  时长 {human_duration(res['duration'])}  词 {res['words']} 个")
    print(f"断成 {res['lines']} 行：")
    for ln in res["preview"]:
        print(f"  {ln['start']:7.2f} → {ln['end']:7.2f}  {ln['text']}")
    if res["lines"] > len(res["preview"]):
        print(f"  … 其余 {res['lines'] - len(res['preview'])} 行")
    for fmt, path in res["files"].items():
        print(f"  {fmt}: {path}")


def _print_subqa(res: dict) -> None:
    print(f"{res['file']}")
    print(f"{res['lines']} 条 · 平均 {res['avg_cps']} 字/秒 · 最高 {res['max_cps']} 字/秒")
    if res["ok"]:
        print("没有发现问题")
        return
    print(f"{res['issue_count']} 个问题：")
    for issue in res["issues"][:20]:
        print(f"  第 {issue['line']} 条 @{issue['time']}s  [{issue['type']}] {issue['detail']}")
    if res["issue_count"] > 20:
        print(f"  … 其余 {res['issue_count'] - 20} 个")


def _print_ocr(res: dict) -> None:
    print(f"{res['path']}")
    print(f"每 {res['every']}s 一帧 · {len(res['frames'])} 帧 · 合并成 {len(res['segments'])} 段")
    for seg in res["segments"][:8]:
        print(f"  {seg['start']:7.2f} → {seg['end']:7.2f}  {seg['text']}")
    if len(res["segments"]) > 8:
        print(f"  … 其余 {len(res['segments']) - 8} 段")
    for k, v in (res.get("files") or {}).items():
        print(f"  {k}: {v}")


def _print_index(res: dict) -> None:
    print(f"索引 {res['index']}")
    print(f"{res['frames']} 帧 · 每 {res['every']}s · {res['model']}")


def _print_search(res: dict) -> None:
    print(f"「{res['query']}」在 {res['video']}")
    for hit in res["hits"]:
        print(f"  {hit['t']:8.2f}s  score {hit['score']:.3f}  {hit['thumb']}")


def _print_lyrics(res: dict) -> None:
    print(f"歌曲 {res['song']}")
    if res["vocals"]:
        print(f"人声 {res['vocals']}")
    print(f"语言 {res['language']} · {res['duration']}s · {res['words']} 词 · {res['lines']} 行")
    for ln in res["preview"]:
        print(f"  {ln['start']:7.2f} → {ln['end']:7.2f}  {ln['text']}")
    for k, v in res["files"].items():
        print(f"  {k}: {v}")


def _print_dub(res: dict) -> None:
    print(f"输出 {res['out']}")
    print(f"{res['lines']} 句 · 音色 {res['voice']} · 语速 {res['rate']}")
    if res.get("squeezed"):
        print(f"{res['squeezed']} 句超长，已加速压进字幕时长（最大 {res['max_tempo']}×）")
    if res["mix_original"]:
        print("原声保留 25%，与配音混合")


def _print_voices(res: dict) -> None:
    for v in res["voices"]:
        print(v)


def _print_shotcard(res: dict) -> None:
    s = res["summary"]
    print(f"{res['path']}  ·  {res['count']} 个镜头 · {res['duration']}s")
    print(
        f"平均亮度 {s['avg_brightness']} · 平均饱和 {s['avg_saturation']} · "
        f"静止 {s['static_shots']} / 运动 {s['moving_shots']}"
    )
    for shot in res["shots"][:6]:
        colors = " ".join(c["hex"] for c in shot["colors"][:3])
        print(
            f"  {shot['index']:02d} {shot['start']:.2f}-{shot['end']:.2f}s  "
            f"亮 {shot['brightness']:.2f} 饱和 {shot['saturation']:.2f} "
            f"{shot['motion']['label']}({shot['motion']['magnitude']})  {colors}"
        )
        if shot.get("vlm") and shot["vlm"].get("caption"):
            v = shot["vlm"]
            print(f"      {v.get('shot_size', '?')} · {v.get('camera', '?')} · {v.get('mood', '?')} · {v['caption']}")
    if res["count"] > 6:
        print(f"  … 其余 {res['count'] - 6} 个")


def _print_music(res: dict) -> None:
    key = res.get("key") or {}
    print(f"时长 {human_duration(res['duration'])}   速度 {res['tempo_bpm']} BPM   拍数 {res['beat_count']}")
    if res.get("engine") and res["engine"] != "librosa":
        print(f"节拍引擎 {res['engine']}   强拍 {len(res.get('downbeats') or [])} 个")
    print(f"调性 {key.get('label')}（相关度 {key.get('correlation')}）")
    print(f"响度 {res['loudness_dbfs']} dBFS   峰值 {res['peak_dbfs']} dBFS")
    print(f"段落 {len(res['sections'])} 段：")
    for sec in res["sections"]:
        print(f"  {human_duration(sec['start'])} → {human_duration(sec['end'])}   energy {sec['energy']}")
    if res.get("chords"):
        line = " → ".join(c["chord"] for c in res["chords"][:14])
        print(f"和弦 {len(res['chords'])} 段：{line}")
    if res.get("melody"):
        notes = " ".join(m["note"] for m in res["melody"][:10])
        print(f"旋律 {len(res['melody'])} 个音：{notes} …")


def _print_watch(card: dict) -> None:
    info = card["probe"]
    print(f"文件   {info['path']}")
    print(f"时长   {human_duration(info['duration'])}   镜头 {len(card['shots'])} 个   关键帧 {len(card['keyframes'])} 张")
    print(f"转写   {len(card['transcript'])} 段" + (f"  （失败：{card['asr_error']}）" if card["asr_error"] else ""))
    for seg in card["transcript"][:6]:
        print(f"  {seg['start']:7.2f} → {seg['end']:7.2f}  {seg['text']}")
    if len(card["transcript"]) > 6:
        print(f"  … 其余 {len(card['transcript']) - 6} 段")
    for k, v in card["files"].items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                print(f"  {kk}: {vv}")
        elif v:
            print(f"  {k}: {v}")


def _print_auto(res: dict) -> None:
    print(f"输出 {res.get('out') or '（只出计划，未渲染）'}")
    print(
        f"{res['tempo_bpm']} BPM · {res['segments']} 段 · "
        f"{res['pool_shots']} 个候选镜头 / {res['sources']} 个素材文件"
    )
    print(f"种子 {res['seed']} · 复用 {res['stats']['reused']} 次 · 素材不够压短 {res['stats']['clamped']} 次")
    print(f"计划 {res['plan']}")


def _print_polish(res: dict) -> None:
    print(f"输入 {res['in']}")
    print(f"输出 {res['out']}  （{res['lines']} 行，{res['bytes']} 字节）")
    print(f"模型 {res['model']} @ {res['endpoint']}")
    print("注意：VideoCaptioner 优化完会主动去标点；4B 级模型偶有改写，先小样对比再全量")


def _print_edit(res: dict) -> None:
    print(f"输出 {res['out']}")
    print(f"{res['clips']} 个片段  {res['duration']:.2f}s  {res['size'][0]}x{res['size'][1]} @ {res['fps']}fps")
    print(f"字幕 {'有' if res['subtitled'] else '无'}   配乐 {'有' if res['music'] else '无'}   原声 {'保留' if res['keep_audio'] else '丢弃'}")
    for note in res.get("notes") or []:
        print(f"  注意: {note}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mk", description="mediakit：把看视频/听音乐/做字幕/剪片子合成一套 CLI（供人或 agent 调用）"
    )
    parser.add_argument("--version", action="version", version=f"mediakit {__version__}")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="读媒体元信息")
    p.add_argument("file")
    p.set_defaults(func=_cmd_probe, printer=_print_probe)

    p = sub.add_parser("shots", help="切镜头 + 联系表 + OTIO 时间轴")
    p.add_argument("file")
    p.add_argument("--out", help="输出目录")
    p.add_argument("--threshold", type=float, default=27.0)
    p.add_argument("--min-len", type=float, default=0.5, help="最短镜头秒数")
    p.add_argument("--sheet", type=int, default=9, help="联系表最多几张，0 表示不生成")
    p.add_argument("--otio", action="store_true", help="导出 timeline.otio")
    p.set_defaults(func=_cmd_shots, printer=_print_shots)

    p = sub.add_parser("frames", help="均匀抽帧")
    p.add_argument("file")
    p.add_argument("--n", type=int, default=12)
    p.add_argument("--out", required=True)
    p.add_argument("--width", type=int, default=960)
    p.set_defaults(func=_cmd_frames, printer=lambda r: print(f"抽出 {r['count']} 张 → {r['frames'][0]['path'].rsplit(chr(92), 1)[0]}"))

    p = sub.add_parser("subs", help="转写 + 断句，出 SRT/ASS")
    p.add_argument("file")
    p.add_argument("--lang", default=None, help="zh / en / ja …，不填自动识别")
    p.add_argument("--model", default="small", help="tiny/base/small/medium/large-v3")
    p.add_argument("--max-chars", type=float, default=16.0, help="每行最大显示宽度（汉字算 1）")
    p.add_argument("--max-dur", type=float, default=6.0)
    p.add_argument("--pause", type=float, default=0.28, help="停顿多少秒就断行")
    p.add_argument("--formats", default="srt,ass")
    p.add_argument("--stem", default="subs")
    p.add_argument("--font-size", type=int, default=None, help="不填按画面高度自动算")
    p.add_argument("--size", default=None, help="成片尺寸 WxH，例如 1080x1920；决定 ASS 的 PlayRes")
    p.add_argument("--out", default=".")
    p.add_argument("--no-vad", action="store_true")
    p.add_argument("--karaoke", action="store_true", help="ASS 里生成逐字 \kf 卡拉OK")
    p.add_argument("--qa", action="store_true", help="顺带跑一遍阅读速度/行长检查")
    p.set_defaults(func=_cmd_subs, printer=_print_subs)

    p = sub.add_parser("subqa", help="检查字幕阅读速度/行长/重叠")
    p.add_argument("file")
    p.add_argument("--max-cps-cjk", type=float, default=9.0)
    p.add_argument("--max-cps-latin", type=float, default=20.0)
    p.add_argument("--max-chars", type=float, default=16.0)
    p.set_defaults(func=_cmd_subqa, printer=_print_subqa)

    p = sub.add_parser("ocr", help="读画面上的字（硬字幕/歌词/录屏）")
    p.add_argument("file")
    p.add_argument("--out", required=True, help="输出目录")
    p.add_argument("--every", type=float, default=2.0, help="每几秒取一帧")
    p.add_argument("--max-frames", type=int, default=60)
    p.add_argument("--min-score", type=float, default=0.5)
    p.set_defaults(func=_cmd_ocr, printer=_print_ocr)

    p = sub.add_parser("shotcard", help="每个镜头的亮度/饱和/主色/运动")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    p.add_argument("--max-shots", type=int, default=None)
    p.add_argument("--vlm", action="store_true", help="用本机 VLM 给每个镜头写景别/机位/描述")
    p.add_argument("--vlm-max", type=int, default=12, help="最多给几个镜头跑 VLM")
    p.add_argument("--vlm-model", default=None)
    p.set_defaults(func=_cmd_shotcard, printer=_print_shotcard)

    p = sub.add_parser("index", help="给长视频建 CLIP 索引（可搜片段）")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    p.add_argument("--every", type=float, default=2.0)
    p.add_argument("--max-frames", type=int, default=150)
    p.set_defaults(func=_cmd_index, printer=_print_index)

    p = sub.add_parser("search", help="用一句话在索引里找片段")
    p.add_argument("dir")
    p.add_argument("query")
    p.add_argument("--top", type=int, default=5)
    p.set_defaults(func=_cmd_search, printer=_print_search)

    p = sub.add_parser("dub", help="用 Windows 本地语音给字幕配音")
    p.add_argument("file")
    p.add_argument("--srt", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--voice", default=None, help="音色名的一部分，例如 Huihui")
    p.add_argument("--rate", type=int, default=0, help="-10..10")
    p.add_argument("--mix-original", action="store_true")
    p.add_argument("--no-fit", action="store_true", help="不把过长的配音加速压进字幕时长")
    p.set_defaults(func=_cmd_dub, printer=_print_dub)

    p = sub.add_parser("voices", help="列出本机 SAPI 语音")
    p.set_defaults(func=_cmd_voices, printer=_print_voices)

    p = sub.add_parser("lyrics", help="分人声 + 识别歌词，出 SRT/ASS/LRC")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    p.add_argument("--lang", default=None)
    p.add_argument("--model", default="small")
    p.add_argument("--no-separate", action="store_true")
    p.add_argument("--sep-model", default=None)
    p.add_argument("--max-chars", type=float, default=18.0)
    p.add_argument("--pause", type=float, default=0.35)
    p.add_argument("--no-karaoke", action="store_true")
    p.add_argument("--size", default="1920x1080")
    p.set_defaults(func=_cmd_lyrics, printer=_print_lyrics)

    p = sub.add_parser("music", help="测 BPM/调性/段落")
    p.add_argument("file")
    p.add_argument("--out", help="把结果写成 JSON")
    p.add_argument("--no-beats", action="store_true")
    p.add_argument("--chords", action="store_true", help="估和弦进行（模板匹配）")
    p.add_argument("--melody", action="store_true", help="估主旋律音高（pyin）")
    p.add_argument("--melody-max", type=float, default=40.0, help="旋律只分析前 N 秒")
    p.add_argument("--engine", choices=("librosa", "beat-this"), default="librosa",
                   help="节拍追踪器；beat-this 会同时给 downbeats")
    p.set_defaults(func=_cmd_music, printer=_print_music)

    p = sub.add_parser("watch", help="一张卡片看完一个视频")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    p.add_argument("--lang", default=None)
    p.add_argument("--model", default="small")
    p.add_argument("--frames", type=int, default=12)
    p.add_argument("--no-asr", action="store_true")
    p.add_argument("--no-subs", action="store_true")
    p.add_argument("--ocr", action="store_true", help="顺带读关键帧上的字")
    p.set_defaults(func=_cmd_watch, printer=_print_watch)

    p = sub.add_parser("auto", help="音乐 + 素材 → 卡点短片")
    p.add_argument("--music", required=True)
    p.add_argument("--src", action="append", required=True, help="素材文件或目录，可重复给")
    p.add_argument("--out", required=True)
    p.add_argument("--size", default="1080x1920")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--fit", default="crop", choices=["crop", "pad"])
    p.add_argument("--beats-per-cut", type=int, default=4, help="每几拍切一次（--pace fixed 时生效）")
    p.add_argument("--pace", default="auto", choices=["auto", "fixed"], help="auto=按段落能量变节奏")
    p.add_argument("--max-sources", type=int, default=12)
    p.add_argument("--min-shot", type=float, default=0.8)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--gain-db", type=float, default=-14)
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--transition", default="none", choices=["none", "fade", "dissolve", "wipeleft", "slideleft"])
    p.add_argument("--transition-duration", type=float, default=0.25)
    p.set_defaults(func=_cmd_auto, printer=_print_auto)

    p = sub.add_parser("polish", help="用本地 Ollama（经 VideoCaptioner）润色字幕")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    p.add_argument("--model", default=None)
    p.add_argument("--endpoint", default=None)
    p.add_argument("--max-cjk", type=int, default=16)
    p.add_argument("--no-split", action="store_true")
    p.add_argument("--no-optimize", action="store_true")
    p.set_defaults(func=_cmd_polish, printer=_print_polish)

    p = sub.add_parser("edit", help="按 JSON 计划剪一条片子")
    p.add_argument("plan")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_edit, printer=_print_edit)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except Exception as exc:
        sys.stderr.write(f"错误: {exc}\n")
        return 2
    if args.json:
        out_json(result)
    else:
        try:
            args.printer(result)
        except Exception:
            out_json(result)
    return 0
