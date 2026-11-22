from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .config import find_tool


def _bootstrap_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_bootstrap_stdout()


FFMPEG = find_tool("ffmpeg")
FFPROBE = find_tool("ffprobe")


def run_cmd(args, timeout: int = 3600):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def ffmpeg(*args, timeout: int = 3600, cwd=None):
    if not FFMPEG:
        raise RuntimeError("找不到 ffmpeg：请安装后把 bin 目录加进 PATH")
    p = subprocess.run(
        [str(a) for a in [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )
    if p.returncode != 0:
        tail = (p.stderr or "").strip().splitlines()[-6:]
        raise RuntimeError("ffmpeg 失败: " + " | ".join(tail))
    return p


def ffprobe_json(path):
    if not FFPROBE:
        return None
    p = run_cmd(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    )
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except Exception:
        return None


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def out_json(obj) -> None:
    sys.stdout.write(dumps(obj) + "\n")
    sys.stdout.flush()


def ensure_dir(path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def media_path(path, must_exist: bool = True) -> Path:
    p = Path(path).expanduser().resolve()
    if must_exist and not p.exists():
        raise FileNotFoundError(f"找不到文件: {p}")
    return p


def grab_frame(src, t_sec: float, dst, width: int = 960) -> Path:
    dst = Path(dst)
    ensure_dir(dst.parent)
    ffmpeg(
        "-ss", f"{max(t_sec, 0):.3f}",
        "-i", src,
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", "3",
        dst,
    )
    return dst


def human_duration(sec: float) -> str:
    sec = float(sec or 0)
    m, s = divmod(sec, 60)
    h, m = divmod(int(m), 60)
    if h:
        return f"{h}:{m:02d}:{s:05.2f}"
    return f"{m:.0f}:{s:05.2f}"
