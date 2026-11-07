"""产物校验：把 .mcpack 当成 Minecraft 来检查。

检查项对应官方 Texture Set 文档中的硬性规则（违反会导致整个
texture_set 被丢弃并记录 CONTENT_ERROR）：

1. manifest 可解析，含 header / modules（resources）；
2. 每个 texture_set：
   - 存在 ``minecraft:texture_set`` 且含 ``color``；
   - ``normal`` 与 ``heightmap`` 不同时出现；
   - MER 与 MERS 不同时出现；
   - 引用的贴图能在**同一个包**里找到；
   - 通道数符合要求（heightmap 必须单通道）；
4. 所有被引用的图片可解码。

此外给出统计信息（texture_set 数、normal/heightmap/MER 数量），
便于确认打包模式真的生效。
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

IMAGE_EXTENSIONS = (".tga", ".png", ".jpg", ".jpeg")
"""与 Bedrock 的文件优先级一致：.tga > .png > .jpg > .jpeg。"""


@dataclass
class Issue:
    level: str  # error | warning
    code: str
    path: str
    message: str

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    pack: Path
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level: str, code: str, path: str, message: str) -> None:
        issue = Issue(level=level, code=code, path=path, message=message)
        (self.errors if level == "error" else self.warnings).append(issue)

    def summary(self) -> str:
        s = self.stats
        return (
            f"{self.pack.name}: {'通过' if self.ok else '失败'} "
            f"({len(self.errors)} 错误 / {len(self.warnings)} 警告) — "
            f"texture_set={s.get('texture_sets', 0)}, "
            f"normal={s.get('normal_sets', 0)}, "
            f"heightmap={s.get('heightmap_sets', 0)}, "
            f"mer={s.get('mer_sets', 0)}, "
            f"图片={s.get('images', 0)}"
        )


def _find_texture(names: set[str], folder: str, reference: str) -> str | None:
    """按 Bedrock 的扩展名优先级查找被引用的贴图。"""
    reference = reference.replace("\\", "/").lstrip("/")
    candidates = []
    if "/" in reference:
        candidates.append(reference)
    else:
        candidates.append(f"{folder}/{reference}" if folder else reference)
    for base in candidates:
        for ext in IMAGE_EXTENSIONS:
            name = f"{base}{ext}"
            if name in names:
                return name
    # 兜底：在 textures/blocks 根目录查找
    leaf = reference.rsplit("/", 1)[-1]
    for ext in IMAGE_EXTENSIONS:
        name = f"textures/blocks/{leaf}{ext}"
        if name in names:
            return name
    return None


def _png_mode(data: bytes) -> str | None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.mode
    except Exception:
        return None


def validate_pack(path: str | Path) -> ValidationReport:
    pack = Path(path)
    report = ValidationReport(pack=pack)
    if not pack.exists():
        report.add("error", "missing_file", str(pack), "文件不存在")
        return report
    try:
        archive = zipfile.ZipFile(pack)
    except zipfile.BadZipFile:
        report.add("error", "bad_zip", pack.name, "不是有效的 zip / mcpack")
        return report

    names = set(archive.namelist())
    report.stats["entries"] = len(names)

    # ---- manifest ----
    if "manifest.json" not in names:
        report.add("error", "missing_manifest", "manifest.json", "缺少 manifest.json")
    else:
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8-sig"))
        except Exception as exc:
            report.add("error", "bad_manifest", "manifest.json", f"JSON 解析失败：{exc}")
            manifest = {}
        if manifest:
            header = manifest.get("header") or {}
            modules = manifest.get("modules") or []
            if not header:
                report.add("error", "bad_manifest", "manifest.json", "缺少 header")
            else:
                try:
                    uuid.UUID(str(header.get("uuid", "")))
                except ValueError:
                    report.add("error", "bad_uuid", "manifest.json", "header.uuid 非法")
            if not modules or not any(m.get("type") == "resources" for m in modules):
                report.add(
                    "error", "bad_manifest", "manifest.json", "缺少 resources 模块"
                )
            if not isinstance(manifest.get("capabilities", []), list):
                report.add(
                    "warning", "bad_manifest", "manifest.json", "capabilities 不是数组"
                )
            report.stats["format_version"] = manifest.get("format_version")

    # ---- texture sets ----
    texture_sets = [n for n in names if n.endswith(".texture_set.json")]
    used_textures: dict[str, str] = {}
    image_count = 0
    for name in texture_sets:
        folder = name.rsplit("/", 1)[0] if "/" in name else ""
        try:
            doc = json.loads(archive.read(name).decode("utf-8-sig"))
        except Exception as exc:
            report.add("error", "bad_texture_set", name, f"JSON 解析失败：{exc}")
            continue
        layer = doc.get("minecraft:texture_set")
        if not isinstance(layer, dict):
            report.add("error", "bad_texture_set", name, "缺少 minecraft:texture_set")
            continue
        color = layer.get("color")
        if color is None:
            report.add("error", "missing_color", name, "缺少 color 图层")
        elif isinstance(color, str):
            resolved = _find_texture(names, folder, color)
            if resolved is None:
                report.add(
                    "error", "missing_texture", name, f"color 引用的贴图不存在：{color}"
                )
            else:
                used_textures[resolved] = name
        elif not (isinstance(color, list) and len(color) in (3, 4)):
            report.add("error", "bad_color", name, "color 既不是贴图名也不是颜色值")

        normal = layer.get("normal")
        heightmap = layer.get("heightmap")
        mer = layer.get("metalness_emissive_roughness")
        mers = layer.get("metalness_emissive_roughness_subsurface")
        if normal is not None and heightmap is not None:
            report.add(
                "error",
                "normal_heightmap_conflict",
                name,
                "normal 与 heightmap 不能同时存在（整个 texture_set 会失效）",
            )
        if mer is not None and mers is not None:
            report.add(
                "error", "mer_mers_conflict", name, "MER 与 MERS 不能同时存在"
            )
        for key, value, channels in (
            ("normal", normal, (3, 4)),
            ("metalness_emissive_roughness", mer, (3, 4)),
            ("metalness_emissive_roughness_subsurface", mers, (4,)),
            ("heightmap", heightmap, (1,)),
        ):
            if value is None or not isinstance(value, str):
                continue
            resolved = _find_texture(names, folder, value)
            if resolved is None:
                report.add(
                    "error",
                    "missing_texture",
                    name,
                    f"{key} 引用的贴图不存在：{value}",
                )
                continue
            used_textures[resolved] = name
            data = archive.read(resolved)
            mode = _png_mode(data)
            if mode is None:
                report.add("error", "bad_image", resolved, "图片无法解码")
                continue
            actual = {"L": 1, "LA": 2, "RGB": 3, "RGBA": 4, "P": 0}.get(mode)
            if actual is None:
                # TGA 等格式 Pillow 会以 RGB/RGBA 打开；未知模式仅警告
                report.add(
                    "warning", "unknown_mode", resolved, f"未知图片模式：{mode}"
                )
                continue
            if key == "heightmap" and actual != 1:
                report.add(
                    "error",
                    "heightmap_channels",
                    resolved,
                    f"heightmap 必须单通道，实际 {mode}",
                )
            elif key != "heightmap" and actual not in channels:
                report.add(
                    "error",
                    "channels",
                    resolved,
                    f"{key} 需要 {channels} 通道，实际 {mode}",
                )
        if normal is not None:
            report.stats["normal_sets"] = report.stats.get("normal_sets", 0) + 1
        if heightmap is not None:
            report.stats["heightmap_sets"] = report.stats.get("heightmap_sets", 0) + 1
        if mer is not None:
            report.stats["mer_sets"] = report.stats.get("mer_sets", 0) + 1
        if mers is not None:
            report.stats["mers_sets"] = report.stats.get("mers_sets", 0) + 1

    image_count = sum(1 for n in names if n.lower().endswith(IMAGE_EXTENSIONS))
    report.stats["texture_sets"] = len(texture_sets)
    report.stats["images"] = image_count
    report.stats["referenced_images"] = len(used_textures)
    orphan = [
        n
        for n in names
        if n.lower().endswith((".png", ".tga"))
        and n.startswith("textures/")
        and n not in used_textures
    ]
    report.stats["orphan_images"] = len(orphan)
    archive.close()
    return report
