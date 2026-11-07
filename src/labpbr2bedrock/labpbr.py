"""labPBR 1.3 数据解码。

参考 shaderLABS 规范（https://shaderlabs.org/wiki/LabPBR_Material_Standard）：

``_n.png``（法线）
    R = 法线 X（0 左, 255 右）
    G = 法线 Y（0 上, 255 下，DirectX / Y- 约定）
    B = 材质 AO（0 = 100% 遮挡, 255 = 无遮挡），**不是 Z**
    A = 高度/位移（255 = 无位移, 0 = 约 25% 深度）

``_s.png``（高光）
    R = 感知光滑度（0 = 全粗糙, 255 = 全光滑）
    G = F0/反射率：0..229 为介电反射率，230..255 为金属
    B = 0..64 孔隙度；65..255 次表面散射（SSS）
    A = 自发光（0..254；255 表示无自发光，通常来自无 alpha 的 RGB 图）

本模块只做“解码”，不做任何 Bedrock 侧取舍，便于单独测试。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .imaging import alpha_span


@dataclass(frozen=True)
class DecodedNormal:
    """labPBR 法线贴图的解码结果。"""

    rgb: np.ndarray
    """HxWx3 uint8，R=X / G=Y / B=AO。"""

    height: np.ndarray | None
    """HxW uint8 高度（alpha），无 alpha 时为 None。"""

    has_height: bool
    """是否存在“有变化”的高度数据（极差 >= height_min_span）。"""

    width: int
    height_px: int

    def __post_init__(self) -> None:
        if self.rgb.ndim != 3 or self.rgb.shape[2] != 3:
            raise ValueError(f"法线 RGB 形状非法：{self.rgb.shape}")
        if self.height is not None and self.height.shape != self.rgb.shape[:2]:
            raise ValueError("高度通道尺寸与 RGB 不一致")


@dataclass(frozen=True)
class DecodedSpecular:
    """labPBR 高光贴图的解码结果。"""

    smoothness: np.ndarray
    f0: np.ndarray
    porosity_sss: np.ndarray
    emissive: np.ndarray | None
    has_emissive: bool
    width: int
    height_px: int

    def __post_init__(self) -> None:
        shape = self.smoothness.shape
        for name, arr in (
            ("f0", self.f0),
            ("porosity_sss", self.porosity_sss),
            ("emissive", self.emissive),
        ):
            if arr is not None and arr.shape != shape:
                raise ValueError(f"{name} 尺寸不一致：{arr.shape} != {shape}")


def decode_normal(
    rgba: np.ndarray, *, alpha_present: bool, height_min_span: int = 8
) -> DecodedNormal:
    """解码 labPBR ``_n`` 贴图。

    参数
    ----
    rgba:
        HxWx4 uint8（由 :func:`imaging.to_rgba8` 归一化）。
    alpha_present:
        原图是否真的带 alpha。RGB 图会被 Pillow 补成不透明，不能据此判断高度。
    height_min_span:
        alpha 极差低于该值时视为没有真实高度数据。
    """
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"需要 HxWx4 的 RGBA 数组，实际 {rgba.shape}")
    rgb = np.ascontiguousarray(rgba[:, :, :3])
    height = rgba[:, :, 3] if alpha_present else None
    has_height = bool(
        height is not None and alpha_span(height) >= int(height_min_span)
    )
    h, w = rgb.shape[:2]
    return DecodedNormal(
        rgb=rgb,
        height=height,
        has_height=has_height,
        width=w,
        height_px=h,
    )


def decode_specular(
    rgba: np.ndarray, *, alpha_present: bool
) -> DecodedSpecular:
    """解码 labPBR ``_s`` 贴图。

    注意 ``alpha_present`` 用于区分“RGB 高光图（无自发光）”与
    “RGBA 高光图（alpha=自发光，255 表示不发光）”。
    """
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"需要 HxWx4 的 RGBA 数组，实际 {rgba.shape}")
    smoothness = np.ascontiguousarray(rgba[:, :, 0])
    f0 = np.ascontiguousarray(rgba[:, :, 1])
    porosity_sss = np.ascontiguousarray(rgba[:, :, 2])
    emissive = np.ascontiguousarray(rgba[:, :, 3]) if alpha_present else None
    # 全为 255 的 alpha 表示“没有自发光”；出现 <255 的像素才算有。
    has_emissive = bool(emissive is not None and int(emissive.min()) < 255)
    h, w = smoothness.shape
    return DecodedSpecular(
        smoothness=smoothness,
        f0=f0,
        porosity_sss=porosity_sss,
        emissive=emissive,
        has_emissive=has_emissive,
        width=w,
        height_px=h,
    )


def decode_ao(normal: DecodedNormal) -> np.ndarray:
    """labPBR 的 AO 位于法线蓝通道（0 = 全遮挡, 255 = 无遮挡）。"""
    return normal.rgb[:, :, 2]
