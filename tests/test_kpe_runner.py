"""KPE 通道：源文件解析 / 后端 failover / 超大书分卷（C1）。

- 2026-10-28 修：PDF 原件 vs 正文 dump（`_pdf_path` 只看 path 会 12/12 返回 None）；
- 2026-10-29 C1：先切块、再按「chunks 实际字符数」决定单卷/多卷；逐卷 extract + 导入，
  卷间断点续跑。全部人造数据，零网络零 LLM。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from knowatlas.config import Config
from knowatlas.pipeline.kpe_runner import _pdf_path, run_kpe_for_entry

_TARGET_CHARS = 6000
_MAX_CHARS = 8000      # 与 runner 的 --max-chars = chunk_chars + 2000 同口径


def _cfg(tmp_path: Path, roots: list[Path], backends: list[dict] | None = None, *,
         ingest: dict | None = None) -> Config:
    data = {
        "general": {"db_path": str(tmp_path / "data" / "k.db")},
        "sources": {"folders": {"roots": [str(r) for r in roots]}},
    }
    if backends:
        data["llm"] = {"backends": backends}
    if ingest:
        data["ingest"] = ingest
    return Config(data, tmp_path / "knowatlas.toml")


def _pdf(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.7\n% fake\n")
    return p


def _write_chunks(out: Path, *, source: Path | None, n: int = 2,
                  chars: int = 30) -> None:
    """模拟 `kpe chunks` 的产物：manifest.json + chunks.jsonl。"""
    out.mkdir(parents=True, exist_ok=True)
    rows = [{"index": i + 1, "id": f"c{i + 1}",
             "section_path": f"第{i + 1}章 > {i + 1}.1",
             "page_start": 0, "page_end": 0, "chars": chars,
             "text": "x" * chars} for i in range(n)]
    (out / "chunks.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8", newline="\n")
    manifest = {"book": "B", "source": str(source.resolve()) if source else "",
                "params": {"target_chars": _TARGET_CHARS, "max_chars": _MAX_CHARS},
                "chunk_count": n, "chunks_chars": n * chars}
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8", newline="\n")


def _write_done_points(out: Path) -> None:
    """模拟 `kpe extract` 成功：每块一个点 + done.jsonl。"""
    rows = [json.loads(x) for x in (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip()]
    (out / "points.jsonl").write_text(
        "".join(json.dumps({"chunk_id": c["id"], "chunk_index": c["index"],
                            "section_path": c["section_path"], "text": f"点{c['id']}",
                            "quote": "", "quote_ok": False, "model": "m"},
                           ensure_ascii=False) + "\n" for c in rows),
        encoding="utf-8", newline="\n")
    (out / "done.jsonl").write_text(
        "".join(json.dumps({"chunk_id": c["id"]}) + "\n" for c in rows),
        encoding="utf-8", newline="\n")


def _fake_runner(calls: list[list[str]], *, fail_volume: str | None = None,
                 chunks_n: int = 2, chunk_chars: int = 30):
    """假 `_run`：chunks 写整本产物；extract 写 done/points（可指定某卷失败）。"""

    def fake_run(args, timeout):
        calls.append(list(args))
        if args[0] == "chunks":
            out = Path(args[args.index("--out") + 1])
            _write_chunks(out, source=Path(args[1]), n=chunks_n, chars=chunk_chars)
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        out = Path(args[1])
        if fail_volume and out.name == fail_volume:
            return SimpleNamespace(returncode=1, stdout="", stderr="LLM HTTP 402")
        _write_done_points(out)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    return fake_run


def _fake_import(calls: list[str], **extra):
    def fake_import(cfg, dl, out, **kw):
        calls.append(Path(out).name)
        return {"created": 1, "linked": 0, **extra}

    return fake_import


def test_pdf_locator_resolves_under_configured_roots(tmp_path):
    root = tmp_path / "KnowLedge"
    pdf = _pdf(root, "labuladong的算法秘籍V2.7.pdf")
    cfg = _cfg(tmp_path, [tmp_path / "other", root])   # 只有第二个根命中
    assert _pdf_path(cfg, "file://labuladong的算法秘籍V2.7.pdf") == pdf
    # 子目录 + URL 编码
    nested = _pdf(root, "books/Hello Agents.pdf")
    assert _pdf_path(cfg, "file://books/Hello%20Agents.pdf") == nested
    # 绝对 file URL（非 folder 来源，如手动 kadd）仍认
    assert _pdf_path(cfg, f"file:///{pdf.as_posix()}") == pdf


def test_non_pdf_and_illegal_locators_return_none(tmp_path):
    root = tmp_path / "KnowLedge"
    _pdf(root, "a.pdf")
    (root / "note.md").write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path, [root])
    assert _pdf_path(cfg, "file://note.md") is None          # 不是 PDF
    assert _pdf_path(cfg, "file://missing.pdf") is None       # 根里没有
    assert _pdf_path(cfg, "file://../escape.pdf") is None     # 越界
    assert _pdf_path(cfg, "file://a\\b.pdf") is None          # 反斜杠
    assert _pdf_path(cfg, "file:///C:/nope/x.pdf") is None     # 绝对路径但不存在
    assert _pdf_path(cfg, "https://a.example/x.pdf") is None   # 非 file
    assert _pdf_path(cfg, "") is None


def test_dry_run_reports_pdf_source_not_book_md(tmp_path):
    root = tmp_path / "KnowLedge"
    pdf = _pdf(root, "b.pdf")
    cfg = _cfg(tmp_path, [root])
    entry = SimpleNamespace(id="e1", locator="file://b.pdf", title="B")
    res = run_kpe_for_entry(cfg, None, entry, "正文" * 10, dry_run=True)
    assert res["status"] == "ok" and res["dry_run"] is True
    assert res["source"] == str(pdf)                # 原件，不是 book.md
    assert res["would_chunk"] is True               # 还没切块：试跑不去切（零成本）
    # 解析不到 PDF 才落 book.md（非 PDF 来源）
    entry2 = SimpleNamespace(id="e2", locator="https://a.example/post", title="P")
    res2 = run_kpe_for_entry(cfg, None, entry2, "正文" * 10, dry_run=True)
    assert res2["source"].endswith("book.md")


def test_multi_key_env_spec_picks_first_present(monkeypatch, tmp_path):
    """真配置 `api_key_env = "SF1,SF2"` 是 key 池写法，不能整串当变量名去取。"""
    from knowatlas.pipeline.kpe_runner import _llm_target, _pick_key_env

    spec = "KNOWATLAS_TEST_SF1,KNOWATLAS_TEST_SF2"
    monkeypatch.delenv("KNOWATLAS_TEST_SF1", raising=False)
    monkeypatch.delenv("KNOWATLAS_TEST_SF2", raising=False)
    assert _pick_key_env(spec) == "KNOWATLAS_TEST_SF1"       # 都没值 → 第一个（报错可读）
    monkeypatch.setenv("KNOWATLAS_TEST_SF2", "sk-x")
    assert _pick_key_env(spec) == "KNOWATLAS_TEST_SF2"       # 取第一个有值的
    cfg = Config({"llm": {"backends": [{
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": spec, "model": "fake-model"}]}}, tmp_path / "k.toml")
    assert _llm_target(cfg) == ("https://api.siliconflow.cn/v1", "fake-model",
                                "KNOWATLAS_TEST_SF2")


def _two_backends() -> list[dict]:
    return [{"base_url": "https://a.example/v1", "api_key_env": "KNOWATLAS_T_K1", "model": "m1"},
            {"base_url": "https://b.example/v1", "api_key_env": "KNOWATLAS_T_K2", "model": "m2"}]


def test_extract_fails_over_to_next_backend(monkeypatch, tmp_path):
    """第一个后端 402（余额不足）要换下一个——管道有这层 failover，KPE 以前没有。"""
    import knowatlas.pipeline.kpe_import as kpe_import
    import knowatlas.pipeline.kpe_runner as kpe_runner

    root = tmp_path / "KnowLedge"
    _pdf(root, "b.pdf")
    cfg = _cfg(tmp_path, [root], _two_backends())
    monkeypatch.setenv("KNOWATLAS_T_K1", "k1")
    monkeypatch.setenv("KNOWATLAS_T_K2", "k2")
    monkeypatch.setattr(kpe_runner, "_MAX_POINTS_SUPPORTED", True)
    monkeypatch.setattr(kpe_import, "import_kpe_dir",
                        lambda *a, **k: {"created": 3, "linked": 1})
    calls: list[list[str]] = []

    def fake_run(args, timeout):
        calls.append(list(args))
        if args[0] == "chunks":
            _write_chunks(Path(args[args.index("--out") + 1]), source=Path(args[1]))
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        if "m1" in args:                       # 第一个后端：余额不足
            return SimpleNamespace(returncode=1, stdout="", stderr="LLM HTTP 402")
        (Path(args[1]) / "manifest.json").write_text('{"chunk_count": 7}',
                                                    encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(kpe_runner, "_run", fake_run)
    entry = SimpleNamespace(id="e9", locator="file://b.pdf", title="B")
    res = run_kpe_for_entry(cfg, None, entry, "正文" * 20)
    assert res["status"] == "ok", res
    assert [c[0] for c in calls] == ["chunks", "extract", "extract"]
    assert "m2" in calls[-1] and "--max-points" in calls[-1]
    assert res["mode"] == "single"
    assert res["chunks"] == 7 and res["points"] == 4
    assert res["llm"] == "m2@https://b.example/v1"


def test_all_backends_failing_reports_last_error(monkeypatch, tmp_path):
    import knowatlas.pipeline.kpe_runner as kpe_runner

    root = tmp_path / "KnowLedge"
    _pdf(root, "b.pdf")
    cfg = _cfg(tmp_path, [root], _two_backends())
    monkeypatch.setenv("KNOWATLAS_T_K1", "k1")
    monkeypatch.setenv("KNOWATLAS_T_K2", "k2")
    monkeypatch.setattr(kpe_runner, "_MAX_POINTS_SUPPORTED", True)
    seen: list[str] = []

    def fake_run(args, timeout):
        if args[0] == "chunks":
            _write_chunks(Path(args[args.index("--out") + 1]), source=Path(args[1]))
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        seen.append(args[args.index("--model") + 1])
        return SimpleNamespace(returncode=1, stdout="", stderr=f"402 from {seen[-1]}")

    monkeypatch.setattr(kpe_runner, "_run", fake_run)
    entry = SimpleNamespace(id="e9", locator="file://b.pdf", title="B")
    res = run_kpe_for_entry(cfg, None, entry, "正文" * 20)
    assert res["status"] == "error"
    assert seen == ["m1", "m2"]                 # 两个后端都试过
    assert "m2" in res["error"] and "402" in res["error"]


# ---- 2026-10-29 C1：超大书分卷 ----


def _volume_cfg(tmp_path: Path) -> Config:
    root = tmp_path / "KnowLedge"
    _pdf(root, "big.pdf")
    return _cfg(tmp_path, [root], _two_backends(),
                ingest={"kpe_max_chars": 10000})   # 4 块 × 3000 > 10000 → 2 卷


def _big_entry() -> SimpleNamespace:
    return SimpleNamespace(id="e-big", locator="file://big.pdf", title="超大的书")


def test_oversized_book_splits_into_volumes(monkeypatch, tmp_path):
    """正文超上限不再硬报错：切块 → 按章装箱 → 逐卷抽取 + 逐卷导入。"""
    import knowatlas.pipeline.kpe_import as kpe_import
    import knowatlas.pipeline.kpe_runner as kpe_runner

    cfg = _volume_cfg(tmp_path)
    monkeypatch.setenv("KNOWATLAS_T_K1", "k1")
    calls: list[list[str]] = []
    imports: list[str] = []
    monkeypatch.setattr(kpe_runner, "_run",
                        _fake_runner(calls, chunks_n=4, chunk_chars=3000))
    monkeypatch.setattr(kpe_runner, "_MAX_POINTS_SUPPORTED", False)
    monkeypatch.setattr(kpe_import, "import_kpe_dir", _fake_import(imports))

    res = run_kpe_for_entry(cfg, None, _big_entry(), "正文" * 20)
    assert res["status"] == "ok", res
    assert res["mode"] == "volumes" and res["volumes"] == 2
    assert res["volumes_done"] == 2 and res["chunks"] == 4
    assert res["points"] == 2                       # 每卷导入一次（1 点/卷）
    assert [c[0] for c in calls] == ["chunks", "extract", "extract"]
    assert imports == ["v001", "v002"]

    out = Path(res["out"])
    for name in ("v001", "v002"):
        assert (out / name / "chunks.jsonl").is_file()
        assert (out / name / "manifest.json").is_file()
    index = json.loads((out / "volumes.json").read_text(encoding="utf-8"))
    assert [v["dir"] for v in index["volumes"]] == ["v001", "v002"]
    assert index["max_chars"] == 10000
    vol_manifest = json.loads((out / "v001" / "manifest.json").read_text(encoding="utf-8"))
    assert vol_manifest["book"] == "超大的书"        # 导入后进 meta.book，不是卷名
    assert vol_manifest["volume"] == 1 and vol_manifest["volumes"] == 2


def test_volumes_resume_skips_completed_extract(monkeypatch, tmp_path):
    """第二次调用：卷内块都 done → 不再调 extract（不重复花钱），只补导入。"""
    import knowatlas.pipeline.kpe_import as kpe_import
    import knowatlas.pipeline.kpe_runner as kpe_runner

    cfg = _volume_cfg(tmp_path)
    monkeypatch.setenv("KNOWATLAS_T_K1", "k1")
    calls: list[list[str]] = []
    imports: list[str] = []
    monkeypatch.setattr(kpe_runner, "_run",
                        _fake_runner(calls, chunks_n=4, chunk_chars=3000))
    monkeypatch.setattr(kpe_runner, "_MAX_POINTS_SUPPORTED", False)
    monkeypatch.setattr(kpe_import, "import_kpe_dir", _fake_import(imports))

    first = run_kpe_for_entry(cfg, None, _big_entry(), "正文" * 20)
    assert first["status"] == "ok" and first["volumes_done"] == 2
    calls.clear()
    imports.clear()

    again = run_kpe_for_entry(cfg, None, _big_entry(), "正文" * 20)
    assert again["status"] == "ok"
    assert calls == []                              # 整本 chunks 命中缓存，一次子进程都没起
    assert imports == ["v001", "v002"]              # 导入幂等，仍逐卷补


def test_volume_failure_keeps_finished_progress(monkeypatch, tmp_path):
    """v002 失败 → v001 照常导入，status=error 且 volumes_done=1（下轮续跑）。"""
    import knowatlas.pipeline.kpe_import as kpe_import
    import knowatlas.pipeline.kpe_runner as kpe_runner

    cfg = _volume_cfg(tmp_path)
    monkeypatch.setenv("KNOWATLAS_T_K1", "k1")
    calls: list[list[str]] = []
    imports: list[str] = []
    monkeypatch.setattr(kpe_runner, "_run",
                        _fake_runner(calls, fail_volume="v002", chunks_n=4, chunk_chars=3000))
    monkeypatch.setattr(kpe_runner, "_MAX_POINTS_SUPPORTED", False)
    monkeypatch.setattr(kpe_import, "import_kpe_dir", _fake_import(imports))

    res = run_kpe_for_entry(cfg, None, _big_entry(), "正文" * 20)
    assert res["status"] == "error"
    assert "v002" in res["error"]
    assert res["volumes_done"] == 1
    assert res["points"] == 1                       # 只有 v001 的点进了库
    assert imports == ["v001"]                      # 失败卷没有点可导 → 不白跑一次导入
    # 两个后端都试过（v002 都 402），之后不再往后跑
    assert [c[0] for c in calls] == ["chunks", "extract", "extract"]


def test_small_payload_stays_single_volume(monkeypatch, tmp_path):
    """chunks 字符数 ≤ 上限 → 原单卷路径（不建 v001，行为与旧版一致）。"""
    import knowatlas.pipeline.kpe_import as kpe_import
    import knowatlas.pipeline.kpe_runner as kpe_runner

    cfg = _volume_cfg(tmp_path)
    monkeypatch.setenv("KNOWATLAS_T_K1", "k1")
    calls: list[list[str]] = []
    imports: list[str] = []
    monkeypatch.setattr(kpe_runner, "_run",
                        _fake_runner(calls, chunks_n=2, chunk_chars=1000))   # 2000 ≤ 10000
    monkeypatch.setattr(kpe_runner, "_MAX_POINTS_SUPPORTED", False)
    monkeypatch.setattr(kpe_import, "import_kpe_dir", _fake_import(imports))

    res = run_kpe_for_entry(cfg, None, _big_entry(), "正文" * 20)
    assert res["status"] == "ok" and res["mode"] == "single" and res["volumes"] == 0
    assert imports == ["e-big"]                     # 导入的是整本目录
    out = Path(res["out"])
    assert not (out / "v001").exists()
    assert [c[0] for c in calls] == ["chunks", "extract"]
    assert calls[-1][1] == str(out)


def test_dry_run_reports_volume_plan_without_llm(monkeypatch, tmp_path):
    """试跑：已有整本 chunks 时只报卷计划——零切块、零 LLM、零写库。"""
    import knowatlas.pipeline.kpe_runner as kpe_runner

    cfg = _volume_cfg(tmp_path)
    root = tmp_path / "KnowLedge"
    out = tmp_path / "data" / "kpe" / "e-big"
    _write_chunks(out, source=root / "big.pdf", n=4, chars=3000)
    calls: list[list[str]] = []
    monkeypatch.setattr(kpe_runner, "_run", _fake_runner(calls))
    monkeypatch.delenv("KNOWATLAS_T_K1", raising=False)

    res = run_kpe_for_entry(cfg, None, _big_entry(), "正文" * 20, dry_run=True)
    assert res["status"] == "ok" and res["dry_run"] is True
    assert res["mode"] == "volumes" and res["volumes"] == 2
    assert len(res["volume_plan"]) == 2
    assert calls == []                              # 一次子进程都没起
    assert not (out / "v001").exists()              # 试跑不落卷目录