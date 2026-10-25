from kpe.validate import dedupe, gate_reasons, parse_points, quote_ok


def test_parse_points_fenced_and_array() -> None:
    pts, err = parse_points('```json\n{"points": [{"text": "甲", "quote": "乙"}]}\n```')
    assert err == "" and pts[0]["text"] == "甲"
    pts, err = parse_points('[{"text": "丙"}]')
    assert err == "" and pts[0]["text"] == "丙"
    pts, err = parse_points("not json")
    assert pts == [] and err


def test_quote_ok_normalizes_punctuation() -> None:
    chunk = "心智社会理论的核心在于不存在中央控制器。这一思想被 MAS 领域继承。"
    assert quote_ok("心智社会理论的核心在于不存在中央控制器", chunk)
    assert quote_ok("心智社会理论的核心在于不存在中央控制器：这一思想被MAS领域继承", chunk)
    assert not quote_ok("完全无关的一句话内容", chunk)


def test_gate_reasons() -> None:
    assert "too_short" in gate_reasons("太短")
    assert "bad_start" in gate_reasons("本章介绍了智能体的基本概念与工程实践")
    assert "truncated" in gate_reasons("第一步先做甲，第二步……")
    assert gate_reasons("CoT 是一种通过中间推理步骤提升多步推理的提示技术。") == []


def test_dedupe() -> None:
    pts = [{"text": "甲 乙"}, {"text": "甲乙"}, {"text": "丙"}]
    assert len(dedupe(pts)) == 2