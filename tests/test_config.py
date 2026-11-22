from pathlib import Path

from mediakit_cli.config import find_tool
from mediakit_cli.lyrics import _lrc_time
from mediakit_cli.ocr import _norm


def test_lrc_time_format():
    assert _lrc_time(0) == "[00:00.00]"
    assert _lrc_time(65.5) == "[01:05.50]"
    assert _lrc_time(-3) == "[00:00.00]"


def test_ocr_norm_strips_punctuation_and_space():
    assert _norm("大家，晚上好。") == "大家晚上好"
    assert _norm(" hello, world ") == "helloworld"


def test_find_tool_respects_env_var(tmp_path: Path, monkeypatch):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("MEDIAKIT_FFMPEG", str(fake))
    assert find_tool("ffmpeg") == str(fake)


def test_find_tool_returns_none_for_unknown(monkeypatch):
    monkeypatch.delenv("MEDIAKIT_NOT_A_TOOL", raising=False)
    assert find_tool("definitely-not-a-real-tool-123") is None
