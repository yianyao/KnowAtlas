"""勘误 L1 确定性错误检查（方案 §7.6，0.2.0 第六十四批，Phase 7 批次 65a）。

定位：纯规则、零费用，**只做确定性错误**防误报——L1 误报会淹没裁决队列并毁掉
功能信誉（方案 §7.6 原文）。两类确定性信号：

| kind  | 规则                                                             |
|-------|------------------------------------------------------------------|
| syntax | 完整 Python 代码块（```python 围栏）ast.parse 失败               |
| api    | 代码块中使用**已移除**（removed 级）API，对照表内置官方依据       |

防误报纪律（宁漏勿误）：
- 代码片段多为节选——带节选特征（REPL 前缀 / 首行缩进 / `...` 占位 / 语言未标）
  的一律**不下结论**（也不送 LLM：疑似交 L2 全量核查，那是 65b 用户裁决的事）；
- API 对照表只收「已移除 + 替代明确 + 官方依据」条目；deprecated（仍能跑）不收；
- 正文提及 API 名不算（讲废弃的文章是正常内容），只查代码块；
- `np.float64` / `pd.concat` 这类合法名用词边界与排除名单防误报。

死链（确定性错误第三类）已有独立通道（kcheck → meta.link_status=dead →
管理页失效链接），本模块不重复承接。

边界：纯函数、无 IO、无库依赖（ast 为标准库）；跨条目编排与落库在
pipeline/errata.py。
"""

from __future__ import annotations

import ast
import re

# ---- 完整代码块提取 ----

_FENCE_RE = re.compile(
    r"```([A-Za-z0-9_+#-]*)[ \t]*\r?\n(.*?)```", re.DOTALL
)
_PY_LANGS = {"python", "py", "python3"}
# 语言未标的围栏块保守跳过：无法确认是 Python（bash/json 误判会大量误报）

# 节选特征：命中任一 → 不下结论（疑似，交 L2/人）
_REPL_RE = re.compile(r"^\s*>>>", re.MULTILINE)
_ELLIPSIS_RE = re.compile(r"^\s*\.\.\.\s*$", re.MULTILINE)


def extract_python_blocks(body: str) -> list[str]:
    """提取正文中标注 Python 的围栏代码块（未标语言的跳过——无法确认语言）。"""
    out = []
    for m in _FENCE_RE.finditer(str(body or "")):
        lang = m.group(1).strip().lower()
        if lang in _PY_LANGS:
            out.append(m.group(2))
    return out


def looks_like_excerpt(code: str) -> bool:
    """节选特征判定：REPL 示例 / `...` 省略占位 / 首行缩进（函数体中段）。"""
    if _REPL_RE.search(code) or _ELLIPSIS_RE.search(code):
        return True
    first = next((ln for ln in code.splitlines() if ln.strip()), "")
    return bool(first) and first[0] in " \t"


def verify_syntax(code: str) -> str | None:
    """完整块语法验证；SyntaxError 返回「行 N: 消息」，通过返回 None。"""
    try:
        ast.parse(code)
    except SyntaxError as exc:
        line = f"行 {exc.lineno}: " if exc.lineno else ""
        return f"{line}{exc.msg}"
    return None


# ---- 已移除 API 对照表（只收 removed 级 + 官方依据；deprecated 不收） ----

