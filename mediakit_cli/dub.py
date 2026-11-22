from __future__ import annotations

import sys
import tempfile
import wave
from pathlib import Path

import pysubs2

from .util import ffmpeg, media_path


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("dub 依赖 Windows SAPI，只能在 Windows 上运行")


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def list_voices() -> list:
    _require_windows()
    import win32com.client

    voice = win32com.client.Dispatch("SAPI.SpVoice")
    return [v.GetDescription() for v in voice.GetVoices()]


def _synth(text: str, wav_path: Path, voice_name: str | None = None, rate: int = 0) -> None:
    import win32com.client

    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(wav_path), 3, False)  # 3 = SSFMCreateForWrite
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    if voice_name:
        for v in voice.GetVoices():
            if voice_name.lower() in v.GetDescription().lower():
                voice.Voice = v
                break
    voice.Rate = int(max(-10, min(10, rate)))
    voice.AudioOutputStream = stream
    try:
        voice.Speak(text)
    finally:
        stream.Close()


def dub(
    video,
    srt,
    out,
    voice_name: str | None = None,
    rate: int = 0,
    mix_original: bool = False,
    fit: bool = True,
    progress=None,
) -> dict:
    note = progress or (lambda *_: None)
    _require_windows()
    src = media_path(video)
    sub_path = media_path(srt)
    subs = pysubs2.load(str(sub_path))
    events = [e for e in subs if e.plaintext.strip()]
    if not events:
        raise RuntimeError("字幕里没有可用文本")

    tmp = Path(tempfile.mkdtemp(prefix="mkdub_"))
    wavs = []
    squeezed = 0
    max_tempo = 1.0
    try:
        for i, ev in enumerate(events):
            wav = tmp / f"{i:03d}.wav"
            _synth(ev.plaintext.strip(), wav, voice_name, rate)
            slot = max((ev.end - ev.start) / 1000.0, 0.2)
            dur = _wav_duration(wav)
            tempo = 1.0
            if fit and dur > slot * 1.02:
                tempo = min(2.0, max(0.5, dur / slot))
                if tempo > 1.001:
                    squeezed += 1
                    max_tempo = max(max_tempo, tempo)
            wavs.append((max(ev.start, 0), wav, tempo))
            if i % 10 == 0:
                note(f"合成 {i + 1}/{len(events)}")

        args = ["-i", str(src)]
        for _, wav, _ in wavs:
            args += ["-i", str(wav)]

        filters = []
        labels = []
        for i, (start_ms, _, tempo) in enumerate(wavs):
            idx = i + 1
            stretch = f"atempo={tempo:.3f}," if tempo > 1.001 else ""
            filters.append(
                f"[{idx}:a]{stretch}adelay={start_ms}|{start_ms},aresample=48000,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo[d{i}]"
            )
            labels.append(f"[d{i}]")

        counter = {"n": 0}

        def mix(group: list) -> str:
            if len(group) == 1:
                return group[0]
            merged = []
            for gi in range(0, len(group), 20):
                part = group[gi:gi + 20]
                if len(part) == 1:
                    merged.append(part[0])
                    continue
                counter["n"] += 1
                label = f"[mx{counter['n']}]"
                filters.append(
                    f"{''.join(part)}amix=inputs={len(part)}:normalize=0:dropout_transition=0{label}"
                )
                merged.append(label)
            return mix(merged)

        audio_label = mix(labels)
        if mix_original:
            filters.append(
                "[0:a]volume=0.25,aresample=48000,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo[orig]"
            )
            filters.append(f"{audio_label}[orig]amix=inputs=2:normalize=0[aout]")
            audio_label = "[aout]"

        from .probe import probe

        video_dur = float(probe(src).get("duration") or 0)
        if video_dur > 0:
            filters.append(f"{audio_label}apad=whole_dur={video_dur:.3f}[apad]")
            audio_label = "[apad]"

        cmd = args + [
            "-filter_complex", ";".join(filters),
            "-map", "0:v",
            "-map", audio_label,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(Path(out).resolve()),
        ]
        note("混音")
        ffmpeg(*cmd, timeout=3600)
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

    return {
        "out": str(Path(out).resolve()),
        "lines": len(events),
        "voice": voice_name or "默认",
        "rate": rate,
        "mix_original": mix_original,
        "fit": fit,
        "squeezed": squeezed,
        "max_tempo": round(max_tempo, 2),
    }
