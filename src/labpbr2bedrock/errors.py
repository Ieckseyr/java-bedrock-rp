"""项目内统一异常。

所有异常都带 ``code``，便于在报告与 CLI 中稳定地分类，而不必解析消息文本。
"""

from __future__ import annotations


class ConversionError(Exception):
    """所有转换相关异常的基类。"""

    code = "conversion_error"

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path

    def __str__(self) -> str:  # pragma: no cover - 简单拼接
        base = super().__str__()
        return f"{base} ({self.path})" if self.path else base


class SourceError(ConversionError):
    """输入材质包无法读取或结构非法。"""

    code = "source_error"


class PackFormatError(ConversionError):
    """材质包结构／清单不符合预期。"""

    code = "pack_format_error"


class InvalidImageError(ConversionError):
    """图片无法解码，或尺寸／通道不符合要求。"""

    code = "invalid_image"


class MappingError(ConversionError):
    """贴图名无法映射到 Bedrock 命名。"""

    code = "mapping_error"
