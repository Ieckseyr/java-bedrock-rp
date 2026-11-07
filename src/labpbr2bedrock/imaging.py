"""图像读写工具。

约定：
- 所有像素运算统一使用 8 位 RGBA ``numpy.ndarray``（H, W, 4），避免中途出现
  16 位 / 调色板 / 灰度等模式带来的隐式转换；
- 写回 Bedrock 时按通道数显式选择 ``RGB`` / ``L``，不携带任何元数据，保证
  输出可复现（同样的输入永远得到同样的 PNG 字节）。
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from .errors import InvalidImageError

RGBA = "RGBA"
RGB = "RGB"
L = "L"


def open_png(data: bytes, *, path: str | None = None) -> Image.Image:
    """从字节解码 PNG，并强制读取像素。"""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # Pillow 的异常类型随版本变化，这里统一兜底
        raise InvalidImageError(f"无法解码 PNG：{exc}", path=path) from exc
    if image.format not in (None, "PNG"):
        raise InvalidImageError(f"期望 PNG，实际为 {image.format}", path=path)
    return image


def has_alpha(image: Image.Image) -> bool:
    """图片是否显式带有 alpha 通道（含调色板透明色）。"""
    return image.mode in {"RGBA", "LA", "PA", "RGBa", "La"} or "transparency" in image.info


def to_rgba8(image: Image.Image, *, path: str | None = None) -> np.ndarray:
    """把任意 Pillow 图片转成 8 位 RGBA 数组。

    16 位图像按 ``>> 8`` 缩放到 8 位；浮点图像按 0..1 线性缩放到 0..255。
    颜色管理（ICC）不做处理，保持原始数值。
    """
    mode = image.mode
    if mode in {"I;16", "I;16B", "I;16L", "I", "I;16N"}:
        raw = np.asarray(image)
        if raw.dtype == np.uint16:
            gray = (raw >> 8).astype(np.uint8)
        else:
            gray = np.clip(raw >> 8, 0, 255).astype(np.uint8)
        image = Image.fromarray(gray, mode=L)
    elif mode == "F":
        raw = np.asarray(image, dtype=np.float32)
        gray = np.clip(np.rint(raw), 0, 255).astype(np.uint8)
        image = Image.fromarray(gray, mode=L)

    try:
        rgba = np.asarray(image.convert(RGBA), dtype=np.uint8)
    except Exception as exc:  # pragma: no cover - 极端损坏文件
        raise InvalidImageError(f"无法转换为 RGBA：{exc}", path=path) from exc
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise InvalidImageError(f"RGBA 形状异常：{rgba.shape}", path=path)
    return np.ascontiguousarray(rgba)


def encode_png(array: np.ndarray, mode: str, *, compress_level: int = 6) -> bytes:
    """把数组编码为 PNG 字节。

    ``mode`` 只能是 ``RGB``、``RGBA`` 或 ``L``：
    - Bedrock 的 normal / MER 用 3 通道（官方允许 3 或 4 通道，3 通道更省空间）；
    - heightmap 必须是 1 通道。
    """
    array = np.ascontiguousarray(array)
    if mode == "L":
        if array.ndim != 2:
            raise ValueError(f"L 模式需要二维数组，实际 {array.shape}")
    elif mode in {"RGB", "RGBA"}:
        channels = 4 if mode == "RGBA" else 3
        if array.ndim != 3 or array.shape[2] != channels:
            raise ValueError(f"{mode} 模式需要 {channels} 通道，实际 {array.shape}")
    else:
        raise ValueError(f"不支持的 PNG 模式：{mode}")
    if array.dtype != np.uint8:
        raise ValueError(f"像素必须是 uint8，实际 {array.dtype}")

    image = Image.fromarray(array)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=compress_level)
    return buffer.getvalue()


def encode_tga(data: bytes) -> bytes:
    """把 PNG 字节转成 TGA（RLE），用于匹配新版 Bedrock 的 .tga 贴图。

    Bedrock 在同一目录内按 ``.tga > .png`` 选择贴图；当原版资源包使用
    ``.tga`` 时，同时提供 ``.tga`` 可以确保覆盖生效。TGA 保留 alpha。
    """
    image = open_png(data, path="<tga source>")
    if has_alpha(image):
        image = image.convert(RGBA)
    else:
        image = image.convert(RGB)
    buffer = io.BytesIO()
    image.save(buffer, format="TGA", compression="tga_rle")
    return buffer.getvalue()


def alpha_span(alpha: np.ndarray) -> int:
    """alpha 通道极差（0..255）。"""
    if alpha.size == 0:
        return 0
    return int(alpha.max()) - int(alpha.min())


def multiply_rgb_in_place(rgb: np.ndarray, factor: np.ndarray) -> None:
    """把 0..1 的系数乘进 8 位 RGB（用于可选 AO 烘焙）。"""
    rgb[...] = np.clip(
        np.rint(rgb.astype(np.float32) * factor[..., None]), 0, 255
    ).astype(np.uint8)
