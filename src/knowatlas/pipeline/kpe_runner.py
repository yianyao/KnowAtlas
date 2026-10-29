"""KPE 通道（工单 2026-10-27《入库即抽点与自动老化》§2.2）：书/超长文档自动走 KPE。

纪律（沿用 `pipeline/kpe_import.py` 的边界）：
- **不 import `tools/kpe`**：只以子进程调用它的 CLI（`python -m kpe chunks|extract`），
  KnowAtlas 仍可独立分发；产物格式不变，导入仍复用 `import_kpe_dir`。
- 依赖同解释器：主项目已带 `pdfplumber`（markitdown 的 PDF 解析依赖），所以子进程用
  `sys.executable` + `PYTHONPATH=<repo>/tools/kpe` 即可，**不需要 uv / 不需要装包**。
- 幂等：`out_dir` 固定为 `data/kpe/<entry_id>/`，KPE 自身用 `cache/` + `done.jsonl` 续跑；
  重复调用只会补没跑完的块（`--retry-failed` 补齐失败块，不重复花钱）。
- 失败不抛业务异常：返回 `{"status": "error", "error": ...}`，由调用方记 `meta.ingest`。

超大书（工单 2026-10-29《超大书分卷摄取》C1）：
- **先切块、再决定单卷/多卷**。上限量的是「真正喂给 LLM 的 chunks 字符数」，不是正文字数
  （真库 agentic-ai-guide 正文 2.59M、PDF 通道只有 776k；旧代码按正文判上限，直接堵死）；
- `Σ块.chars <= [ingest] kpe_max_chars` → 单卷，行为与旧版逐字相同；
- 超过 → `kpe_volumes.pack_volumes()` 按章装箱成 `v001..`，逐卷 `extract` + 逐卷导入；
  卷内靠 `done.jsonl`、卷间靠 `volume_complete()` 断点续跑（全完成时不需要 LLM key）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .kpe_volumes import (pack_volumes, total_chars, volume_complete,
                          volume_stats, write_volumes)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_KPE_ROOT = _REPO_ROOT / "tools" / "kpe"
_CHUNK_TIMEOUT = 1800     # 大 PDF 解析 + 分块
_EXTRACT_TIMEOUT = 3600   # 单卷抽取（4 并发、数百块）
_MAX_POINTS_SUPPORTED: bool | None = None
_IMPORT_KEYS = ("created", "linked", "skipped", "dropped_front", "empty", "offset_ok")


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


def _pick_key_env(spec: str) -> str:
    """`api_key_env` 可逗号分隔多个变量名（LlmClient 的 key 池口径）——取第一个**有值**的。

    2026-10-28 修：此前把整串 `"A,KNOWATLAS_LLM_API_KEY_SF2"` 当成单个变量名去
    `os.environ.get(...)`，真配置下必然取不到 → KPE 每次都报「LLM 未配置」。KPE 的
    `--api-key-env` 只认单个变量名，所以这里先挑一个。
    """
    names = [s.strip() for s in str(spec or "").split(",") if s.strip()]
    for name in names:
        if os.environ.get(name):
            return name
    return names[0] if names else "KNOWATLAS_LLM_API_KEY"


def _llm_targets(cfg: Any) -> list[tuple[str, str, str]]:
    """按配置顺序展开 (base_url, model, api_key_env) 候选；KPE 一次只吃一个后端。

    `LlmClient` 自己会在后端之间 failover（402/401 换个后端继续），但 KPE 是子进程，
    只能由调用方逐个尝试——2026-10-28 实跑就是硅基 key 余额不足（HTTP 402），而
    `_llm_target()` 只取第一个后端，导致 93/93 块全失败、管道却正常出点。
    """
    out: list[tuple[str, str, str]] = []
    for b in (cfg.get("llm.backends", []) or []):
        if not (isinstance(b, dict) and b.get("base_url") and b.get("model")):
            continue
        names = [s.strip() for s in str(b.get("api_key_env") or "").split(",") if s.strip()]
        for name in (names or ["KNOWATLAS_LLM_API_KEY"]):
            if os.environ.get(name):          # key 池里只展开真有值的变量
                out.append((str(b["base_url"]), str(b["model"]), name))
    if not out:                               # 旧配置（扁平 [llm]）兼容
        spec = str(cfg.get("llm.api_key_env", "KNOWATLAS_LLM_API_KEY"))
        out.append((str(cfg.get("llm.base_url", "")), str(cfg.get("llm.model", "")),
                    _pick_key_env(spec)))
    return out


def _llm_target(cfg: Any) -> tuple[str, str, str]:
    """第一个候选（保持旧调用点语义）。"""
    return _llm_targets(cfg)[0]


def _relative_part(raw: str) -> str | None:
    """根相对路径；含盘符/反斜杠/`..` 一律不合规（与 `fetchers/file_reader` 同口径）。"""
    rel = raw.lstrip("/")
    if not rel or "\\" in rel or ".." in Path(rel).parts:
        return None
    if len(rel) >= 2 and rel[1] == ":":
        return None
    return rel


def _absolute_part(raw: str) -> Path | None:
    """绝对 file URL（`file:///C:/x.pdf`、`file://C:/x.pdf`）→ Path；非绝对返回 None。"""
    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw.lstrip("/")
    p = Path(raw)
    return p if p.is_absolute() else None


def _pdf_path(cfg: Any, locator: str) -> Path | None:
    """locator 指向的 PDF 原件；解析不到或不是 PDF 返回 None。

    真数据的 locator 是 `file://<根相对路径>`（folder 适配器禁绝对机器路径），裸文件名时
    urlsplit 把名字放进 netloc、path 为空 —— 2026-10-28 前只看 path，真库 12 本 PDF **全部**
    返回 None，于是 KPE 只能把正文 dump 成 `book.md` 再分块，丢掉 `section_path` / 页码
    （KPE 的目录/页码分块正是 PDF 走 KPE 的理由）。现在按 `sources.folders.roots` 逐根解析。
    """
    try:
        parts = urlsplit(str(locator or ""))
    except ValueError:
        return None
    if parts.scheme != "file":
        return None
    raw = unquote(parts.netloc + (parts.path or ""))
    rel = _relative_part(raw)
    cand: Path | None = None
    if rel:
        for root in list(cfg.get("sources.folders.roots", []) or []):
            if (Path(str(root)) / rel).is_file():
                cand = Path(str(root)) / rel
                break
    if cand is None:                    # 非 folder 来源（手动 kadd 的绝对路径）兜底
        cand = _absolute_part(raw)
    if cand is None or cand.suffix.lower() != ".pdf" or not cand.is_file():
        return None
    return cand


def _tail(text: str, limit: int = 300) -> str:
    return (text or "").strip()[-limit:]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_chunks(out: Path) -> list[dict[str, Any]]:
    """读整本 chunks.jsonl（坏行跳过，与 `kpe_import._read_jsonl` 同口径）。"""
    rows: list[dict[str, Any]] = []
    path = out / "chunks.jsonl"
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _chunks_ready(out: Path, src: Path, chunk_chars: int) -> bool:
    """整本切块是否可复用：源路径与切块参数都对得上才复用它（否则重切）。

    2026-10-29 C1：切块从「每次跑」变成「先切一次、之后复用」——大 PDF 解析要 1–2 分钟，
    而 chunks 决定卷划分与 chunk id。**换 `points.chunk_chars` 需先删 `data/kpe/<entry>/`**
    （id 与卷划分都会变，旧卷缓存作废），这条写在变更工单里。
    """
    manifest = _read_json(out / "manifest.json")
    if not isinstance(manifest, dict) or not (out / "chunks.jsonl").is_file():
        return False
    if str(manifest.get("source") or "") != str(src.resolve()):
        return False
    params = manifest.get("params") or {}
    try:
        return (int(params.get("target_chars") or 0) == int(chunk_chars)
                and int(params.get("max_chars") or 0) == int(chunk_chars) + 2000)
    except (TypeError, ValueError):
        return False


def _extract(out: Path, cfg: Any, max_points: int) -> tuple[str, str]:
    """在 `out` 目录跑一次 extract；后端逐个 failover。返回 (成功的 llm 标签, 错误)。

    成功时错误为空；失败时标签为空。已成功的块在 `cache/` 里，`--retry-failed` 只补失败块，
    换后端不会重复花钱——单卷与分卷共用这条口径。
    """
    usable = [t for t in _llm_targets(cfg) if t[0] and t[1] and os.environ.get(t[2])]
    if not usable:
        return "", "LLM 未配置（base_url/model/api_key_env）——KPE 无法抽取"
    last_error = ""
    for base_url, model, key_env in usable:
        extract_args = ["extract", str(out), "--base-url", base_url, "--model", model,
                        "--api-key-env", key_env, "--workers", "2",
                        "--retry-failed"]
        if _supports_max_points():
            extract_args.extend(["--max-points", str(max_points)])
        try:
            res = _run(extract_args, _EXTRACT_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            last_error = f"extract 启动失败（{model}@{base_url}）：{exc}"
            continue
        if res.returncode == 0:
            return f"{model}@{base_url}", ""
        last_error = (f"extract 失败（{res.returncode}，{model}@{base_url}）："
                      f"{_tail(res.stderr or res.stdout)}")
    return "", last_error


def _acc_import(stats: dict[str, Any], imported: dict[str, Any]) -> None:
    """把一次导入的计数并进 stats（分卷时逐卷累加；单卷只有一次）。"""
    stats["points"] += int(imported.get("created") or 0) + int(imported.get("linked") or 0)
    agg = stats.get("imported") or {}
    for key in _IMPORT_KEYS:
        if key in imported:
            agg[key] = int(agg.get(key) or 0) + int(imported.get(key) or 0)
    stats["imported"] = agg


def _finish_volumes(stats: dict[str, Any], done_stats: list[dict[str, Any]],
                    vols: list[Any], *, error: str = "") -> dict[str, Any]:
    """收尾：记每卷现场、已完成卷数；有错或没跑完 → status=error（下轮续跑）。"""
    stats["volume_stats"] = done_stats
    stats["volumes_done"] = sum(1 for v in done_stats if v.get("complete"))
    if error:
        stats["error"] = error
        stats["status"] = "error"
    elif stats["volumes_done"] < len(vols):
        stats["status"] = "error"
        stats["error"] = f"部分卷未完成（{stats['volumes_done']}/{len(vols)}）"
    return stats


def _run_volumes(cfg: Any, dl: Any, entry: Any, out: Path, vols: list[Any],
                 stats: dict[str, Any], *, import_kpe_dir: Any,
                 max_points: int, backup: bool) -> dict[str, Any]:
    """逐卷 extract + 导入；某卷失败就停下（已完成的卷照常入库，下轮续跑）。"""
    done_stats: list[dict[str, Any]] = []
    for vol in vols:
        vdir = out / vol.dirname
        if not volume_complete(vdir, vol.chunk_ids):
            llm, err = _extract(vdir, cfg, max_points)
            if err:
                prefix = (f"{vol.dirname}（块 #{vol.summary()['first_index']}"
                          f"..#{vol.summary()['last_index']}）：")
                # 失败也要把该卷**已产出的点**导入：进度可见，下一轮只补没跑的块。
                done = volume_stats(vdir)
                if done.get("points"):
                    try:
                        _acc_import(stats, import_kpe_dir(
                            cfg, dl, vdir, entry_id=entry.id, backup=backup,
                            dry_run=False))
                    except Exception as exc:  # noqa: BLE001 —— 导入失败不该盖掉抽取错误
                        err += f"；导入失败：{type(exc).__name__}: {exc}"
                done_stats.append(done)
                return _finish_volumes(stats, done_stats, vols, error=prefix + err)
            stats["llm"] = llm
        try:
            _acc_import(stats, import_kpe_dir(
                cfg, dl, vdir, entry_id=entry.id, backup=backup, dry_run=False))
        except Exception as exc:  # noqa: BLE001 —— 单卷导入失败不该炸整轮巡检
            done_stats.append(volume_stats(vdir))
            return _finish_volumes(
                stats, done_stats, vols,
                error=f"{vol.dirname} 导入失败：{type(exc).__name__}: {exc}")
        done_stats.append(volume_stats(vdir))
    return _finish_volumes(stats, done_stats, vols)


def run_kpe_for_entry(cfg: Any, dl: Any, entry: Any, body: str, *,
                      out_root: Path | None = None, dry_run: bool = False,
                      backup: bool = False) -> dict[str, Any]:
    """对单条目跑 KPE（chunks → extract → 导入点层）；返回统计 dict。

    body：条目正文（用于非 PDF 的 md dump；上限已改按 chunks 实际字符数判定）。
    """
    from .kpe_import import import_kpe_dir

    stats: dict[str, Any] = {"entry_id": entry.id, "title": str(entry.title)[:40],
                             "status": "ok", "mode": "single", "chunks": 0,
                             "points": 0, "volumes": 0, "volumes_done": 0,
                             "dry_run": dry_run}
    if not available():
        return {**stats, "status": "error", "error": "KPE 子树不存在（tools/kpe）"}
    max_chars = int(getattr(cfg, "ingest_kpe_max_chars", 600000))
    chunk_chars = int(getattr(cfg, "points_chunk_chars", 6000))
    max_points = int(getattr(cfg, "points_max_per_chunk", 6))

    # 绝对化：KPE 子进程的 cwd 是 `tools/kpe`，相对 db_path 会把产物写进子树（2026-10-28 修）。
    data_dir = Path(cfg.db_path).resolve().parent
    out = Path(out_root or (data_dir / "kpe" / entry.id)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stats["out"] = str(out)

    # 源文件：PDF 用原件（目录/页码）；其余正文 dump 成 md（保留标题层级当 section_path）。
    src = _pdf_path(cfg, str(entry.locator or ""))
    if src is None:
        src = out / "book.md"
        src.write_text(body, encoding="utf-8", newline="\n")
    stats["source"] = str(src)

    if dry_run:
        # 试跑零成本：不切块、不调 LLM。已有整本 chunks 时按当前配置报卷计划。
        planned = _read_chunks(out)
        if planned:
            total = total_chars(planned)
            stats["chunks"] = len(planned)
            if total > max_chars:
                vols = pack_volumes(planned, max_chars)
                stats.update(mode="volumes", volumes=len(vols),
                             volume_plan=[v.summary() for v in vols])
        else:
            stats["would_chunk"] = True
        return {**stats, "status": "ok", "dry_run": True}

    # ---- 1) 整本切块（本地免费、幂等；决定卷划分与 chunk id）----
    if not _chunks_ready(out, src, chunk_chars):
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
    chunks = _read_chunks(out)
    if not chunks:
        return {**stats, "status": "error",
                "error": "没有分出任何块（检查源文件/目录解析）"}
    stats["chunks"] = len(chunks)
    total = total_chars(chunks)

    # ---- 2) 单卷：与旧版逐字相同（含 body 超上限的老书，只要 PDF 通道装得下）----
    if total <= max_chars:
        llm, err = _extract(out, cfg, max_points)
        if err:
            return {**stats, "status": "error", "error": err}
        stats["llm"] = llm
        try:
            imported = import_kpe_dir(cfg, dl, out, entry_id=entry.id,
                                      backup=backup, dry_run=False)
        except Exception as exc:  # noqa: BLE001 —— 导入失败不该炸整轮巡检
            return {**stats, "status": "error",
                    "error": f"导入失败：{type(exc).__name__}: {exc}"}
        stats["chunks"] = int((_read_json(out / "manifest.json") or {}).get("chunk_count")
                              or len(chunks))
        stats["points"] = int(imported.get("created") or 0) + int(imported.get("linked") or 0)
        stats["imported"] = imported
        return stats

    # ---- 3) 多卷：按章装箱 → 逐卷 extract + 导入（断点续跑）----
    manifest = _read_json(out / "manifest.json")
    if not isinstance(manifest, dict):
        manifest = {"book": str(entry.title or src.stem), "source": str(src.resolve()),
                    "chunk_count": len(chunks)}
    vols = pack_volumes(chunks, max_chars)
    write_volumes(out, manifest, vols, book=str(entry.title or src.stem),
                  max_chars=max_chars)
    stats.update(mode="volumes", volumes=len(vols),
                 volume_plan=[v.summary() for v in vols])
    return _run_volumes(cfg, dl, entry, out, vols, stats,
                        import_kpe_dir=import_kpe_dir, max_points=max_points,
                        backup=backup)