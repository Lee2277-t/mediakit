"""不用耳朵裁决节拍器：比较「拍点是否落在音符起始上」以及节拍间隔的稳定性。"""

from __future__ import annotations

import sys
from pathlib import Path

import librosa
import numpy as np
from scipy.signal import find_peaks

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def salience(onset: np.ndarray, frames: np.ndarray, beats) -> float:
    beats = np.asarray(beats, dtype=float).ravel()
    if beats.size == 0:
        return 0.0
    idx = np.clip(np.searchsorted(frames, beats), 0, len(onset) - 1)
    return float(onset[idx].mean() / (onset.mean() + 1e-9))


def stability(beats) -> float:
    beats = np.asarray(beats, dtype=float).ravel()
    if len(beats) < 3:
        return 99.0
    d = np.diff(np.asarray(beats))
    return float(np.std(d) / (np.mean(d) + 1e-9))


def top_tempos(onset: np.ndarray, sr: int, lo: float = 50, hi: float = 200) -> list:
    tg = librosa.feature.tempogram(onset_envelope=onset, sr=sr)
    freqs = librosa.tempo_frequencies(tg.shape[0], sr=sr)
    profile = tg.mean(axis=1)
    mask = (freqs >= lo) & (freqs <= hi)
    peaks, _ = find_peaks(profile[mask], distance=3)
    sub_freqs = freqs[mask][peaks]
    sub_vals = profile[mask][peaks]
    order = np.argsort(-sub_vals)[:5]
    return [(round(float(sub_freqs[i]), 1), round(float(sub_vals[i]), 3)) for i in order]


def main() -> int:
    path = sys.argv[1]
    y, sr = librosa.load(path, sr=22050, mono=True)
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    frames = librosa.times_like(onset, sr=sr)

    tempo_l, beats_l = librosa.beat.beat_track(y=y, sr=sr, units="time", trim=False)
    beats_l = [float(b) for b in beats_l]
    tempo_l = float(np.atleast_1d(tempo_l)[0])

    tempo_s, beats_s = librosa.beat.beat_track(y=y, sr=sr, units="time", trim=False, start_bpm=79)
    tempo_s = float(np.atleast_1d(tempo_s)[0])
    beats_s = [float(b) for b in beats_s]

    from beat_this.inference import File2Beats

    f2b = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
    raw, db = f2b(path)
    beats_b = [float(b) for b in raw]

    print(f"\n{Path(path).name}  ({len(y)/sr:.1f}s)")
    print(f"  自动相关前 5 峰 (BPM, 强度): {top_tempos(onset, sr)}")
    print(f"  librosa 默认        {tempo_l:6.2f} BPM  {len(beats_l):3d} 拍  "
          f"落点强度 {salience(onset, frames, beats_l):.2f}  间隔不稳 {stability(beats_l):.3f}")
    print(f"  librosa start=79    {tempo_s:6.2f} BPM  {len(beats_s):3d} 拍  "
          f"落点强度 {salience(onset, frames, beats_s):.2f}  间隔不稳 {stability(beats_s):.3f}")
    print(f"  beat_this           {60/np.median(np.diff(beats_b)):6.2f} BPM  {len(beats_b):3d} 拍  "
          f"落点强度 {salience(onset, frames, beats_b):.2f}  间隔不稳 {stability(beats_b):.3f}  强拍 {len(db)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
