from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .util import media_path

_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _key(chroma_mean: np.ndarray):
    best = None
    for i in range(12):
        rolled = np.roll(chroma_mean, -i)
        for mode, tpl in (("major", _MAJOR), ("minor", _MINOR)):
            try:
                corr = float(np.corrcoef(rolled, tpl)[0, 1])
            except Exception:
                continue
            if best is None or corr > best["correlation"]:
                best = {
                    "tonic": _NOTES[i],
                    "mode": mode,
                    "label": f"{_NOTES[i]} {mode}",
                    "correlation": round(corr, 3),
                }
    return best or {"tonic": None, "mode": None, "label": None, "correlation": 0.0}


def _sections(y: np.ndarray, sr: int, hop: int = 512, min_gap: float = 8.0):
    rms = __import__("librosa").feature.rms(y=y, hop_length=hop)[0]
    step = max(1, int(sr / hop))
    env = np.array([rms[i:i + step].mean() for i in range(0, len(rms), step)], dtype=float)
    if len(env) < 8:
        return [{"start": 0.0, "end": round(len(y) / sr, 2), "energy": 0.0}]
    k = min(5, len(env))
    env_s = np.convolve(env, np.ones(k) / k, mode="same")
    diff = np.abs(np.diff(env_s))
    if diff.size == 0 or float(diff.max()) == 0.0:
        return [{"start": 0.0, "end": round(len(y) / sr, 2), "energy": round(float(env.mean()), 4)}]
    thr = float(diff.mean() + 1.2 * diff.std())
    cand = [i + 1 for i, v in enumerate(diff) if v > thr]
    cuts = [0.0]
    for c in cand:
        t = float(c)
        if t - cuts[-1] >= min_gap and (len(y) / sr) - t >= min_gap:
            cuts.append(t)
    cuts.append(float(len(y) / sr))
    out = []
    for a, b in zip(cuts, cuts[1:]):
        seg = env[int(a):int(b)]
        out.append(
            {
                "start": round(a, 2),
                "end": round(b, 2),
                "energy": round(float(seg.mean()) if len(seg) else 0.0, 4),
            }
        )
    return out


def estimate_chords(y, sr: int, beats: list, min_dur: float = 0.35) -> list:
    import librosa

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    times = librosa.times_like(chroma, sr=sr)
    duration = len(y) / sr
    bounds = [0.0] + [b for b in beats if 0 < b < duration] + [duration]
    raw = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a < min_dur:
            continue
        mask = (times >= a) & (times < b)
        if not mask.any():
            continue
        v = chroma[:, mask].mean(axis=1)
        nv = np.linalg.norm(v)
        if nv < 1e-6:
            continue
        best_label, best_score = None, -1.0
        for root in range(12):
            for suffix, intervals in (("", (0, 4, 7)), ("m", (0, 3, 7))):
                tpl = np.zeros(12)
                for i in intervals:
                    tpl[(root + i) % 12] = 1.0
                score = float(np.dot(v, tpl) / (nv * np.linalg.norm(tpl)))
                if score > best_score:
                    best_score = score
                    best_label = f"{_NOTES[root]}{suffix}"
        raw.append({"start": round(a, 2), "end": round(b, 2), "chord": best_label, "score": round(best_score, 3)})

    merged = []
    for seg in raw:
        if merged and merged[-1]["chord"] == seg["chord"]:
            merged[-1]["end"] = seg["end"]
            merged[-1]["score"] = round((merged[-1]["score"] + seg["score"]) / 2, 3)
        else:
            merged.append(dict(seg))
    return merged


