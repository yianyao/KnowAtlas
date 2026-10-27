"""生成三份参考文档：命令 / 配置 / 接口（只读源码与示例配置，不写库）。

产出：
  docs/参考-命令.md
  docs/参考-配置.md
  docs/参考-接口.md

说明：这是 temp/ 下的过程脚本（AGENTS §4.6）。验证通过后再提升为 tools/gen_docs.py，
并加一条"文档与代码一致"的测试。
"""
from __future__ import annotations

import argparse
import inspect
import re
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs"

EXAMPLE = ROOT / "config" / "knowatlas.example.toml"
HEAD = ("> 本文件由脚本从源码生成，**不要手改**；改代码/配置后重跑 `uv run python tools/gen_docs.py`。\n"
        "> 生成口径：命令行取 `argparse` 解析树，配置取 `CONFIG_SCHEMA_KEYS` + 示例文件 + `Config` 默认值，\n"
        "> 接口取 FastAPI 应用的 `app.routes`（一次性构建在临时空库上，不联网）。\n")


# ---------------- 1. 命令 ----------------
def gen_commands() -> str:
    from knowatlas.cli import build_parser

    parser = build_parser()
    subs = {}
    helps = {}
    for action in parser._subparsers._group_actions:  # noqa: SLF001
        subs.update(action.choices)
        for ca in getattr(action, "_choices_actions", []):
            helps[ca.dest] = ca.help or ""

    def describe(name: str, sub) -> str:
        own = (sub.description or "").strip()
        if own:
            return own
        return (helps.get(name) or "").strip()

    lines = ["# 参考 · 命令（CLI）\n", HEAD, f"共 **{len(subs)}** 个子命令。\n",
             "## 一览\n", "| 命令 | 作用 | 参数数 |", "|---|---|---|"]
    for name in sorted(subs):
        sub = subs[name]
        desc = describe(name, sub).splitlines()[0] if describe(name, sub) else ""
        n = len([a for a in sub._actions if a.dest != "help"])  # noqa: SLF001
        lines.append(f"| `{name}` | {desc} | {n} |")

    for name in sorted(subs):
        sub = subs[name]
        desc = describe(name, sub)
        lines += [f"\n## `{name}`\n"]
        if desc:
            lines += [f"{desc}\n"]
        lines += [f"用法：`{sub.format_usage().strip().replace('usage: ', '')}`\n",
                  "| 参数 | 取值 | 默认 | 说明 |", "|---|---|---|---|"]
        for a in sub._actions:  # noqa: SLF001
            if a.dest == "help":
                continue
            flags = ", ".join(f"`{s}`" for s in a.option_strings) or f"`{a.dest}`"
            if isinstance(a, argparse._SubParsersAction):  # noqa: SLF001
                flags = f"`{{{','.join(a.choices)}}}`"
                choices = "、".join(a.choices)
            elif a.choices:
                choices = "、".join(str(c) for c in a.choices)
            elif isinstance(a, (argparse._StoreTrueAction, argparse._StoreFalseAction)):  # noqa: SLF001
                choices = "开关"
            elif a.option_strings:
                choices = f"`{a.metavar or a.dest.upper()}`"
            else:
                choices = f"`{a.dest.upper()}`"
            default = "—" if a.default in (None, False) else (
                "true" if a.default is True else str(a.default))
            if a.default is False:
                default = "false"
            help_txt = (a.help or "").replace("\n", " ")
            lines.append(f"| {flags} | {choices} | {default} | {help_txt} |")
    lines.append("""
## 需要 LLM / 网络的命令（人工维护）

| 命令 | 何时会调用外部 |
|---|---|
| `kadd` | 抓正文（网络）；分类/提炼（LLM，未配置时降级） |
| `ksync` | 抓正文（网络）；分类与命名（LLM，可关） |
| `kpoints` | 抽点（LLM；`--dry-run` 也会调，注意费用） |
| `kaging` | L2 时效复核 / 点级老化（LLM） |
| `kerrata` | 事实核查（LLM） |
| `kauto` | 抓正文 + 抽点 + 老化（`--dry-run` 完全零费用） |
| `kpeimport` | 纯本地导入（不联网、不调 LLM） |
| `kcheck` | 链接体检（网络，可 `--dry-run`） |
| `kexport` / `kbackup` / `ktest` / `kinit` | 纯本地 |
""")
    return "\n".join(lines).rstrip() + "\n"


