"""Bedrock 资源包写出。

输出是 ``.mcpack``（本质为 zip）：

* 文件在 zip 根目录（manifest.json 在根），Minecraft 可直接导入；
* PNG 已压缩，zip 层用 STORED 存储以节省时间；JSON/文本用 DEFLATED；
* zip 条目时间戳固定为 1980-01-01，保证相同输入产生字节级可复现的产物；
* 先写 ``.part`` 临时文件，成功后原子重命名，避免半成品。
"""

from __future__ import annotations

import json
import os
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ._version import __version__
from .errors import PackFormatError

MANIFEST = "manifest.json"
FIXED_DATE = (1980, 1, 1, 0, 0, 0)
UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/labpbr2bedrock")
TEXTURE_SET_VERSION = "1.16.100"


def stable_uuid(seed: str) -> str:
    """由名称派生的确定性 UUID，保证重复构建不会产生随机清单。"""
    return str(uuid.uuid5(UUID_NAMESPACE, seed))


def build_manifest(
    *,
    name: str,
    description: str,
    seed: str,
    version: tuple[int, int, int] = (1, 0, 0),
    min_engine_version: tuple[int, int, int] = (1, 16, 0),
    capabilities: tuple[str, ...] = ("raytraced",),
    license_note: str | None = None,
) -> dict:
    """构造 Bedrock manifest（format_version 2）。"""
    if not name.strip():
        raise ValueError("manifest 名称不能为空")
    metadata: dict = {
        "authors": ["labpbr2bedrock"],
        "generated_with": {"labpbr2bedrock": [__version__]},
    }
    if license_note:
        metadata["license"] = license_note
    return {
        "format_version": 2,
        "header": {
            "name": name[:256],
            "description": description[:512],
            "uuid": stable_uuid(f"{seed}/header"),
            "version": list(version),
            "min_engine_version": list(min_engine_version),
        },
        "modules": [
            {
                "type": "resources",
                "uuid": stable_uuid(f"{seed}/module/resources"),
                "version": list(version),
            }
        ],
        "capabilities": list(capabilities),
        "metadata": metadata,
    }


def build_texture_set(
    *,
    color: str,
    normal: str | None = None,
    mer: str | None = None,
    heightmap: str | None = None,
) -> dict:
    """构造 ``*.texture_set.json``。

    参数都是“同一目录下的贴图名（不含扩展名）”。
    normal 与 heightmap 互斥；若同时给出，这里直接报错而不是写出无效 JSON。
    """
    if normal and heightmap:
        raise PackFormatError("texture_set 中 normal 与 heightmap 互斥")
    layer: dict[str, object] = {"color": color}
    if normal:
        layer["normal"] = normal
    if heightmap:
        layer["heightmap"] = heightmap
    if mer:
        layer["metalness_emissive_roughness"] = mer
    return {"format_version": TEXTURE_SET_VERSION, "minecraft:texture_set": layer}


def merge_texture_set(
    existing: dict,
    *,
    normal: str | None,
    mer: str | None,
    heightmap: str | None,
) -> dict:
    """在已有 texture_set 上合并新图层（用于 ``base-pack`` 模式）。

    规则：
    - 保留 ``color`` 与其它未知键；
    - normal / heightmap 互斥，按本次模式设置或删除；
    - MER 与 MERS 互斥，给出 MER 时删除 MERS（RTX 只认 MER）。
    """
    if normal and heightmap:
        raise PackFormatError("texture_set 中 normal 与 heightmap 互斥")
    data = json.loads(json.dumps(existing))  # 深拷贝，避免修改调用方对象
    layer = data.setdefault("minecraft:texture_set", {})
    if not isinstance(layer, dict):
        raise PackFormatError("已有 texture_set 结构非法")
    if normal:
        layer["normal"] = normal
    else:
        layer.pop("normal", None)
    if heightmap:
        layer["heightmap"] = heightmap
    else:
        layer.pop("heightmap", None)
    if mer:
        layer.pop("metalness_emissive_roughness_subsurface", None)
        layer["metalness_emissive_roughness"] = mer
    return data


@dataclass
class WriteStats:
    files: int = 0
    duplicates: int = 0
    bytes: int = 0


class BedrockPackWriter:
    """流式写出 zip，避免在磁盘上同时保留解包目录与压缩包。"""

    def __init__(self, output: Path) -> None:
        self.output = Path(output)
        self.tmp = self.output.with_name(self.output.name + ".part")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if self.tmp.exists():
            self.tmp.unlink()
        self._zip = zipfile.ZipFile(
            self.tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True
        )
        self._written: set[str] = set()
        self.stats = WriteStats()
        self.manifest: dict | None = None

    # ------------------------------------------------------------------ #
    def __enter__(self) -> "BedrockPackWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if exc_type is None:
            self.close()
        else:  # 失败时删除半成品
            self._zip.close()
            self.tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    def add(self, name: str, data: bytes, *, compress: bool = False) -> bool:
        """写入一个文件；重名时跳过并计数。"""
        name = name.replace("\\", "/").lstrip("/")
        if not name or name.endswith("/"):
            raise PackFormatError(f"非法条目名：{name!r}")
        if name in self._written:
            self.stats.duplicates += 1
            return False
        info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
        info.external_attr = 0o644 << 16
        info.compress_type = (
            zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
        )
        self._zip.writestr(info, data)
        self._written.add(name)
        self.stats.files += 1
        self.stats.bytes += len(data)
        return True

    def add_json(self, name: str, obj: object) -> bool:
        payload = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        return self.add(name, payload, compress=True)

    def add_texture_set(self, name: str, obj: dict) -> bool:
        return self.add_json(name, obj)

    def add_manifest(self, manifest: dict) -> bool:
        self.manifest = manifest
        return self.add_json(MANIFEST, manifest)

    def has(self, name: str) -> bool:
        return name in self._written

    def written(self) -> set[str]:
        return set(self._written)

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        self._zip.close()
        os.replace(self.tmp, self.output)

    def abort(self) -> None:
        self._zip.close()
        self.tmp.unlink(missing_ok=True)
