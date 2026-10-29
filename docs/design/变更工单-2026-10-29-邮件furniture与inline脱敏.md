# 变更工单：邮件 furniture 剔除 + inline 脱敏 + 剥离率告警（批 97c · 8.9 邮件）

- 日期：2026-10-29
- 触发：R32 交接块「下一步 ①」——`知识索引工具-TODO.md` 8.9 邮件（97c：furniture 补丁 +
  redact + 线程还原）；用户 2026-10-29 21:1x 批准「按方案实施」。
- 关联：`知识索引工具-清洗层方案.md` §3.5（邮件清洗段）、§6（剥离率告警）、§4 代码地图
  「`adapters/maildir.py` ｜ quote_strip 补 furniture 剔除清单」；批 97a
  （`变更工单-2026-10-24-97a清洗层.md`，inline 不动、只清正文库的决定在本单被**收窄**）。

## 1. 现状（只读核对，2026-10-29 21:1x）

| 件 | 现状 |
|---|---|
| `adapters/maildir.py:190` | `delta = quote_strip(full_body)` 后直接当 `inline_content`；**无 furniture、无 redact** |
| `pipeline/sync/store.py::_store_bodies` | 只对 content_store 那份跑 `clean_text`（含 `redact`），**不动 inline**（97a 刻意为之：全量正文重建 inline 会破坏「增量摘要」口径） |
| 后果 | 邮件正文里的手机号 / 邮箱 / `sk-…` 原样进入 `inline_content` → 检索面、条目页、导出件全部可见；签名块 / 列表页脚 / 手机标语 / 保密免责四类噪声进正文与点抽取 |
| 本机真实数据 | **无 maildir**（`[sources.mail] enabled=false`、路径空；上一轮已扫过 `D:\sData` 与用户目录）。真实验收需用户给目录，本单先用合成 `.eml` 覆盖 |

97a 的「inline 不动」是为了保住「邮件 inline = 去引用的增量摘要」，不是拒绝脱敏——
本单只追加 **furniture + redact** 两步，仍然**不用全量正文重建 inline**，与 `test_maildir`
既有断言（`同意，我来排期` 在、`写道：` 不在）不冲突。

## 2. 方案

### 2.1 `pipeline/mail_threads.py::strip_furniture()`

适配器纪律：清洗函数只能住 `pipeline/`，适配器 import 使用（与 `quote_strip` 同款）。

```python
def strip_furniture(text: str) -> tuple[str, dict[str, int]]
```

四类规则（`_FURNITURE_RULES` 归类，返回 `{"signature":n,"list_footer":n,"mobile":n,
"disclaimer":n,"lines":删除的非空行数}`）：

| 类 | 触发形态 | 动作 |
|---|---|---|
| 签名块 | RFC 3676 分隔线 `--`（行内仅 `--` 或 `-- `） | 从该行**切到尾** |
| 列表页脚 | `unsubscribe` / `退订` / `取消订阅` / `您收到(此|这)(封)?邮件` / `You received this` / `此(邮|电)件由…发送` | 从该行切到尾 |
| 手机标语 | `发自我的 iPhone` / `发送自 iPhone` / `Sent from my iPhone` / `Get Outlook for iOS` / `发自网易邮箱大师` / `来自华为手机` 等（行首锚定） | **只删该行** |
| 免责声明 | `本邮件…保密/机密/泄露` / `This email and any attachments` / `本电邮所载…保密` | 从该行切到尾 |

三条防误杀闸门（都是真实邮件形态打出来的）：

1. **尾部窗口**：只在最后 `_TAIL_LINES = 30` 个**非空行**里找；页脚/免责要求位于
   后 50%（`_TRAIL_FRACTION = 0.5`）——正文中间讨论「unsubscribe 流程」不误切。
2. **围栏保护**：``` / ~~~ 代码块内的 `--` 是 markdown 分隔线，不是签名分隔线。
3. **不产出空正文**：删完为空则**原样返回**（签名只有两行的邮件不会变成空条目）。

### 2.2 `adapters/maildir.py`：inline 链路

```
full_body（适配器全量正文）
  → quote_strip            （已有，去引用）
  → strip_furniture        （本单新增）
  → redact                 （本单新增；受 [clean].redact_enabled 控制）
  = inline_content
