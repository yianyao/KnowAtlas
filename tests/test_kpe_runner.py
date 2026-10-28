"""KPE 通道的源文件解析（2026-10-28 修：PDF 原件 vs 正文 dump）。

真数据里 locator 是 `file://<根相对路径>`（folder 适配器禁绝对机器路径），裸文件名落在
`urlsplit` 的 netloc 里 —— 只取 `path` 会让 `_pdf_path` 对真库 12/12 本 PDF 返回 None，
KPE 只能把正文 dump 成 `book.md`，丢掉 `section_path` / 页码（PDF 走 KPE 的唯一理由）。
全部人造数据，零网络零 LLM。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from knowatlas.config import Config
from knowatlas.pipeline.kpe_runner import _pdf_path, run_kpe_for_entry


def _cfg(tmp_path: Path, roots: list[Path], backends: list[dict] | None = None) -> Config:
    data = {
        "general": {"db_path": str(tmp_path / "data" / "k.db")},
        "sources": {"folders": {"roots": [str(r) for r in roots]}},
    }
    if backends:
        data["llm"] = {"backends": backends}
    return Config(data, tmp_path / "knowatlas.toml")


def _pdf(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.7\n% fake\n")
    return p


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
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        if "m1" in args:                       # 第一个后端：余额不足
            return SimpleNamespace(returncode=1, stdout="", stderr="LLM HTTP 402")
        out = Path(args[1])
        (out / "manifest.json").write_text('{"chunk_count": 7}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(kpe_runner, "_run", fake_run)
    entry = SimpleNamespace(id="e9", locator="file://b.pdf", title="B")
    res = run_kpe_for_entry(cfg, None, entry, "正文" * 20)
    assert res["status"] == "ok", res
    assert [c[0] for c in calls] == ["chunks", "extract", "extract"]
    assert "m2" in calls[-1] and "--max-points" in calls[-1]
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
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        seen.append(args[args.index("--model") + 1])
        return SimpleNamespace(returncode=1, stdout="", stderr=f"402 from {seen[-1]}")

    monkeypatch.setattr(kpe_runner, "_run", fake_run)
    entry = SimpleNamespace(id="e9", locator="file://b.pdf", title="B")
    res = run_kpe_for_entry(cfg, None, entry, "正文" * 20)
    assert res["status"] == "error"
    assert seen == ["m1", "m2"]                 # 两个后端都试过
    assert "m2" in res["error"] and "402" in res["error"]