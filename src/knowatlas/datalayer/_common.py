"""datalayer 共享常量与纯函数助手（拆分自 db.py，行为逐字不变）。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

# 老化删除出口冷却期（方案 §7.5 用户裁决第 4 条：人裁废弃→即刻 rejected→
# 30 天冷却→自动物理删除；冷却期=误裁反悔窗口）
REJECT_COOLING_DAYS = 30

_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_ORIGINS = ("prior", "rule", "embedding", "llm", "manual")

# IN (...) 批量读的分片大小（SQLite 变量上限 999；留余量，且单条 SQL 不宜过长）
_IN_CHUNK = 400

# 「转正」动作：pending→active 走 web 批量转正（bulk_activate），rejected→active
# 走恢复（restore）。fetch 候选的「刚转正优先」就读这两类 task_log（见
# activation_times）——不改表、不新增 meta 键。
_ACTIVATION_ACTIONS = ("bulk_activate", "restore")


def _consumable(alias: str = "e") -> str:
    """消费面守卫 SQL 片段（0.2.0 第三十六批，带前导 AND）。

    知识消费页（关系图/召回/检索/线索）只出「可消费」条目：
    status='active'（调用方既有条件）+ 非待清理（value_flag!=not_knowledge）
    + 非永久失效（link_status!=dead；error=疑似临时不判死）
    + 非去重副条目（dedupe_master 为空；第三十八批：跨源合并后由主条目代表）
    + 非明确过期（freshness_flag!=stale；第四十一批：suspect 仅标记保留可见）。
    管理页（待清理候选/时效候选/失效链接/归档检索）不走本片段，照常全量列出。
    Python 侧同口径判定在 pipeline/dedupe.py::_is_consumable，改动须两处同步。
    """
    return (f" AND COALESCE(json_extract({alias}.meta,'$.value_flag'),'ok')!='not_knowledge'"
            f" AND COALESCE(json_extract({alias}.meta,'$.link_status'),'ok')!='dead'"
            f" AND COALESCE(json_extract({alias}.meta,'$.dedupe_master'),'')=''"
            f" AND COALESCE(json_extract({alias}.meta,'$.freshness_flag'),'ok')!='stale'")


def _parse_iso(raw: Any) -> datetime | None:
    """ISO 时间串 → aware datetime；空串/坏串/非串一律 None（调用方按「最老」处理）。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


# 点级语义去重副点退出消费面（批次 94，条目级 dedupe_master 的点层对应物）：
# dupe_of 指向组内保留点——可逆标记（清 meta 即恢复），溯源指针永不动。
# 消费面 SQL（search_points/get_point_hit/cloud_point_data/cloud_facet_points）
# 均带 COALESCE(json_extract(p.meta,'$.dupe_of'),'')=''' 守卫，新增消费面须同步。
# H3 覆盖纪律：upsert 的 UPDATE 只含源拥有的字段；status 与人工校正永不覆盖。
# meta 浅合并（第十八批）：源键覆盖旧值，源不设置的键（机器/人工后处理，如
# value_flag / link_status / manual_*）原样保留——否则同步会抹掉后处理结论。
# 点层同理（P0，2026-10-25）：points.meta 的 kind/kind_why/kind_at/kind_model 是
# 分诊后处理结论（change ticket 变更工单-2026-10-25-点分诊.md），永不加进
# _SOURCE_FIELDS；点 meta 只有 merge_meta_of_point 的浅合并入口。
# 同理 points_pending_kpe（P3，2026-10-26：长文待 kpe 分块的标记，变更工单-2026-10-26-P3点层取全文.md）
# 与 points_gate（自洽性闸门阻断）——都是后处理键，永不进 _SOURCE_FIELDS。
_SOURCE_FIELDS = (
    "title", "locator", "locator_canonical", "native_path",
    "inline_content", "content_hash", "created_at",
)
_PATHS_CTE = """
WITH RECURSIVE paths(id, path) AS (
    SELECT c.id, c.name FROM categories c
    WHERE NOT EXISTS (SELECT 1 FROM category_parents cp WHERE cp.category_id = c.id)
    UNION ALL
    SELECT cp.category_id, p.path || '/' || c.name
    FROM paths p
    JOIN category_parents cp ON cp.parent_id = p.id
    JOIN categories c ON c.id = cp.category_id
)
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _meta_json(meta: dict[str, Any]) -> str:
    return json.dumps(meta, ensure_ascii=False, sort_keys=True)