```

- `redact` 直接复用 `pipeline/clean.py::redact`（同一套规则，不另写）；
- `[clean].redact_enabled=false` 时跳过脱敏（与 content_store 那份口径一致）；
- 全量正文仍走 `_store_bodies` 的 `clean_text`（含 redact），**双轨不变**；
- `content_hash` 仍按**全量正文**算（重同步幂等键不变，不受 inline 清洗影响）。

### 2.3 统计与告警（「剥离率 >90%」的口径更正）

原方案字面「单封剥离率 >90%」在真实邮件里是**常态**（一行回复 + 十行引用），照字面会天天告警。
落成两个指标 + 一个 WARN：

| 指标 | 定义 | 是否告警 |
|---|---|---|
| `strip_over90` | `1 - len(inline)/len(full) ≥ 0.9` 的封数 | **否**，只进 stats（观测用） |
| `strip_near_empty` | `len(full) ≥ 200` 且清洗后 `len(inline) < 20` | **是**：>0 即 WARN（规则过激的真实信号） |
| `warnings` | 源级字符串列表，`ksync` 打印 | — |

`not_rerun` 纪律：`strip_over90` 高不代表有问题，别据此改阈值。

### 2.4 审计字段

`Entry.meta["mail_clean"] = {"furniture_lines": n, "redacted": n, "strip_ratio": 0.0–1.0}`。

- 不复用 `meta["clean"]`：那个键由 `_store_bodies` 写（全量正文的清洗统计），同名会被覆盖；
- meta 是源自有字段，浅合并不冲突（`datalayer/_common.py::_SOURCE_FIELDS` 未变）。

## 3. 契约影响

| 契约 | 是否变化 |
|---|---|
| 表结构 / 迁移 | 无 |
| 字段 / `meta` 键 | **无**（新增 `meta.mail_clean` 是源自有子键，非表字段；`_SOURCE_FIELDS` 未变） |
| locator scheme / `SOURCE_TYPES` / `STATUSES` | 无 |
| REST 接口 | 无 |
| `CONFIG_SCHEMA_KEYS` | **无**（复用既有 `clean.enabled` / `clean.redact_enabled`，不新增键） |
| 能力注册表 | 无 |
| DataLayer 公开方法集 | 无（不新增方法） |
| 适配器 stats 键 | +`furniture_lines` / `inline_redacted` / `strip_over90` / `strip_near_empty` / `warnings`（诊断输出，非契约） |

## 4. 验证

1. 新增 `tests/test_mail_furniture.py`（~14 例）：四类规则各 1–3 例、围栏保护、尾部窗口防误切、
   删空兜底、`redact` 只作用 inline、`redact_enabled=false` 不脱敏、`strip_near_empty` 计数。
2. `tests/test_maildir.py` 补 2 例：inline 链路顺序（引用 + 签名 + 手机号）与 `meta.mail_clean`。
3. 定向：`pytest -o addopts= -q tests/test_mail_furniture.py tests/test_maildir.py tests/test_clean.py`。
4. 全量：`pytest -o addopts= -q`（基线 **789 passed / 1 skipped**）→ 期望 ≈805。
5. `tests/test_canary.py`（无新能力，指纹应零漂移）；`gen_docs --check` 三份。
6. 真库验收：**阻塞于「本机无 maildir」**，用户给目录后跑一次真库剥离前后对比
   （条目 inline 差异 + `strip_over90`/`strip_near_empty` 分布），本单不算完成。

## 5. 已知取舍

- furniture 只清 inline，content_store 保留全量含签名：FTS 全文完整、可溯源；条目页看到的是干净增量。
- 规则是「尾部启发式」，不做 ML；漏网形态（公司自定义页脚）靠 `warnings` 抽检发现后再补规则。
- 中英混排签名块若没有 `--` 分隔线不会被删（宁漏勿误）。
- 脱敏不可逆（`█`/`[手机]` 掩码）：inline 一旦落库，原文只能从 `content_store` 或源 maildir 取回。