from mediakit_cli.subs import display_len, lines_from_words, quality_report


def _w(text, start, end):
    return {"text": text, "start": start, "end": end}


def test_display_len_counts_cjk_as_one():
    assert display_len("你好") == 2
    assert display_len("ab") == 1.1
    assert display_len("。") == 0.3


def test_lines_from_words_splits_on_pause():
    words = [
        _w("大家", 0.0, 0.4),
        _w("晚上好。", 0.4, 1.4),
        _w("今天", 2.0, 2.4),
        _w("聊三件事。", 2.4, 3.6),
    ]
    lines = lines_from_words(words, max_chars=16, pause=0.3)
    assert len(lines) == 2
    assert lines[0]["text"] == "大家晚上好。"
    assert lines[1]["start"] >= lines[0]["end"]


def test_lines_never_overlap_and_are_ordered():
    words = [_w(f"词{i}", i * 0.6, i * 0.6 + 0.5) for i in range(20)]
    lines = lines_from_words(words, max_chars=6, pause=0.1)
    for prev, cur in zip(lines, lines[1:]):
        assert cur["start"] >= prev["end"]


def test_quality_report_flags_short_and_crowded_lines():
    lines = [
        {"text": "这就是一句正常长度的话", "start": 0.0, "end": 2.0},
        {"text": "短", "start": 2.0, "end": 2.2},
        {"text": "这一句塞了太多字根本来不及读", "start": 2.1, "end": 2.4},
    ]
    report = quality_report(lines)
    kinds = {issue["type"] for issue in report["issues"]}
    assert "short" in kinds
    assert "cps" in kinds or "width" in kinds
    assert report["ok"] is False
