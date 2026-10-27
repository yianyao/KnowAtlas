"""pipeline/sync/_common.py（拆分产物）。"""

# 拆分自 pipeline/sync.py（路线 A，2026-10-28）：函数体逐字搬迁，未改行为。


from typing import Any
from ...adapters.bookmark import collect_bookmarks
from ...adapters.dbfile import collect_dbs
from ...adapters.emmx import collect_emmx
from ...adapters.folder import collect_folders
from ...adapters.maildir import collect_maildirs
from ...adapters.opml import collect_opml
from ...adapters.session import collect_sessions


_BATCH_COLLECTORS: dict[str, Any] = {
    "bookmarks": collect_bookmarks,
    "folders": collect_folders,
    "emmx": collect_emmx,
    "mail": collect_maildirs,
    "opml": collect_opml,
    "sessions": collect_sessions,   # 第五十七批：AI 会话（harvester 产物，零凭证）
    "dbs": collect_dbs,             # 第五十七批：数据文件（sqlite/PG 自省，零凭证）
}


_SOURCE_TYPE_BY_NAME: dict[str, str] = {
    "bookmarks": "bookmark", "folders": "folder", "emmx": "emmx", "mail": "mail",
    "opml": "opml", "sessions": "session", "dbs": "db"}


_SECTION_BY_NAME: dict[str, str] = {"sessions": "session", "dbs": "db"}


_INLINE_LIMIT = 4096


_TRUNCATED_AT = 4000


_SOURCE_FIELDS = ("title", "locator", "locator_canonical", "native_path",
                  "inline_content", "content_hash", "created_at")