def estimate_melody(y, sr: int, max_seconds: float = 40.0) -> list:
    import librosa

    seg = y[: int(max_seconds * sr)]
    if len(seg) < sr:
        return []
    f0, voiced, _ = librosa.pyin(
        seg,
        fmin=float(librosa.note_to_hz("C3")),
        fmax=float(librosa.note_to_hz("C6")),
        sr=sr,
        frame_length=2048,
    )
    times = librosa.times_like(f0, sr=sr)
    notes, cur = [], None
    for t, f, v in zip(times, f0, voiced):
        if not v or not np.isfinite(f) or f <= 0:
            continue
        midi = int(round(float(librosa.hz_to_midi(f))))
        if cur and cur["midi"] == midi and (t - cur["end"]) < 0.12:
            cur["end"] = float(t)
        else:
            if cur:
                notes.append(cur)
            cur = {"start": float(t), "end": float(t), "midi": midi}
    if cur:
        notes.append(cur)
    out = []
    for n in notes:
        if n["end"] - n["start"] < 0.08:
            continue
        out.append(
            {
                "start": round(n["start"], 2),
                "end": round(n["end"], 2),
                "note": _NOTES[n["midi"] % 12] + str(n["midi"] // 12 - 1),
                "midi": n["midi"],
            }
        )
    return out


def _tempo_prior(y, sr: int, lo: float = 60.0, hi: float = 120.0):
    """用 tempogram 在 60–120 里挑最强峰，压住 librosa 的三连音误判。"""
    import librosa

    onset = librosa.onset.onset_strength(y=y, sr=sr)
    tg = librosa.feature.tempogram(onset_envelope=onset, sr=sr)
    freqs = librosa.tempo_frequencies(tg.shape[0], sr=sr)
    profile = tg.mean(axis=1)
    mask = (freqs >= lo) & (freqs <= hi)
    if not mask.any():
        return None
    return float(freqs[mask][int(np.argmax(profile[mask]))])


def analyze(
    path,
    with_beats: bool = True,
    with_chords: bool = False,
    with_melody: bool = False,
    melody_max: float = 40.0,
    engine: str = "librosa",
) -> dict:
    import librosa

    p = media_path(path)
    y, sr = librosa.load(str(p), sr=22050, mono=True)
    duration = len(y) / sr

    downbeats = None
    prior = None
    if engine == "beat-this":
        from beat_this.inference import File2Beats

        tracker = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
        raw_beats, raw_downbeats = tracker(str(p))
        beats = [round(float(b), 3) for b in raw_beats]
        downbeats = [round(float(b), 3) for b in raw_downbeats]
        if len(beats) > 1:
            tempo = float(60.0 / float(np.median(np.diff(beats))))
        else:
            tempo = 0.0
    else:
        prior = _tempo_prior(y, sr)
        tempo, beats = librosa.beat.beat_track(
            y=y, sr=sr, units="time", trim=False, start_bpm=prior if prior else 120.0
        )
        tempo = float(np.atleast_1d(tempo)[0]) if tempo is not None else 0.0
        beats = [round(float(b), 3) for b in beats]

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key = _key(chroma.mean(axis=1))

    rms = librosa.feature.rms(y=y)[0]
    dbfs = float(20 * math.log10(max(float(rms.mean()), 1e-9)))
    peak = float(20 * math.log10(max(float(np.abs(y).max()), 1e-9)))

    result = {
        "path": str(p),
        "duration": round(duration, 3),
        "sample_rate": 22050,
        "tempo_bpm": round(tempo, 2),
        "key": key,
        "loudness_dbfs": round(dbfs, 2),
        "peak_dbfs": round(peak, 2),
        "beat_count": len(beats),
        "beats": beats if with_beats else beats[:0],
        "engine": engine,
        "tempo_prior": round(prior, 2) if engine == "librosa" and prior else None,
        "downbeats": downbeats or [],
        "sections": _sections(y, sr),
        "note": "sections 是按能量突变粗分的近似段落，不是乐谱级结构",
    }
    if with_chords:
        result["chords"] = estimate_chords(y, sr, beats)
        result["chord_note"] = "按拍做模板匹配（大三/小三），不是深度学习和弦识别，转位与七和弦会判错"
    if with_melody:
        result["melody"] = estimate_melody(y, sr, melody_max)
        result["melody_note"] = f"pyin 单音高跟踪，只取前 {melody_max:g} 秒；复音/和声会串"
    return result
