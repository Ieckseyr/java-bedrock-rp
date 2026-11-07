"""labpbr2bedrock —— 把 Java 版 labPBR 材质转换为基岩版（RTX / Vibrant Visuals）PBR 材质。

公开 API::

    from labpbr2bedrock import convert_pack, ConversionSettings, PackMode

    convert_pack(
        sources=["rotrBLOCKS BASE.zip"],
        output="rotrBLOCKS_bedrock_pbr.mcpack",
        mode=PackMode.PBR,
    )

模块划分::

    imaging     图像读写与 8 位 RGBA 归一化
    labpbr      labPBR 1.3（_n / _s）解码
    bedrock     Bedrock MER / normal / heightmap 编码
    name_map    Java -> Bedrock 贴图名映射
    java_pack   Java 材质包（zip / 目录）读取与多包叠加
    pipeline    转换流程编排
    pack_writer Bedrock 资源包写出
    validate    产物结构校验
"""

from __future__ import annotations

from ._version import __version__  # noqa: E402

from .config import ConversionSettings, PackMode
from .errors import (
    ConversionError,
    InvalidImageError,
    MappingError,
    PackFormatError,
    SourceError,
)
from .pipeline import ConversionResult, convert_pack

__all__ = [
    "ConversionError",
    "ConversionResult",
    "ConversionSettings",
    "InvalidImageError",
    "MappingError",
    "PackFormatError",
    "PackMode",
    "SourceError",
    "convert_pack",
    "__version__",
]