# ---------------- 2. 配置 ----------------
CLASS = {
    "general": ("D", "部署参数：换机器/换目录就要改"),
    "web": ("D", "部署参数：Web 鉴权入口"),
    "llm": ("T", "领域阈值：模型与采样（密钥本体走环境变量）"),
    "embedding": ("T", "领域阈值：向量后端"),
    "fetch": ("T", "领域阈值：抓取节流与后端"),
    "clean": ("T", "领域阈值：清洗开关（细阈值是 I 类，见 ADR）"),
    "aging": ("T", "领域阈值：老化节奏与域闸门"),
    "ingest": ("T", "领域阈值：巡检预算"),
    "points": ("T", "领域阈值：分块与点数上限"),
    "sources": ("D", "部署参数：本机数据源位置"),
}
INTERNAL = [
    ("清洗阈值（页码占比、目录点线、重复行、推广窗口）", "pipeline/clean.py::CleanThresholds",
     "从 5.9 M 字符真实语料量出；开放会变成「可配置成洗不干净」"),
    ("自洽性闸门阈值（裸名词/截断/代码块未闭合）", "pipeline/point_gate.py",
     "它定义「什么算合格知识点」，可调等于什么都能过"),
    ("EOL 表（技术与版本 → 停产日期）", "semantic/eol.py::EOL",
     "数据驱动，更新走工单；放配置会让判据版本不可追溯"),
    ("点分诊/老化批大小（AGING_BATCH 等）", "pipeline/aging.py、lifecycle.py",
     "性能参数，跟数据量有关，按需改代码"),
]


def parse_example() -> tuple[dict, dict]:
    """返回 (值表, 注释表)：dotted key → tomllib 值 / 说明文字。"""
    text = EXAMPLE.read_text(encoding="utf-8").splitlines()
    values = tomllib.loads("\n".join(text))
    flat: dict = {}

    def walk(node: dict, prefix: str = "") -> None:
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                if prefix == "sources":  # 每个源是一张形状不同的表，作为一个键展示
                    flat[key] = {f"__keys__": sorted(v.keys())}
                else:
                    walk(v, key)
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                flat[key] = {f"__array__": sorted(v[0].keys())}
            else:
                flat[key] = v

    walk(values)
    comments: dict = {}
    section = ""
    block: list[str] = []
    for line in text:
        s = line.strip()
        if s.startswith("["):
            m = re.match(r"\[([^\]#]+)", s)
            if m:
                section = m.group(1).strip()
                block = []
                continue
        if not s:
            block = []
            continue
        if s.startswith("#"):
            block.append(s.lstrip("#").strip())
            continue
        if "=" not in s:
            block = []
            continue
        ok, _, rest = s.partition("=")
        key = ok.strip()
        value = rest.strip()
        inline = ""
        cut = value.find(" #")
        if cut >= 0:
            value, inline = value[:cut].strip(), value[cut + 1:].lstrip("#").strip()
        desc = inline or " ".join(block)
        desc = " ".join(desc.split())
        if len(desc) > 160:
            desc = desc[:157].rstrip("，。；、 ") + "…"
        comments[f"{section}.{key}"] = desc
        block = []
    return flat, comments


PREFIXED = {"aging": "aging_", "ingest": "ingest_", "points": "points_"}


