"""KPE 通道（工单 2026-10-27《入库即抽点与自动老化》§2.2）：书/超长文档自动走 KPE。

纪律（沿用 `pipeline/kpe_import.py` 的边界）：
- **不 import `tools/kpe`**：只以子进程调用它的 CLI（`python -m kpe chunks|extract`），
  KnowAtlas 仍可独立分发；产物格式不变，导入仍复用 `import_kpe_dir`。
- 依赖同解释器：主项目已带 `pdfplumber`（markitdown 的 PDF 解析依赖），所以子进程用
  `sys.executable` + `PYTHONPATH=<repo>/tools/kpe` 即可，**不需要 uv / 不需要装包**。
- 幂等：`out_dir` 固定为 `data/kpe/<entry_id>/`，KPE 自身用 `cache/` + `done.jsonl` 续跑；
  重复调用只会补没跑完的块（`--retry-failed` 补齐失败块，不重复花钱）。
- 失败不抛业务异常：返回 `{"status": "error", "error": ...}`，由调用方记 `meta.ingest`。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_KPE_ROOT = _REPO_ROOT / "tools" / "kpe"
_CHUNK_TIMEOUT = 1800     # 大 PDF 解析 + 分块
_EXTRACT_TIMEOUT = 3600   # 全本抽取（4 并发、数百块）
_MAX_POINTS_SUPPORTED: bool | None = None


def kpe_root() -> Path:
    return _KPE_ROOT


def available() -> bool:
    """KPE 源码子树是否在（打包安装的 wheel 里没有 `tools/` → 不支持 KPE 通道）。"""
    return (_KPE_ROOT / "kpe" / "cli.py").is_file()


def _env() -> dict[str, str]:
    env = dict(os.environ)
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (str(_KPE_ROOT) + (os.pathsep + prev if prev else ""))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "kpe", *args], cwd=str(_KPE_ROOT),
                          env=_env(), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _supports_max_points() -> bool:
    """上游是否已支持 `--max-points`（子树未升级时优雅降级为 prompt 默认 1–6）。"""
    global _MAX_POINTS_SUPPORTED
    if _MAX_POINTS_SUPPORTED is None:
        try:
            res = _run(["extract", "--help"], 60)
            _MAX_POINTS_SUPPORTED = "--max-points" in (res.stdout or "")
        except (OSError, subprocess.SubprocessError):
            _MAX_POINTS_SUPPORTED = False
    return _MAX_POINTS_SUPPORTED


def _llm_target(cfg: Any) -> tuple[str, str, str]:
    """(base_url, model, api_key_env)；多后端取第一个（与 LlmClient 的优先级同向）。"""
    backends = cfg.get("llm.backends", []) or []
    for b in backends:
        if isinstance(b, dict) and b.get("base_url") and b.get("model"):
            return (str(b["base_url"]), str(b["model"]),
                    str(b.get("api_key_env") or "KNOWATLAS_LLM_API_KEY"))
    return (str(cfg.get("llm.base_url", "")), str(cfg.get("llm.model", "")),
            str(cfg.get("llm.api_key_env", "KNOWATLAS_LLM_API_KEY")))


def _pdf_path(locator: str) -> Path | None:
    try:
        parts = urlsplit(locator)
    except ValueError:
        return None
    if parts.scheme != "file" or not parts.path:
        return None
    p = Path(unquote(parts.path.lstrip("/")) if parts.netloc else unquote(parts.path))
    if parts.netloc:   # file:///C:/x.pdf 在 Windows 上 netloc 为空、path 以 /C:/ 开头
        p = Path(unquote(parts.path))
    return p if p.suffix.lower() == ".pdf" and p.is_file() else None


def _tail(text: str, limit: int = 300) -> str:
    return (text or "").strip()[-limit:]


def run_kpe_for_entry(cfg: Any, dl: Any, entry: Any, body: str, *,
                      out_root: Path | None = None, dry_run: bool = False,
                      backup: bool = False) -> dict[str, Any]:
    """对单条目跑 KPE（chunks → extract → 导入点层）；返回统计 dict。

    body：条目正文（用于非 PDF 的 md dump，同时给字数上限护栏）。
    """
    from .kpe_import import import_kpe_dir

    stats: dict[str, Any] = {"entry_id": entry.id, "title": str(entry.title)[:40],
                             "status": "ok", "chunks": 0, "points": 0,
                             "dry_run": dry_run}
    if not available():
        return {**stats, "status": "error", "error": "KPE 子树不存在（tools/kpe）"}
    max_chars = int(getattr(cfg, "ingest_kpe_max_chars", 600000))
    if len(body) > max_chars:
        return {**stats, "status": "error",
                "error": f"正文 {len(body):,} 字超过 KPE 上限 {max_chars:,}"}
    chunk_chars = int(getattr(cfg, "points_chunk_chars", 6000))
    max_points = int(getattr(cfg, "points_max_per_chunk", 6))

    data_dir = Path(cfg.db_path).parent
    out = Path(out_root or (data_dir / "kpe" / entry.id))
    out.mkdir(parents=True, exist_ok=True)
    stats["out"] = str(out)

    # 源文件：PDF 用原件（目录/页码）；其余正文 dump 成 md（保留标题层级当 section_path）。
    src = _pdf_path(str(entry.locator or ""))
    if src is None:
        src = out / "book.md"
        src.write_text(body, encoding="utf-8", newline="\n")
    stats["source"] = str(src)

    if dry_run:
        return {**stats, "status": "ok", "dry_run": True}

    chunks_args = ["chunks", str(src), "--out", str(out),
                   "--target-chars", str(chunk_chars),
                   "--max-chars", str(chunk_chars + 2000),
                   "--book-title", str(entry.title or src.stem)]
    try:
        res = _run(chunks_args, _CHUNK_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return {**stats, "status": "error", "error": f"chunks 启动失败：{exc}"}
    if res.returncode != 0:
        return {**stats, "status": "error",
                "error": f"chunks 失败（{res.returncode}）：{_tail(res.stderr or res.stdout)}"}

    base_url, model, key_env = _llm_target(cfg)
    if not (base_url and model and os.environ.get(key_env)):
        return {**stats, "status": "error",
                "error": f"LLM 未配置（base_url/model/{key_env}）——KPE 无法抽取"}
    extract_args = ["extract", str(out), "--base-url", base_url, "--model", model,
                    "--api-key-env", key_env, "--workers", "2",
                    "--retry-failed"]
    if _supports_max_points():
        extract_args.extend(["--max-points", str(max_points)])
    try:
        res = _run(extract_args, _EXTRACT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return {**stats, "status": "error", "error": f"extract 启动失败：{exc}"}
    if res.returncode != 0:
        return {**stats, "status": "error",
                "error": f"extract 失败（{res.returncode}）：{_tail(res.stderr or res.stdout)}"}

    try:
        imported = import_kpe_dir(cfg, dl, out, entry_id=entry.id,
                                  backup=backup, dry_run=False)
    except Exception as exc:  # noqa: BLE001 —— 导入失败不该炸整轮巡检
        return {**stats, "status": "error", "error": f"导入失败：{type(exc).__name__}: {exc}"}
    try:
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        stats["chunks"] = int(manifest.get("chunk_count") or 0)
    except (OSError, ValueError):
        stats["chunks"] = 0
    stats["points"] = int(imported.get("created") or 0) + int(imported.get("linked") or 0)
    stats["imported"] = imported
    return stats