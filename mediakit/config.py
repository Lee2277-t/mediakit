"""Runtime configuration: tool discovery and local model endpoints.

Everything is overridable by environment variable so the package does not
depend on any particular machine layout.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# tool name -> environment variable that points at the executable
ENV_VARS = {
    "ffmpeg": "MEDIAKIT_FFMPEG",
    "ffprobe": "MEDIAKIT_FFPROBE",
    "audio-separator": "MEDIAKIT_AUDIO_SEPARATOR",
    "videocaptioner": "MEDIAKIT_VIDEOCAPTIONER",
}


def find_tool(name: str, env_var: str | None = None):
    """Locate an executable: explicit env var, PATH, then a few common dirs."""
    env_var = env_var or ENV_VARS.get(name)
    if env_var:
        raw = os.environ.get(env_var)
        if raw:
            p = Path(raw).expanduser()
            if p.is_file():
                return str(p)
            # allow pointing at a bin directory
            for candidate in (p / name, p / (name + ".exe")):
                if candidate.is_file():
                    return str(candidate)

    exe = name if name.lower().endswith(".exe") else name + ".exe"
    found = shutil.which(name) or shutil.which(exe)
    if found:
        return found

    home = Path.home()
    candidates = [
        home / ".dsh" / "bin" / exe,
        home / ".local" / "bin" / name,
        Path("/usr/local/bin") / name,
        Path("/opt/homebrew/bin") / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def ollama_base() -> str:
    """OpenAI-compatible base URL, without the trailing /chat/completions."""
    return os.environ.get("MEDIAKIT_OLLAMA_BASE", "http://127.0.0.1:11434/v1").rstrip("/")


def ollama_chat_url() -> str:
    return ollama_base() + "/chat/completions"


def vlm_model() -> str:
    return os.environ.get("MEDIAKIT_VLM_MODEL", "qwen3-vl:4b-instruct")


def whisper_model() -> str:
    return os.environ.get("MEDIAKIT_WHISPER_MODEL", "small")
