"""pipeline/sync/flags.py（拆分产物）。"""

# 拆分自 pipeline/sync.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


from datetime import datetime
from typing import Any
from ...models import Entry, FetchResult


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _flag_value(dl: Any, entry: Entry, out: Any) -> bool:
    """把「非知识」结论落进 meta（value_flag=not_knowledge + value_flag_reason）。

    tag 来源两条路：L0 价值守卫（value_guard，结构性规则，带 reason）与 LLM
    kind=non（classify_deep，语义判断，无 reason）——统一经本函数落库，语义同构。
    返回是否本次新标记（已标记 / 用户已否决 value_flag=ok 的不重复写）。
    用户否决以**库中** meta 为准（采集器产出的 entry.meta 不含后处理键，
    同步路径必须读库才能看到 Web UI 里点过的「是知识，保留」）。
    保留决定权在用户：仅标记，不自动舍弃（not_knowledge 只进待清理候选）。
    """
    if "not_knowledge" not in out.tags:
        return False
    current = dl.get_entry(entry.id)
    if current is not None and current.meta.get("value_flag") == "ok":
        return False  # 用户已否决——机器结论不再覆盖人的决定
    reason = next((t.split(":", 1)[1] for t in out.tags
                   if t.startswith("value_reason:")), None)
    if current is not None and current.meta.get("value_flag") == "not_knowledge":
        if reason and current.meta.get("value_flag_reason") != reason:
            dl.merge_meta(entry.id, {"value_flag_reason": reason})  # 旧 LLM 标记补原因
        return False
    patch: dict[str, Any] = {"value_flag": "not_knowledge"}
    if reason:
        patch["value_flag_reason"] = reason
    dl.merge_meta(entry.id, patch)
    return True