# 标准库：模块级 import 即命中（Python 3.12/3.13 移除批，PEP 594 + PEP 632）
_REMOVED_STDLIB: tuple[tuple[str, str, str, str], ...] = (
    # (模块名, 移除版本, 官方依据, 替代)
    ("imp", "Python 3.12", "PEP 594", "importlib"),
    ("distutils", "Python 3.12", "PEP 632", "setuptools / sysconfig"),
    ("asyncore", "Python 3.12", "PEP 594", "asyncio"),
    ("asynchat", "Python 3.12", "PEP 594", "asyncio"),
    ("smtpd", "Python 3.12", "PEP 594", "aiosmtpd"),
    ("cgi", "Python 3.13", "PEP 594", "email.parser / multipart"),
    ("cgitb", "Python 3.13", "PEP 594", "traceback"),
    ("telnetlib", "Python 3.13", "PEP 594", "telnetlib3"),
    ("pipes", "Python 3.13", "PEP 594", "subprocess"),
    ("crypt", "Python 3.13", "PEP 594", "argon2-cffi / bcrypt"),
    ("imghdr", "Python 3.13", "PEP 594", "filetype / pure-magic"),
    ("nntplib", "Python 3.13", "PEP 594", "第三方 nntp 客户端"),
    ("xdrlib", "Python 3.13", "PEP 594", "struct / 第三方 xdr 库"),
    ("uu", "Python 3.13", "PEP 594", "binascii"),
)
_IMPORT_RE_TPL = r"^[ \t]*(?:import[ \t]+{mod}\b|from[ \t]+{mod}\b)"

# 第三方著名 removed API：词边界 + 后向断言防合法名误报（np.float64 等）
_REMOVED_THIRD_PARTY: tuple[tuple[str, str, str, str, str], ...] = (
    # (pattern, API 名, 移除版本, 官方依据, 替代)
    (r"\bnp\.(?:float|int|bool|object|str)\b(?!\w)", "numpy 内建类型别名",
     "NumPy 1.24", "NumPy 1.24 官方迁移指南", "np.float64 / Python 内建类型"),
    (r"\btf\.contrib\b", "tf.contrib", "TensorFlow 2.0",
     "TensorFlow 官方迁移指南", "tf.compat.v1 或对应 tf.* 模块"),
    (r"\bsklearn\.cross_validation\b", "sklearn.cross_validation",
     "scikit-learn 0.20", "scikit-learn 官方迁移说明", "sklearn.model_selection"),
    (r"\bpandas\.datetools\b|\bpd\.datetools\b", "pandas.datetools",
     "pandas 1.0", "pandas 官方变更日志", "pandas._libs.tslibs / dateutil"),
)

_IMPORT_LINE_RE_CACHE: dict[str, re.Pattern[str]] = {}
_THIRD_PARTY_RE: tuple[tuple[re.Pattern[str], str, str, str, str], ...] = tuple(
    (re.compile(p), name, ver, ev, rep) for p, name, ver, ev, rep in _REMOVED_THIRD_PARTY
)


def _import_hits(mod: str, code: str) -> bool:
    pat = _IMPORT_LINE_RE_CACHE.get(mod)
    if pat is None:
        pat = re.compile(_IMPORT_RE_TPL.format(mod=mod), re.MULTILINE)
        _IMPORT_LINE_RE_CACHE[mod] = pat
    return bool(pat.search(code))


def check_text(body: str) -> list[dict[str, str]]:
    """单条正文确定性错误检查；返回错误清单（空 = 无确定性错误）。

    返回元素 {"kind": syntax|api, "detail": 人类可读描述（含依据）}。
    只查 Python 围栏代码块；节选特征命中不下结论；正文提及不误报。
    """
    findings: list[dict[str, str]] = []
    for code in extract_python_blocks(body):
        if looks_like_excerpt(code):
            continue  # 疑似节选：不下确定性结论（宁漏勿误）
        err = verify_syntax(code)
        if err:
            findings.append({"kind": "syntax", "detail": f"完整代码块语法错误（{err}）"})
        for mod, ver, ev, rep in _REMOVED_STDLIB:
            if _import_hits(mod, code):
                findings.append({
                    "kind": "api",
                    "detail": f"代码 import 已移除模块 {mod}（{ver} 移除，依据 {ev}；"
                              f"替代：{rep}）",
                })
        for pat, name, ver, ev, rep in _THIRD_PARTY_RE:
            if pat.search(code):
                findings.append({
                    "kind": "api",
                    "detail": f"代码使用已移除 API {name}（{ver} 移除，依据 {ev}；"
                              f"替代：{rep}）",
                })
    return findings
