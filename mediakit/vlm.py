from __future__ import annotations

import base64
import json
import re
import urllib.request
from pathlib import Path

from .config import ollama_base, ollama_chat_url, vlm_model

PROMPT = (
    "你是分镜分析助手。看这张视频截图，只输出一个 JSON 对象，不要解释、不要代码块：\n"
    '{"shot_size":"远景/全景/中景/近景/特写 之一",'
    '"camera":"平视/俯视/仰视/倾斜 之一",'
    '"motion":"静止/轻微/明显 之一",'
    '"mood":"一个中文词",'
    '"caption":"不超过20个字的中文画面描述"}'
)


def _opener():
    # Local loopback must bypass any configured proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post(payload: dict, endpoint: str, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with _opener().open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return {"raw": text[:300]}


def describe_image(
    image_path,
    model: str | None = None,
    endpoint: str | None = None,
    timeout: int = 180,
) -> dict:
    model = model or vlm_model()
    endpoint = endpoint or ollama_chat_url()
    p = Path(image_path)
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 300,
        "temperature": 0.2,
        "stream": False,
    }
    data = _post(payload, endpoint, timeout=timeout)
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    result = _parse_json(text)
    result["model"] = model
    return result


def available(model: str | None = None) -> bool:
    model = model or vlm_model()
    try:
        req = urllib.request.Request(ollama_base().rsplit("/v1", 1)[0] + "/api/tags")
        with _opener().open(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return any(m.get("name", "").startswith(model) for m in data.get("models", []))
    except Exception:
        return False
