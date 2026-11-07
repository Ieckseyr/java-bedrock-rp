"""转换参数与打包模式。

这里集中放置所有会影响数值结果的配置，保证：
1. 每个参数都有默认值、取值范围与说明；
2. 单元测试只依赖这些显式参数，不依赖全局状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PackMode(str, Enum):
    """打包模式。

    Bedrock 规定同一个 texture_set 中 ``normal`` 与 ``heightmap`` 互斥，
    因此三种模式在“每张贴图用哪一种高度信息”上做取舍：

    - ``PBR``:       只用 normal + MER（最通用，细节来自法线）。
    - ``HEIGHTMAP``: 只用 heightmap + MER（视差效果，细节来自高度图。
                     对没有真实高度数据的贴图会写出中性高度图，因而损失法线细节）。
    - ``MIXED``:     自动选择：有真实高度数据的贴图用 heightmap，其余用 normal。
                     这是默认推荐模式，既合法又能保留最多细节。
    """

    PBR = "pbr"
    HEIGHTMAP = "heightmap"
    MIXED = "mixed"

    @classmethod
    def parse(cls, value: str) -> "PackMode":
        try:
            return cls(value.strip().lower())
        except ValueError as exc:  # pragma: no cover - 由 CLI 先行校验
            raise ValueError(
                f"未知打包模式 {value!r}，可选：pbr / heightmap / mixed"
            ) from exc

    @property
    def label(self) -> str:
        return {
            PackMode.PBR: "PBR",
            PackMode.HEIGHTMAP: "Heightmap",
            PackMode.MIXED: "Mixed",
        }[self]


class RoughnessMode(str, Enum):
    """labPBR 感知光滑度 -> Bedrock 粗糙度的换算方式。

    labPBR 规范定义 ``roughness_linear = (1 - perceptual_smoothness) ** 2``；
    Bedrock 的 MER 蓝通道是线性粗糙度，因此默认用 ``LINEAR``。
    少数材质按“感知粗糙度”制作，可用 ``PERCEPTUAL`` 直接取反。
    """

    LINEAR = "linear"
    PERCEPTUAL = "perceptual"

    @classmethod
    def parse(cls, value: str) -> "RoughnessMode":
        try:
            return cls(value.strip().lower())
        except ValueError as exc:  # pragma: no cover
            raise ValueError(
                f"未知粗糙度模式 {value!r}，可选：linear / perceptual"
            ) from exc


@dataclass(frozen=True)
class ConversionSettings:
    """单张材质转换的数值参数（全部有界、可复现）。"""

    # ---- labPBR 解码 ----
    metal_threshold: int = 230
    """labPBR `_s` 绿通道 >= 该值视为金属（230-255 为硬编码金属区间）。"""

    roughness_mode: RoughnessMode = RoughnessMode.LINEAR
    """感知光滑度 -> 线性粗糙度的换算方式。"""

    emissive_full: int = 254
    """labPBR `_s` alpha 中代表 100% 自发光的数值上限（255 表示无自发光）。"""

    flip_green: bool = False
    """是否翻转法线绿通道。

    labPBR 与 Bedrock RTX 均采用 DirectX（Y 向下）约定，默认不翻转。
    仅当目标平台/引擎使用 OpenGL 约定时才需要打开。
    """

    normal_z_mode: str = "reconstruct"
    """法线蓝通道处理：``reconstruct``（由 XY 重建 Z，推荐）或 ``copy``。

    labPBR 的 ``_n`` 蓝通道存的是 AO 而不是 Z，直接复制会让 Bedrock
    收到长度不为 1 的法线，因此默认重建。``copy`` 仅用于对比排查。
    """

    # ---- 高度图 ----
    height_min_span: int = 8
    """alpha 极差小于该值视为“没有真实高度数据”。"""

    height_neutral: int = 128
    """Bedrock 高度图的中性值（0.5 ≈ 128）。"""

    height_depth: float = 1.0
    """labPBR 高度向 Bedrock 凹陷方向映射的比例。

    1.0 表示 labPBR 的 0..255 用满 Bedrock 的中性值~最低值区间；
    0.5 表示只使用一半深度，效果更保守。
    """

    height_min: int = 1
    """labPBR 规范建议高度图最小值不低于 1，0 会在部分 POM 实现中出问题。"""

    # ---- 其它 ----
    bake_ao: bool = False
    """是否把 labPBR 的 AO（`_n` 蓝通道）乘进颜色贴图。

    默认关闭：Bedrock 没有 AO 通道，且烘焙 AO 会改变原始颜色，
    仅在明确需要“AO 版颜色贴图”时开启。
    """

    normal_max_xy: float = 1.0
    """XY 长度上限，用于兜底归一化异常法线。"""

    resize_mismatched: bool = True
    """法线/高光分辨率与颜色不一致时是否缩放对齐。

    Emiores 这类附加包常用 256x256 的自发光遮罩搭配 512x512 颜色贴图；
    统一缩放到颜色分辨率，保证 texture_set 的三个图层尺寸一致。
    关闭后尺寸不一致的贴图会被判定为失败并跳过。
    """

    mixed_include_heightmap_files: bool = True
    """MIXED 模式下始终附带一张高度图文件（不被 JSON 引用）。

    这样同一份 Mixed 包同时包含颜色、法线、高度三种贴图；texture_set 走 normal，
    高度图留给叠加或手动调整。
    """

    mixed_json: str = "auto"
    """MIXED 模式下 texture_set 引用谁：

    - ``auto``（默认，目标格式）：有真实高度时引用 heightmap，否则引用 normal；
      两种情况下都会额外写高度图/法线文件，实现“视差 + 法线”的混合包；
    - ``normal``：始终引用 normal（面向光追），高度图仅附带。
    """

    def validate(self) -> None:
        if not 0 <= self.metal_threshold <= 255:
            raise ValueError("metal_threshold 必须在 0..255")
        if not 1 <= self.emissive_full <= 255:
            raise ValueError("emissive_full 必须在 1..255")
        if not 0 <= self.height_min_span <= 255:
            raise ValueError("height_min_span 必须在 0..255")
        if not 0 <= self.height_neutral <= 255:
            raise ValueError("height_neutral 必须在 0..255")
        if not 0.0 < self.height_depth <= 1.0:
            raise ValueError("height_depth 必须位于 (0, 1]")
        if not 0 <= self.height_min <= 255:
            raise ValueError("height_min 必须在 0..255")
        if self.normal_z_mode not in {"reconstruct", "copy"}:
            raise ValueError("normal_z_mode 必须是 reconstruct 或 copy")
        if self.mixed_json not in {"normal", "auto"}:
            raise ValueError("mixed_json 必须是 normal 或 auto")


@dataclass(frozen=True)
class BuildSettings:
    """一次打包的输入输出与命名配置。"""

    mode: PackMode
    output: Path
    pack_name: str = "Converted Pack"
    pack_description: str = "Converted from Java labPBR"
    source_pack_name: str = "convert"
    min_engine_version: tuple[int, int, int] = (1, 16, 0)
    capabilities: tuple[str, ...] = ("raytraced",)
    keep_work_dir: bool = False
    copy_color_textures: bool = True
    include_entities: bool = False
    include_items: bool = False
    pack_icon: Path | None = None
    source_license: str | None = None

    def validate(self) -> None:
        if self.output.suffix.lower() != ".mcpack":
            raise ValueError("输出文件必须使用 .mcpack 扩展名（本质是 zip）")
        if not self.source_pack_name:
            raise ValueError("source_pack_name 不能为空")


@dataclass
class PipelineStats:
    """运行过程中的计数，用于报告。"""

    textures_seen: int = 0
    textures_mapped: int = 0
    textures_with_pbr: int = 0
    textures_with_normal: int = 0
    textures_with_height: int = 0
    textures_with_mer: int = 0
    heightmap_files_unreferenced: int = 0
    textures_written: int = 0
    textures_skipped_unmapped: int = 0
    textures_skipped_conflict: int = 0
    textures_skipped_missing_color: int = 0
    textures_skipped_animated: int = 0
    textures_failed: int = 0
    bytes_written: int = 0
    warnings: list[str] = field(default_factory=list)
    unmapped: dict[str, str] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
