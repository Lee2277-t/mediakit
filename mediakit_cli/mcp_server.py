"""MCP server exposing mediakit as agent tools.

Run `mediakit-mcp` to serve over stdio. Each tool returns a JSON-serializable
dict; heavy dependencies are imported lazily so the server starts fast.
"""

from __future__ import annotations

from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP as _Server  # mcp < 2
except ImportError:  # mcp >= 2 renamed FastMCP to MCPServer
    try:
        from mcp.server.mcpserver import MCPServer as _Server
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "The MCP server needs the optional dependency: pip install 'mediakit-cli[mcp]'"
        ) from exc

mcp = _Server("mediakit")


@mcp.tool()
def probe(path: str) -> dict:
    """Read container/codec/duration metadata for a media file."""
    from .probe import probe as _probe

    return _probe(path)


@mcp.tool()
def shots(path: str, threshold: float = 27.0, min_seconds: float = 0.5) -> dict:
    """Detect shot boundaries and return their timecodes."""
    from .shots import detect_shots

    shots_list = detect_shots(path, threshold=threshold, min_seconds=min_seconds)
    return {"path": path, "count": len(shots_list), "shots": shots_list}


@mcp.tool()
def music(path: str, chords: bool = False, melody: bool = False, engine: str = "librosa") -> dict:
    """Analyze tempo, beats, key, loudness, sections; optionally chords/melody."""
    from .music import analyze

    return analyze(path, with_chords=chords, with_melody=melody, engine=engine)


@mcp.tool()
def subs(
    path: str,
    out_dir: str,
    lang: str | None = None,
    model: str = "small",
    max_chars: float = 16.0,
    size: str = "1920x1080",
    karaoke: bool = False,
) -> dict:
    """Transcribe speech into SRT/ASS with pause-aware line breaking."""
    from .subs import build_lines, transcribe, write_subtitles

    width, height = (int(x) for x in size.lower().split("x"))
    asr = transcribe(path, language=lang, model=model)
    lines = build_lines(asr, max_chars=max_chars)
    files = write_subtitles(
        lines, out_dir, formats=("srt", "ass"), resolution=(width, height), karaoke=karaoke
    )
    return {"path": path, "language": asr["language"], "lines": len(lines), "files": files}


@mcp.tool()
def ocr(path: str, out_dir: str, every: float = 2.0, max_frames: int = 60) -> dict:
    """Read on-screen text (hardcoded subtitles, lyrics, screen recordings)."""
    from .ocr import ocr_video

    return ocr_video(path, every=every, max_frames=max_frames)


@mcp.tool()
def shotcard(path: str, out_dir: str, vlm: bool = False, max_shots: int | None = None) -> dict:
    """Per-shot brightness, saturation, dominant colors, motion; optional VLM captions."""
    from .shotcard import analyze

    return analyze(path, out_dir, max_shots=max_shots, use_vlm=vlm)


@mcp.tool()
def index(path: str, out_dir: str, every: float = 2.0, max_frames: int = 150) -> dict:
    """Build a CLIP index over frames so the video can be searched by sentence."""
    from .index import build_index

    return build_index(path, out_dir, every=every, max_frames=max_frames)


@mcp.tool()
def search(index_dir: str, query: str, top: int = 5) -> dict:
    """Search a CLIP index with a natural-language sentence."""
    from .index import search as _search

    return _search(index_dir, query, topk=top)


@mcp.tool()
def lyrics(path: str, out_dir: str, lang: str | None = None, separate: bool = False) -> dict:
    """Transcribe song lyrics to SRT/ASS/LRC; optionally separate vocals first."""
    from .lyrics import make_lyrics

    return make_lyrics(path, out_dir, lang=lang, separate=separate)


@mcp.tool()
def dub(path: str, srt: str, out: str, voice: str | None = None, mix_original: bool = False) -> dict:
    """Dub subtitles with local Windows SAPI voices (Windows only)."""
    from .dub import dub as _dub

    return _dub(path, srt, out, voice_name=voice, mix_original=mix_original)


@mcp.tool()
def edit(plan_path: str, out: str) -> dict:
    """Render an edit plan (clips, subtitles, music, transitions, beat sync)."""
    import json

    from .edit import render

    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    return render(plan, out)


@mcp.tool()
def auto(
    music_path: str,
    src_dir: str,
    out: str,
    size: str = "1080x1920",
    fit: str = "crop",
    seed: int = 7,
    transition: str | None = None,
    plan_only: bool = False,
) -> dict:
    """Beat-synced montage from a music track and a folder of footage."""
    from .auto import generate

    width, height = (int(x) for x in size.lower().split("x"))
    return generate(
        music_path,
        [src_dir],
        out,
        size=(width, height),
        fit=fit,
        seed=seed,
        transition=transition,
        plan_only=plan_only,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
