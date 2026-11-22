from __future__ import annotations

from pathlib import Path

from .util import ffprobe_json, media_path


def _fraction_to_float(text: str) -> float:
    try:
        num, _, den = (text or "0/1").partition("/")
        n, d = float(num or 0), float(den or 1)
        return n / d if d else 0.0
    except Exception:
        return 0.0


def _probe_av(path: Path) -> dict:
    import av

    with av.open(str(path)) as container:
        duration = float(container.duration / av.time_base) if container.duration else 0.0
        video = audio = None
        for st in container.streams:
            if st.type == "video" and video is None:
                video = {
                    "codec": st.codec_context.name,
                    "width": st.codec_context.width,
                    "height": st.codec_context.height,
                    "fps": round(float(st.average_rate or 0), 3),
                    "pix_fmt": st.codec_context.pix_fmt,
                    "frames": int(st.frames or 0),
                }
            elif st.type == "audio" and audio is None:
                audio = {
                    "codec": st.codec_context.name,
                    "sample_rate": st.codec_context.sample_rate,
                    "channels": st.codec_context.channels,
                }
        return {
            "path": str(path),
            "duration": round(duration, 3),
            "size_bytes": path.stat().st_size,
            "format": None,
            "bit_rate": 0,
            "video": video,
            "audio": audio,
        }


def probe(path) -> dict:
    p = media_path(path)
    data = ffprobe_json(p)
    if not data:
        return _probe_av(p)

    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    result = {
        "path": str(p),
        "duration": round(float(fmt.get("duration") or 0), 3),
        "size_bytes": int(fmt.get("size") or p.stat().st_size),
        "format": fmt.get("format_name"),
        "bit_rate": int(fmt.get("bit_rate") or 0),
        "video": None,
        "audio": None,
    }
    if video:
        result["video"] = {
            "codec": video.get("codec_name"),
            "width": video.get("width"),
            "height": video.get("height"),
            "fps": round(_fraction_to_float(video.get("avg_frame_rate") or video.get("r_frame_rate")), 3),
            "pix_fmt": video.get("pix_fmt"),
            "frames": int(video.get("nb_frames") or 0),
        }
    if audio:
        result["audio"] = {
            "codec": audio.get("codec_name"),
            "sample_rate": int(audio.get("sample_rate") or 0),
            "channels": int(audio.get("channels") or 0),
        }
    return result


def has_audio(info: dict) -> bool:
    return bool(info.get("audio"))
