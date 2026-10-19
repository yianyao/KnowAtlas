"""ids.py 契约测试（完整方案 §3.3：跟踪参数、尾斜杠、query 排序、hash 规范化、防碰撞）。"""

from __future__ import annotations

from knowatlas.ids import canonical_url, content_hash, entry_id, normalize_text


def test_canonical_strips_tracking_and_fragment():
    url = "HTTPS://www.Example.com/a/?utm_source=x&b=2&utm_campaign=y#frag"
    assert canonical_url(url) == "https://www.example.com/a?b=2"


def test_canonical_sorts_query_and_keeps_blank_values():
    assert canonical_url("https://e.com/?b=2&a=1&c=") == "https://e.com/?a=1&b=2&c="


def test_canonical_strips_trailing_slash_but_keeps_root():
    assert canonical_url("https://e.com/x/") == "https://e.com/x"
    assert canonical_url("https://e.com/") == "https://e.com/"


def test_canonical_strips_default_port():
    assert canonical_url("https://e.com:443/x") == "https://e.com/x"
    assert canonical_url("http://e.com:8080/x") == "http://e.com:8080/x"


def test_canonical_rejects_non_http():
    assert canonical_url("file://docs/a.md") is None
    assert canonical_url("ftp://e.com/x") is None


def test_content_hash_normalizes_whitespace_and_blank_lines():
    a = "标题\r\n\r\n\r\n正文  \n  缩进\n"
    b = "标题\n\n正文\n缩进"
    assert normalize_text(a) == normalize_text(b)
    assert content_hash(a) == content_hash(b)


def test_entry_id_stable_and_collision_resistant():
    assert entry_id("manual", "https://e.com/a") == entry_id("manual", "https://e.com/a")
    # \x1f 分隔符防碰撞：("a","b|c") 与 ("a|b","c") 必须不同
    assert entry_id("a", "b|c") != entry_id("a|b", "c")


def test_entry_id_format():
    eid = entry_id("manual", "https://e.com/a")
    assert len(eid) == 16
    int(eid, 16)  # 必须是十六进制
