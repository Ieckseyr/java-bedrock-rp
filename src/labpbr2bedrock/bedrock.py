"""labPBR -> Bedrock PBR 的通道编码。

目标格式（NVIDIA《Minecraft with RTX PBR Texturing Guide》与 Bedrock 官方
Texture Set 文档）：

``*_normal.png``
    RGB 法线，DirectX（Y 向下）约定，默认中性色 (128, 128, 255)。
    Bedrock 规定 normal 与 heightmap 在同一 texture_set 中互斥。

``*_mer.png``
    R = 金属度, G = 自发光, B = 线性粗糙度。alpha 被忽略，写 3 通道更省空间。

``*_heightmap.png``
    1 通道（R）高度：0 = 向内凹陷, 0.5 = 不改变表面, 1 = 向外凸起。
    Bedrock 规定 normal 与 heightmap 互斥。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import ConversionSettings, PackMode
from .labpbr import DecodedNormal, DecodedSpecular

FULL = 255.0
HALF = 127.5


@dataclass(frozen=True)
class BedrockMaps:
    """一张贴图转换后的 Bedrock 图层。``None`` 表示该图层不应写出。"""

    normal: np.ndarray | None
    mer: np.ndarray | None
    heightmap: np.ndarray | None
    height_used: bool
    heightmap_referenced: bool = False
    """heightmap 是否被 texture_set 引用；False 表示只是随包附带的高度图文件。"""
    # --- 报告用统计 ---
    metal_ratio: float = 0.0
    emissive_ratio: float = 0.0
    mean_roughness: float = 0.0
    height_span: int = 0
    height_mean: float = 0.0


def encode_normal(
    decoded: DecodedNormal, settings: ConversionSettings
) -> np.ndarray:
    """把 labPBR 法线编码为 Bedrock 法线（RGB）。

    labPBR 的蓝通道存的是 AO，因此默认由 XY 重建 Z：

        x = R/127.5 - 1, y = G/127.5 - 1
        z = sqrt(max(0, 1 - x^2 - y^2))
        B = 127.5 * (z + 1)

    若 XY 长度 > 1（异常法线），先按比例缩放回单位圆再重建。
    """
    rgb = decoded.rgb.astype(np.float32)
    x = rgb[:, :, 0] / HALF - 1.0
    y = rgb[:, :, 1] / HALF - 1.0
    if settings.flip_green:
        y = -y

    length_sq = x * x + y * y
    over = length_sq > settings.normal_max_xy**2
    if np.any(over):
        scale = np.ones_like(length_sq)
        scale[over] = 1.0 / np.sqrt(length_sq[over])
        x *= scale
        y *= scale
        length_sq = x * x + y * y
    length_sq = np.clip(length_sq, 0.0, settings.normal_max_xy**2)

    out = np.empty_like(rgb, dtype=np.uint8)
    out[:, :, 0] = np.clip(np.rint(HALF * (x + 1.0)), 0, 255).astype(np.uint8)
    out[:, :, 1] = np.clip(np.rint(HALF * (y + 1.0)), 0, 255).astype(np.uint8)

    if settings.normal_z_mode == "copy":
        out[:, :, 2] = decoded.rgb[:, :, 2]
    else:
        z = np.sqrt(np.clip(1.0 - length_sq, 0.0, 1.0))
        out[:, :, 2] = np.clip(np.rint(HALF * (z + 1.0)), 0, 255).astype(np.uint8)
    return out


def encode_mer(
    decoded: DecodedSpecular, settings: ConversionSettings
) -> np.ndarray:
    """把 labPBR ``_s`` 编码为 Bedrock MER（RGB）。

    R 金属度:
        labPBR 绿通道 230..255 = 金属（含硬编码金属），其余为介电。
        Bedrock 没有 F0 通道，介电反射率无法表达，统一映射为 0。
    G 自发光:
        labPBR alpha 的 0..254，255 = 不发光；线性缩放到 0..255。
    B 粗糙度:
        默认 ``roughness = (1 - smoothness) ** 2``（labPBR 规范）。
    """
    smoothness = decoded.smoothness.astype(np.float32)
    if settings.roughness_mode.value == "linear":
        roughness = (1.0 - smoothness / FULL) ** 2
    else:
        roughness = 1.0 - smoothness / FULL
    out = np.empty((smoothness.shape[0], smoothness.shape[1], 3), dtype=np.uint8)
    out[:, :, 0] = np.where(
        decoded.f0 >= settings.metal_threshold, 255, 0
    ).astype(np.uint8)
    if decoded.emissive is None:
        out[:, :, 1] = 0
    else:
        emissive = decoded.emissive.astype(np.float32)
        scaled = np.rint(emissive * (FULL / settings.emissive_full))
        scaled = np.where(decoded.emissive >= 255, 0.0, scaled)
        out[:, :, 1] = np.clip(scaled, 0, 255).astype(np.uint8)
    out[:, :, 2] = np.clip(np.rint(roughness * FULL), 0, 255).astype(np.uint8)
    return out


def encode_heightmap(
    decoded: DecodedNormal, settings: ConversionSettings
) -> np.ndarray | None:
    """把 labPBR 高度（``_n`` alpha）编码为 Bedrock 1 通道高度图。

    labPBR：alpha 255 = 无位移，0 = 约 25% 深度（向内）。
    Bedrock：128 = 无位移，0 = 最深，255 = 最高。

    因此把 labPBR 的 [0, 255] 线性映射到 Bedrock 的 [中性值-深度, 中性值]：

        value = neutral * (1 - depth * (1 - alpha / 255))

    这样平坦表面（alpha=255）恰好落在中性值，不会整体鼓起；
    ``depth`` 控制视差强度（默认 1.0 用满向内区间）。
    """
    if decoded.height is None:
        return None
    alpha = decoded.height.astype(np.float32)
    alpha = np.maximum(alpha, float(settings.height_min))
    neutral = float(settings.height_neutral)
    value = neutral * (1.0 - settings.height_depth * (1.0 - alpha / FULL))
    return np.clip(np.rint(value), 0, 255).astype(np.uint8)


def select_layers(
    mode: PackMode,
    *,
    has_normal: bool,
    has_height: bool,
    has_specular: bool,
    mixed_json: str = "auto",
) -> tuple[bool, bool, bool]:
    """按打包模式决定写出哪些图层。

    返回 ``(write_normal, write_heightmap, write_mer)``。

    Bedrock 规则：同一 texture_set 中 normal 与 heightmap 只能二选一。
    """
    write_mer = has_specular
    if not has_normal:
        return False, False, write_mer

    if mode is PackMode.PBR:
        return True, False, write_mer
    if mode is PackMode.HEIGHTMAP:
        # 高度图模式：即便没有真实高度数据也写出中性高度图，
        # 保证同一套材质在所有方块上的表现一致。
        return False, True, write_mer
    # MIXED: 默认引用 normal（光追）；auto 时有真实高度则引用 heightmap。
    if mixed_json == "auto" and has_height:
        return False, True, write_mer
    return True, False, write_mer


def encode_maps(
    decoded_normal: DecodedNormal | None,
    decoded_specular: DecodedSpecular | None,
    *,
    mode: PackMode,
    settings: ConversionSettings,
) -> BedrockMaps:
    """把一张贴图的 labPBR 数据编码为 Bedrock 图层集合。"""
    has_normal = decoded_normal is not None
    has_height = bool(decoded_normal is not None and decoded_normal.has_height)
    write_normal, write_heightmap, write_mer = select_layers(
        mode,
        has_normal=has_normal,
        has_height=has_height,
        has_specular=decoded_specular is not None,
        mixed_json=settings.mixed_json,
    )

    normal = encode_normal(decoded_normal, settings) if write_normal else None
    heightmap = (
        encode_heightmap(decoded_normal, settings) if write_heightmap else None
    )
    # 纯高度图模式：法线是 RGB（没有 alpha 高度）时，写中性 128 高度图，
    # 保证 heightmap 包的 texture_set 始终有 heightmap 图层可引用。
    if (
        mode is PackMode.HEIGHTMAP
        and write_heightmap
        and heightmap is None
        and decoded_normal is not None
    ):
        heightmap = np.full(
            (decoded_normal.height_px, decoded_normal.width),
            settings.height_neutral,
            dtype=np.uint8,
        )
    heightmap_referenced = heightmap is not None

    # MIXED：始终附带一张高度图文件（不写进 JSON）：
    # - 有 alpha 的贴图用 alpha 生成（即使没有达到“真实高度”阈值）；
    # - 纯 RGB 法线没有高度数据，写中性 128。
    if (
        mode is PackMode.MIXED
        and settings.mixed_include_heightmap_files
        and normal is not None
        and heightmap is None
    ):
        heightmap = encode_heightmap(decoded_normal, settings) if decoded_normal else None
        if heightmap is None and decoded_normal is not None:
            heightmap = np.full(
                (decoded_normal.height_px, decoded_normal.width),
                settings.height_neutral,
                dtype=np.uint8,
            )
        heightmap_referenced = False

    mer = encode_mer(decoded_specular, settings) if write_mer else None

    metal_ratio = 0.0
    emissive_ratio = 0.0
    mean_roughness = 0.0
    if mer is not None:
        metal_ratio = float(np.count_nonzero(mer[:, :, 0] >= 128)) / mer[:, :, 0].size
        emissive_ratio = float(np.count_nonzero(mer[:, :, 1] > 0)) / mer[:, :, 1].size
        mean_roughness = float(mer[:, :, 2].mean()) / 255.0

    height_span = 0
    height_mean = 0.0
    if decoded_normal is not None and decoded_normal.height is not None:
        height_span = int(decoded_normal.height.max()) - int(decoded_normal.height.min())
        height_mean = float(decoded_normal.height.mean()) / 255.0

    return BedrockMaps(
        normal=normal,
        mer=mer,
        heightmap=heightmap,
        height_used=heightmap_referenced,
        heightmap_referenced=heightmap_referenced,
        metal_ratio=metal_ratio,
        emissive_ratio=emissive_ratio,
        mean_roughness=mean_roughness,
        height_span=height_span,
        height_mean=height_mean,
    )
