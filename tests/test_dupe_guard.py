"""去重边界对规则测试（R30，2026-10-29）。

覆盖：三类风险信号（数字 / 否定词 / 长度比）、真重复改写不 risky（防误伤）、
空值安全、阈值可调。纯函数，零 IO 零 LLM。
"""

from __future__ import annotations

from knowatlas.pipeline.dupe_guard import is_risky, risk_signals


# ---- 数字差异（真库 6 对误并里的 3 对的形态） ----

def test_digit_difference_is_risky():
    a = ("在股票交易动态规划中，当交易次数上限 k 固定为 1 时，状态转移方程可化简为"
         " dp[i][0] = max(dp[i-1][0], dp[i-1][1] + prices[i])。")
    b = ("在股票交易动态规划中，当交易次数 k = 2 时，k 对状态转移的影响无法消除，"
         "状态转移方程必须保留 k 维度。")
    sigs = risk_signals(a, b)
    assert any(s.startswith("数字差异") for s in sigs)
    assert is_risky(a, b)


def test_complexity_difference_is_risky():
    a = "把 n 个数字划分到 k 个桶的回溯解法，时间复杂度上界为 o(k^n)。"
    b = "从桶的角度穷举，每个桶遍历 n 个数字，时间复杂度上界为 o(k*2^n)。"
    assert is_risky(a, b)


# ---- 否定词差异（「碎了」vs「没碎」） ----

def test_negation_difference_is_risky():
    a = "若在第 i 层楼扔鸡蛋后鸡蛋碎了，搜索楼层区间变为 [1..i-1]。"
    b = "若在第 i 层楼扔鸡蛋后鸡蛋没碎，搜索楼层区间变为 [i+1..n]。"
    sigs = risk_signals(a, b)
    assert any(s.startswith("否定词差异") for s in sigs)


# ---- 真重复改写不 risky（既不误伤 28 对既有真重复，也不误伤纯同义改写） ----

def test_paraphrase_not_risky():
    a = "Agent = LLM + 上下文 + 工具，三者构成智能体的基本结构。"
    b = "智能体的基本结构：Agent 等于大模型加上下文加工具的组合。"
    assert risk_signals(a, b) == []


def test_same_numbers_same_negation_not_risky():
    a = "归并排序的递归框架可视为二叉树后序遍历：先递归排序左右子数组，再合并两个有序子数组。"
    b = "归并排序的算法框架对应二叉树的后序遍历：先递归排序左右子数组，再合并有序子数组。"
    assert risk_signals(a, b) == []


# ---- 长度比（一条是另一条的扩写） ----

def test_length_ratio_signal():
    a = "最长递增子序列问题中，dp[i] 定义为以 nums[i] 结尾的最长递增子序列的长度。"
    b = "在最长递增子序列的动态规划解法中，dp[i] 定义为以 nums[i] 这个数结尾的最长递增子序列的长度，" \
        "且 dp[i] 的初始值为 1，因为每个数本身就是一个长度为一的递增子序列，转移时对所有 j < i 求最大值。"
    sigs = risk_signals(a, b)
    assert any(s.startswith("长度比") for s in sigs)
    # 阈值可调：放到 3.0 就不再是信号
    assert not any(s.startswith("长度比") for s in risk_signals(a, b, length_ratio=3.0))


# ---- 空值/边界 ----

def test_empty_and_identical_texts():
    assert risk_signals("", "") == []
    assert risk_signals("同一条知识", "同一条知识") == []
    # 空一侧不触发长度比（缺文本无法比较），只是不崩
    assert risk_signals("", "有正文的一侧") == []
    assert risk_signals(None, None) == []