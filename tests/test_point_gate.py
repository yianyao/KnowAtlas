"""知识点自洽性闸门测试（TODO 8.5，2026-10-24）。

覆盖：7 个原因码逐条（过短/裸名词/步骤缺首/跳号/缺尾/尾部截断/代码块未闭合）
+ 正例零误杀（短数据、单句术语定义、完整步骤、含代码块、产品枚举与版本号）。
真实库 27 点的零误杀由 `temp/point_gate_probe.py` 探针复核，固化为本文件
中的同类样本（"Gemini 3、Claude 4.8" 曾把枚举误判成步骤）。
"""

from __future__ import annotations

import pytest

from knowatlas.pipeline.point_gate import (
    GATE_REASONS, MIN_POINT_CHARS, GateResult, gate_point,
)


def _reason(text: str) -> str:
    r = gate_point(text)
    return "" if r.ok else r.reason


# ---- 过短 ----

@pytest.mark.parametrize("text", ["", "   ", "点。", "短词", "\n\t\n"])
def test_too_short(text):
    assert _reason(text) == "too_short"


def test_min_length_boundary_passes():
    """长度下限只拦碎片：恰好达到下限且有句读的术语描述放行。"""
    text = "节" * (MIN_POINT_CHARS - 1) + "。"
    assert gate_point(text) == GateResult(True, "")


# ---- 裸名词 ----

@pytest.mark.parametrize("text", [
    "JavaScript 数组",
    "TCP 三次握手与四次挥手",
    "SQLite 索引 覆盖索引 回表",
])
def test_bare_noun_rejected(text):
    assert _reason(text) == "bare_noun"


@pytest.mark.parametrize("text", [
    "M3 Max 内存带宽 400GB/s。",                       # 独立数据
    "闭包是由引用环境与函数代码组成的实体。",              # 术语描述
    "SQLite 慢查询排查：先 EXPLAIN QUERY PLAN 看计划，再补统计信息 ANALYZE。",
])
def test_valid_forms_pass(text):
    assert gate_point(text).ok


# ---- 步骤完整性 ----

def test_complete_steps_pass():
    assert gate_point("1）安装依赖；2）配置环境变量；3）启动服务并验证。").ok
    assert gate_point("第一步安装依赖；第二步配置环境；第三步启动服务。").ok
    assert gate_point("两种方案：1）全量重灌；2）增量补抓。").ok


def test_steps_head_missing():
    """只有中间/后段步骤：缺首步（用户裁决原话「步骤被截断」）。"""
    assert _reason("2）打开设置面板；3）勾选自动更新；4）重启客户端。") == \
        "steps_head_missing"


def test_steps_gap():
    assert _reason("1）安装依赖；2）配置环境；4）启动服务。") == "steps_gap"


def test_steps_tail_missing():
    """步骤列表没有句末标点收尾 = 末步被切掉。"""
    assert _reason("1）安装依赖；2）配置环境变量；3）启动服务") == \
        "steps_tail_missing"


def test_truncated_tail_marker():
    assert _reason("1）安装依赖；2）配置环境变量；3）启动服务…") == \
        "truncated_tail"
    assert _reason("SQLite 慢查询需要先看执行计划，再补统计信息，然后…") == \
        "truncated_tail"
    assert _reason("这段正文写到一半就被截断了……[截断]") == "truncated_tail"


# ---- 代码块 ----

def test_code_fence_unclosed():
    assert _reason("示例代码如下：\n```python\nprint(1)\n") == \
        "code_fence_unclosed"


def test_closed_code_fence_passes():
    text = "用如下代码开启 WAL：\n```python\nconn.execute('PRAGMA journal_mode=WAL')\n```"
    assert gate_point(text).ok


# ---- 误报防护（真实库踩过的类）----

@pytest.mark.parametrize("text", [
    "国外产品包括 Gemini 3、Claude 4.8、Llama 4 与 Grok 4.3。",
    "Python 3.13 与 Vue 3.5 都发布于 2024 年。",
    "版本 1.2 修复了 3 个问题，见 2026.10 的更新日志。",
])
def test_enumeration_and_versions_are_not_steps(text):
    assert gate_point(text).ok


# ---- 原因码契约 ----

def test_reason_codes_are_exported():
    assert set(GATE_REASONS) == {
        "too_short", "bare_noun", "steps_head_missing", "steps_gap",
        "steps_tail_missing", "truncated_tail", "code_fence_unclosed"}
    for text in ("JavaScript 数组", "2）a；3）b。"):
        r = gate_point(text)
        assert r.reason in GATE_REASONS and not r.ok