def _type_name(v) -> str:
    if isinstance(v, Path):
        return "路径"
    if isinstance(v, bool):
        return "布尔"
    if isinstance(v, int):
        return "整数"
    if isinstance(v, float):
        return "小数"
    if isinstance(v, (list, tuple)):
        return "字符串数组"
    if isinstance(v, dict):
        return "表"
    if v is None:
        return "—"
    return "字符串"


def _prop(key: str) -> str:
    sec, _, short = key.partition(".")
    short = short.replace(".", "_")
    return PREFIXED.get(sec, "") + short


def _fmt(v) -> str:
    if isinstance(v, Path):
        return v.as_posix()
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v in (None, ""):
        return "（空）"
    if isinstance(v, (list, tuple)):
        return "、".join(str(x) for x in v) if v else "（空）"
    if isinstance(v, dict):
        keys = v.get("__keys__") or v.get("__array__") or []
        if keys:
            return "表（" + "、".join(keys) + "）"
        return f"表（{len(v)} 项）"
    return str(v)


def gen_config() -> str:
    from knowatlas.config import CONFIG_SCHEMA_KEYS, Config

    cfg = Config({}, Path("<generated>"))
    flat, comments = parse_example()
    lines = ["# 参考 · 配置\n", HEAD,
             f"共 **{len(CONFIG_SCHEMA_KEYS)}** 个键，分 **10** 段。加载顺序：\n",
             "```\n代码默认值  <  config 文件  <  环境变量 KNOWATLAS_<段>_<键>\n```\n",
             "配置文件路径默认 `config/knowatlas.toml`（相对当前目录），可用环境变量 "
             "`KNOWATLAS_CONFIG` 指定任意路径（**已支持**）。\n",
             "类别：**D** 部署参数 · **S** 秘密 · **T** 领域阈值 · **I** 实现常量（见文末）。\n",
             "「代码默认」有值 = 该键有 `Config` 属性（不写配置也生效）；「—」= 只有代码内默认。\n"]
    by_sec: dict[str, list[str]] = {}
    for key in CONFIG_SCHEMA_KEYS:
        by_sec.setdefault(key.split(".", 1)[0], []).append(key)

    for sec in by_sec:
        cls = CLASS.get(sec, ("T", ""))[0]
        lines += [f"\n## `[{sec}]`（{cls} 类）\n"]
        lines += ["| 键 | 类型 | 代码默认 | 示例文件值 | 说明 |", "|---|---|---|---|---|"]
        for key in by_sec[sec]:
            short = key.split(".", 1)[1]
            prop = _prop(key)
            default = None
            if hasattr(cfg, prop):
                try:
                    default = getattr(cfg, prop)
                except Exception:  # noqa: BLE001
                    default = None
            ex_val = flat.get(key)
            tname = _type_name(default if default is not None else ex_val)
            desc = comments.get(key, "")
            lines.append(f"| `{short}` | {tname} | {_fmt(default) if default is not None else '—'} "
                         f"| {_fmt(ex_val) if ex_val is not None else '—'} | {desc} |")

    lines += ["\n## 秘密（S 类，不在配置文件里）\n",
              "密钥/令牌只从环境变量读，配置文件只写变量名（`*_env`）。\n",
              "| 环境变量 | 用途 |", "|---|---|",
              "| `KNOWATLAS_LLM_API_KEY` | LLM 主 key（DeepSeek 等） |",
              "| `KNOWATLAS_LLM_API_KEY_SF1` / `_SF2` | 备用 LLM key（多后端轮换） |",
              "| `KNOWATLAS_WEB_TOKEN` | Web 写操作令牌 |",
              "| `KNOWATLAS_HOME` | 数据根（覆盖 `general.db_path` 的相对基准） |",
              "| `KNOWATLAS_CONFIG` | 指定配置文件路径 |",
              "| `KNOWATLAS_SOFFICE_PATH` | 旧版 Office 转换后端（可选） |",
              "",
              "## 实现常量（I 类，不开放）\n",
              "| 常量 | 位置 | 为什么不开放 |", "|---|---|---|"]
    for name, loc, why in INTERNAL:
        lines.append(f"| {name} | `{loc}` | {why} |")
    lines.append("")
    return "\n".join(lines)


