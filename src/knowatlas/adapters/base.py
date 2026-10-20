"""SourceAdapter 协议与 AdapterOutput（完整方案 §2）。

纪律：适配器绝不抓网页、绝不分类、绝不清洗正文，只做"翻译"——
读取原始形态 → 输出统一条目列表（抓取由 fetchers 在 pipeline 层完成）。

另含跨源共享的路径模式匹配工具（0.2.0 第十五批）：目录/文件排除规则供 folder 及
将来的 maildir 附件目录、会话记录产物目录、聊天记录导出目录共用。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..models import Entry


def match_path_pattern(pattern: str, name: str, rel: str) -> bool:
    """跨平台一致的排除模式匹配（不直接用 fnmatch 匹 rel 字符串）。

    为什么不用 fnmatch：Windows 上 fnmatch.fnmatch 先做 os.path.normcase，把 '/' 换成
    '\\' 再转正则，实测含分隔符的通配（"项目/*_备份" 匹 "项目\\旧版备份"）直接不匹配——
    同一份配置在 Windows 与 Linux 上行为不一致，违反项目可迁移铁律。

    语义（显式约定，配置里照此写）：
    - 模式不含 '/' → 对**路径任一段**（含文件名、目录名）做 fnmatchcase，故 "Fiction"
      排除任意层级下名为 Fiction 的目录/文件；
    - 模式含 '/' → 按相对路径**逐段前缀匹配**，段内可用通配，故 "项目/*_备份"
      排除 项目/ 下任意以 _备份 结尾的子目录。
    配置里写反斜杠也接受（统一归一为 '/'）。
    """
    pat = pattern.replace("\\", "/")
    rel_norm = rel.replace("\\", "/")
    if "/" not in pat:
        return any(fnmatch.fnmatchcase(seg, pat)
                   for seg in rel_norm.split("/") if seg)
    pat_parts = [p for p in pat.split("/") if p]
    rel_parts = [p for p in rel_norm.split("/") if p]
    if len(pat_parts) > len(rel_parts):
        return False
    return all(fnmatch.fnmatchcase(rp, pp) for rp, pp in zip(rel_parts, pat_parts))


@dataclass(frozen=True)
class AdapterOutput:
    entries: list[Entry]
    stats: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """每个知识源一个实现；name 与 config [sources.<name>] 对应。"""

    name: str

    def collect(self, ctx: Any) -> AdapterOutput:
        """ctx 为适配器上下文（config 等）；源读取失败抛 AdapterError（跳过整个源）。"""
        ...
