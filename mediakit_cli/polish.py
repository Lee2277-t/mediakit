from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import find_tool, ollama_base, vlm_model
from .util import media_path

# Local loopback calls must not go through a proxy: some environments set a
# NO_PROXY entry that httpx cannot parse ("Invalid port").
_PROXY_KEYS = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k.lower() not in _PROXY_KEYS}


def _exe():
    return find_tool("videocaptioner", "MEDIAKIT_VIDEOCAPTIONER")


def available() -> bool:
    return _exe() is not None


def polish(
    src,
    out,
    model: str | None = None,
    endpoint: str | None = None,
    api_key: str = "ollama",
    max_cjk: int = 16,
    split: bool = True,
    optimize: bool = True,
) -> dict:
    exe = _exe()
    if not exe:
        raise RuntimeError(
            "没找到 VideoCaptioner：装好它，或把 MEDIAKIT_VIDEOCAPTIONER 指向 videocaptioner 可执行文件"
        )
    model = model or vlm_model()
    endpoint = endpoint or ollama_base()
    src_path = media_path(src)
    out_path = Path(out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        "subtitle",
        str(src_path),
        "--api-base", endpoint,
        "--api-key", api_key,
        "--model", model,
        "-o", str(out_path),
        "--max-cjk", str(max_cjk),
    ]
    if not split:
        cmd.append("--no-split")
    if not optimize:
        cmd.append("--no-optimize")

    p = subprocess.run(
        cmd,
        env=_clean_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    if p.returncode != 0 or not out_path.exists():
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-4:]
        raise RuntimeError("VideoCaptioner 失败: " + " | ".join(tail))

    text = out_path.read_text(encoding="utf-8", errors="replace")
    blocks = [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip() and "-->" in b]
    return {
        "in": str(src_path),
        "out": str(out_path),
        "model": model,
        "endpoint": endpoint,
        "lines": len(blocks),
        "bytes": out_path.stat().st_size,
        "stderr_tail": (p.stderr or "").strip().splitlines()[-2:],
    }