# ---------------- 3. 接口 ----------------
WRITE = {"POST", "PUT", "PATCH", "DELETE"}


def gen_api() -> str:
    from knowatlas.config import Config
    from knowatlas.datalayer.db import DataLayer
    from knowatlas.web.app import create_app

    data = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="ka-docs-"))
    cfg = Config(data, EXAMPLE)
    cfg.raw.setdefault("general", {})["db_path"] = str(tmp / "k.db")
    cfg.raw["general"]["content_root"] = str(tmp / "content")
    cfg.raw["general"]["backup_dir"] = str(tmp / "backup")
    dl = DataLayer(cfg.db_path)
    dl.init_schema()
    app = create_app(cfg, dl, None, None, start_ingest=False)

    rows = []
    missing: list[str] = []
    spec = app.openapi()
    for path, ops in spec.get("paths", {}).items():
        if not path.startswith("/api"):
            continue
        for m, op in ops.items():
            if m.upper() in {"HEAD", "OPTIONS"}:
                continue
            desc = (op.get("description") or "").strip().splitlines()
            summary = (desc[0].strip() if desc else "") or (op.get("summary") or "")
            summary = summary.strip().rstrip("。.")
            if not desc:
                missing.append(f"{m.upper()} `{path}`")
            params = []
            has_body = "requestBody" in op
            for p in op.get("parameters", []):
                name = p.get("name", "")
                req = "*" if p.get("required") else ""
                params.append(f"{name}{req}")
            if has_body:
                params.append("body")
            rows.append((path, m.upper(), summary, ", ".join(params)))
    rows.sort(key=lambda x: (x[0], x[1]))

    groups: dict[str, list] = {}
    for path, m, summary, params in rows:
        seg = path.split("/")
        g = seg[2] if len(seg) > 2 and seg[2] else "root"
        groups.setdefault(g, []).append((path, m, summary, params))

    lines = ["# 参考 · 接口（REST）\n", HEAD,
             f"共 **{len(rows)}** 个端点，分 **{len(groups)}** 组；前缀 `/api`。\n",
             "写操作（POST/PUT/PATCH/DELETE）需要三件套：`X-KnowAtlas-Token` 头 + "
             "`application/json` + Host/Origin 命中白名单。\n"]
    lines += ["| 组 | 端点数 |", "|---|---|"]
    for g in sorted(groups):
        lines.append(f"| `{g}` | {len(groups[g])} |")

    for g in sorted(groups):
        lines += [f"\n## `{g}`\n", "| 方法 | 路径 | 作用 | 查询参数 |", "|---|---|---|---|"]
        for path, m, summary, params in groups[g]:
            tag = "**写**" if m in WRITE else ""
            lines.append(f"| {m} {tag} | `{path}` | {summary or '—'} | {params or '—'} |")
    if missing:
        lines += ["\n## 缺少 docstring 的端点（补一行说明即可）\n",
                  "下表端点的「作用」是从函数名自动转的，说明还没写：\n"]
        for item in sorted(missing):
            lines.append(f"- {item}")
    lines.append("")
    dl.close()
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in args
    docs = {
        "参考-命令.md": gen_commands(),
        "参考-配置.md": gen_config(),
        "参考-接口.md": gen_api(),
    }
    drift = 0
    for name, text in docs.items():
        p = OUT / name
        if check:
            old = p.read_text(encoding="utf-8") if p.is_file() else ""
            if old == text:
                print(f"OK   {p}")
            else:
                drift += 1
                print(f"DIFF {p}：文档与源码不一致，重跑 `python tools/gen_docs.py`")
            continue
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"OK {p} {len(text.splitlines())} 行")
    return 1 if check and drift else 0


if __name__ == "__main__":
    raise SystemExit(main())