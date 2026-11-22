from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from .util import ensure_dir, ffmpeg

_MODEL = None
_PREPROCESS = None
_TOKENIZER = None


def _load_model():
    global _MODEL, _PREPROCESS, _TOKENIZER
    if _MODEL is None:
        import open_clip

        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k"
        )
        model.eval()
        _MODEL = model
        _PREPROCESS = preprocess
        _TOKENIZER = open_clip.get_tokenizer("ViT-B-32")
    return _MODEL, _PREPROCESS, _TOKENIZER


def build_index(video, out_dir, every: float = 2.0, max_frames: int = 150, progress=None) -> dict:
    import torch
    from PIL import Image

    note = progress or (lambda *_: None)
    out = ensure_dir(out_dir)
    frames_dir = ensure_dir(out / "frames")
    every = max(float(every), 0.5)
    note(f"抽帧：每 {every}s 一帧，最多 {max_frames} 帧")
    ffmpeg(
        "-i", video,
        "-vf", f"fps={1.0 / every:.6f}",
        "-frames:v", str(max_frames),
        "-q:v", "3",
        str(frames_dir / "%05d.jpg"),
    )
    paths = sorted(frames_dir.glob("*.jpg"))
    if not paths:
        raise RuntimeError("没有抽到帧")

    note(f"加载 CLIP 模型（首次会下载约 350MB）")
    model, preprocess, _ = _load_model()
    note(f"编码 {len(paths)} 帧")
    chunks = []
    with torch.no_grad():
        for i in range(0, len(paths), 8):
            batch = [preprocess(Image.open(p).convert("RGB")) for p in paths[i:i + 8]]
            emb = model.encode_image(torch.stack(batch))
            emb = emb / emb.norm(dim=-1, keepdim=True)
            chunks.append(emb.cpu().numpy().astype(np.float32))
            if i % 32 == 0:
                note(f"编码 {min(i + 8, len(paths))}/{len(paths)}")
    embeds = np.concatenate(chunks, axis=0)
    times = np.array([round(i * every, 3) for i in range(len(paths))], dtype=np.float32)

    np.savez_compressed(out / "index.npz", embeds=embeds, times=times)
    meta = {
        "video": str(Path(video).resolve()),
        "frames": len(paths),
        "every": every,
        "model": "ViT-B-32/laion2b_s34b_b79k",
        "thumbs": [str(p) for p in paths],
    }
    (out / "index.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"index": str(out / "index.npz"), "frames": len(paths), "every": every, "model": meta["model"]}


def search(index_dir, query: str, topk: int = 5) -> dict:
    import torch

    d = Path(index_dir)
    data = np.load(d / "index.npz")
    meta = json.loads((d / "index.json").read_text(encoding="utf-8"))
    model, _, tokenizer = _load_model()
    with torch.no_grad():
        tokens = tokenizer([query])
        text = model.encode_text(tokens)
        text = text / text.norm(dim=-1, keepdim=True)
    sims = data["embeds"] @ text.cpu().numpy().T
    sims = sims.reshape(-1)
    order = np.argsort(-sims)[: max(1, topk)]
    hits = []
    for idx in order:
        hits.append(
            {
                "t": round(float(data["times"][idx]), 2),
                "score": round(float(sims[idx]), 4),
                "thumb": meta["thumbs"][int(idx)] if int(idx) < len(meta["thumbs"]) else None,
            }
        )
    return {"query": query, "video": meta.get("video"), "hits": hits, "frames": meta.get("frames")}
