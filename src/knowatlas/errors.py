"""错误分类（完整方案 §10.1）。所有错误携带 entry_id 与 hint（给用户的下一步动作）。"""

from __future__ import annotations


class KnowAtlasError(Exception):
    """全部错误类的基类。"""

    def __init__(self, message: str, *, entry_id: str | None = None, hint: str = "") -> None:
        super().__init__(message)
        self.entry_id = entry_id
        self.hint = hint


class ContractError(KnowAtlasError):
    """字段 / scheme / 契约违例。同步时：该条目标记失败，继续。"""


class LocatorFormatError(ContractError):
    """locator 不符合 scheme 规范。"""


class UnknownSchemeError(ContractError):
    """未注册的 scheme。不静默跳过。"""


class DuplicateCapabilityError(KnowAtlasError):
    """能力注册表重名注册（防静默覆盖）。"""


class AdapterError(KnowAtlasError):
    """适配器读取源失败。同步时：跳过整个源，其余源继续。"""


class AuthExpiredError(AdapterError):
    """凭证失效。消息必须含重取指引（hint）。"""


class RateLimitError(AdapterError):
    """429 限流。指数退避；超限跳过该源本次。"""


class DegradedParseError(KnowAtlasError):
    """可降级解析失败（.emmx page.bin、PDF 等）。降级标题级，degraded=true。"""


class FetchError(KnowAtlasError):
    """抓取失败（网络错误、HTTP 4xx/5xx、正文过短）。实施期新增，见 CHANGELOG 0.1.0。"""


class ConfigError(KnowAtlasError):
    """配置缺失 / 非法。启动即退出（退出码 1）。"""
