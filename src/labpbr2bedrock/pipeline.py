"""转换流程编排。

职责：
1. 读取并叠加多个 Java 包；
2. 按规则把 Java 贴图名映射到 Bedrock 名；
3. 解码 labPBR、编码 Bedrock 图层（有界并发）；
4. 按打包模式写出 ``.mcpack``；
5. 产出可审计的报告。

设计要点：
* 单张贴图失败不会中断整包：错误被记录到报告并继续；
* 先规划再写出，保证 merge 模式不会产生重复 zip 条目；
* 颜色贴图默认按原始字节拷贝，不重新编码，既快又无损；
* 结果流式写出，内存占用与贴图总量无关。
"""

from __future__ import annotations

import io
import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from PIL import Image

from .bedrock import BedrockMaps, encode_maps
from .config import BuildSettings, ConversionSettings, PackMode, PipelineStats
from .errors import ConversionError, InvalidImageError
from .imaging import (
    encode_png,
    encode_tga,
    has_alpha,
    multiply_rgb_in_place,
    open_png,
    to_rgba8,
)
from .java_pack import BLOCK_ROOT, JavaPack, JavaPackStack, TextureGroup
from .labpbr import decode_normal, decode_specular
from .name_map import NameMapper, tga_only_paths
from .pack_writer import (
    BedrockPackWriter,
    build_manifest,
    build_texture_set,
    merge_texture_set,
)

logger = logging.getLogger("labpbr2bedrock")

BLOCKS_DIR = "textures/blocks"
README_NAME = "README.txt"
LICENSE_NAME = "LICENSE_source.txt"


# ---------------------------------------------------------------------- #
# 数据模型
# ---------------------------------------------------------------------- #
@dataclass
class TextureRecord:
    """单张贴图的处理记录（报告中逐条输出）。"""

    java_name: str
    target: str
    rule: str
    status: str
    has_normal: bool = False
    has_specular: bool = False
    has_height: bool = False
    layers: str = ""
    height_span: int = 0
    message: str = ""
    unreferenced: str = ""
    """随包写出但未写进 texture_set 的图层（例如 Mixed 模式的附带高度图）。"""


@dataclass
class ConversionResult:
    output: Path
    report_path: Path | None
    mode: PackMode
    stats: PipelineStats
    records: list[TextureRecord]
    duration_s: float
    size_bytes: int
    manifest: dict
    settings: ConversionSettings

    def summary(self) -> str:
        s = self.stats
        return (
            f"[{self.mode.value}] {self.output.name}: "
            f"{s.textures_written} 张贴图写入, "
            f"{s.textures_skipped_unmapped} 张未映射, "
            f"{s.textures_failed} 张失败, "
            f"{self.size_bytes / (1024 * 1024):.1f} MiB, "
            f"{self.duration_s:.1f}s"
        )


@dataclass
class _Planned:
    group: TextureGroup
    target: str
    rule: str
    base_size: tuple[int, int]
    normal_has_alpha: bool = False


@dataclass
class _Converted:
    plan: _Planned
    normal_png: bytes | None
    mer_png: bytes | None
    heightmap_png: bytes | None
    has_height: bool
    height_span: int
    notes: tuple[str, ...] = ()
    heightmap_referenced: bool = False


# ---------------------------------------------------------------------- #
# 工具函数
# ---------------------------------------------------------------------- #
def _probe_size(data: bytes, name: str) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception as exc:
        raise InvalidImageError(f"无法读取图片尺寸：{exc}", path=name) from exc


def _probe_alpha(data: bytes, name: str) -> bool:
    """只读文件头判断是否带 alpha（不完整解码像素）。"""
    try:
        with Image.open(io.BytesIO(data)) as image:
            return has_alpha(image)
    except Exception as exc:
        raise InvalidImageError(f"无法读取图片头：{exc}", path=name) from exc


def _will_write_pbr(plan: _Planned, mode: PackMode) -> bool:
    """预测该贴图在当前模式下是否至少会写出一个 PBR 图层。"""
    if plan.group.specular:
        return True
    if plan.group.normal is None:
        return False
    if mode is PackMode.HEIGHTMAP:
        return plan.normal_has_alpha
    return True


def _target_paths(target: str, color_ext: str = "png") -> dict[str, str]:
    """由 Bedrock 贴图相对名生成各图层路径（均相对包根）。"""
    folder, _, stem = target.rpartition("/")
    prefix = f"{folder}/" if folder else ""
    return {
        "color": f"{BLOCKS_DIR}/{target}.{color_ext}",
        "normal": f"{BLOCKS_DIR}/{prefix}{stem}_normal.png",
        "mer": f"{BLOCKS_DIR}/{prefix}{stem}_mer.png",
        "heightmap": f"{BLOCKS_DIR}/{prefix}{stem}_heightmap.png",
        "texture_set": f"{BLOCKS_DIR}/{target}.texture_set.json",
        "reference": stem,
    }


def _color_extension(target: str) -> str:
    """Bedrock 原版只提供 .tga 的贴图，我们也输出 .tga 以确保覆盖生效。"""
    return "tga" if target in tga_only_paths() else "png"


def _base_has_color(base: JavaPack, target: str) -> bool:
    """底板包是否已有该颜色贴图（任意 Bedrock 支持的扩展名）。"""
    folder, _, stem = target.rpartition("/")
    prefix = f"{BLOCKS_DIR}/{folder}/" if folder else f"{BLOCKS_DIR}/"
    return any(base.has(f"{prefix}{stem}{ext}") for ext in (".png", ".tga", ".jpg", ".jpeg"))


def _score_group(group: TextureGroup, rule: str) -> tuple:
    """同一 Bedrock 目标名出现多个 Java 来源时的取舍依据。"""
    return (
        1 if rule == "exact" else 0,
        int(bool(group.normal)) + int(bool(group.specular)),
        1 if not group.animated else 0,
        group.name,
    )


def _base_vocabulary(base_reader: JavaPack) -> set[str]:
    """收集底板包实际使用的贴图名，供命名映射优先命中。"""
    names: set[str] = set()
    prefix = "textures/blocks/"
    for name in base_reader.names():
        if name.startswith(prefix) and name.lower().endswith((".png", ".tga")):
            names.add(name[len(prefix) :].rsplit(".", 1)[0])
        elif name.endswith(".texture_set.json"):
            try:
                doc = json.loads(base_reader.read(name).decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            color = (doc.get("minecraft:texture_set") or {}).get("color")
            if isinstance(color, str):
                folder = name[len(prefix) :].rsplit("/", 1)[0] if "/" in name[len(prefix):] else ""
                names.add(f"{folder}/{color}" if folder else color)
    return names


# ---------------------------------------------------------------------- #
# 主流程
# ---------------------------------------------------------------------- #
def convert_pack(
    sources: Sequence[str | Path],
    output: str | Path,
    *,
    mode: PackMode = PackMode.MIXED,
    settings: ConversionSettings | None = None,
    base_pack: str | Path | None = None,
    pack_name: str | None = None,
    pack_description: str | None = None,
    jobs: int = 0,
    fill_missing_colors: bool = True,
    pack_icon: str | Path | None = None,
    vibrant_visuals: bool = False,
    report_path: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> ConversionResult:
    """把 Java labPBR 材质包转换为 Bedrock PBR 材质包。

    参数
    ----
    sources:
        Java 包路径列表，后者覆盖前者（BASE 放最前，附加包放后面）。
    output:
        输出 ``.mcpack`` 路径。
    mode:
        打包模式（pbr / heightmap / mixed）。
    base_pack:
        可选的现有 Bedrock 包。给出时以它为底板，只替换/补充 PBR 图层，
        保留其 blocks.json、雾效、颜色贴图等全部内容。
    jobs:
        并行度，0 表示自动。
    report_path:
        可选，写出 JSON 报告。
    """
    settings = settings or ConversionSettings()
    settings.validate()
    out_path = Path(output)
    source_stem = Path(sources[0]).stem if sources else "convert"
    if vibrant_visuals:
        capabilities: tuple[str, ...] = ("pbr",)
        min_engine = (1, 21, 120)
    else:
        capabilities = ("raytraced",)
        min_engine = (1, 16, 0)
    build = BuildSettings(
        mode=mode,
        output=out_path,
        pack_name=pack_name or f"labPBR2Bedrock {mode.label}",
        pack_description=pack_description or "Converted from Java labPBR",
        source_pack_name=source_stem,
        min_engine_version=min_engine,
        capabilities=capabilities,
        copy_color_textures=base_pack is None,
        source_license=None,
        pack_icon=Path(pack_icon) if pack_icon else None,
    )
    build.validate()

    def emit(message: str) -> None:
        if progress is not None:
            progress(message)
        else:
            logger.info(message)

    started = time.perf_counter()
    stats = PipelineStats()
    records: list[TextureRecord] = []

    stack = JavaPackStack([JavaPack(p) for p in sources])
    base_reader = JavaPack(base_pack) if base_pack else None
    writer: BedrockPackWriter | None = None
    try:
        groups = stack.texture_groups(BLOCK_ROOT)
        emit(f"扫描到 {len(groups)} 组 Java 方块贴图")

        mapper = NameMapper(
            preferred=_base_vocabulary(base_reader) if base_reader is not None else None
        )
        chosen: dict[str, _Planned] = {}
        for name, group in sorted(groups.items()):
            if group.animated:
                stats.textures_skipped_animated += 1
                records.append(
                    TextureRecord(
                        java_name=name,
                        target="",
                        rule="",
                        status="skipped_animated",
                        message="动画贴图未转换（Bedrock flipbook 需要单独的动画元数据）",
                    )
                )
                continue
            resolved = mapper.resolve(name)
            if resolved is None:
                stats.textures_skipped_unmapped += 1
                stats.unmapped[name] = "no bedrock equivalent"
                records.append(
                    TextureRecord(
                        java_name=name,
                        target="",
                        rule="",
                        status="skipped_unmapped",
                    )
                )
                continue
            try:
                base_size = _probe_size(stack.read(group.base), group.base)
                # 尺寸不一致的图层默认缩放对齐；关闭缩放时才提前判定失败。
                if not settings.resize_mismatched:
                    for layer_name, layer_path in (
                        ("法线", group.normal),
                        ("高光", group.specular),
                    ):
                        if layer_path and _probe_size(
                            stack.read(layer_path), layer_path
                        ) != base_size:
                            raise InvalidImageError(
                                f"{layer_name}尺寸与颜色 {base_size} 不一致",
                                path=layer_path,
                            )
            except ConversionError as exc:
                stats.textures_failed += 1
                stats.failed[name] = str(exc)
                records.append(
                    TextureRecord(
                        java_name=name,
                        target=resolved.target,
                        rule=resolved.rule,
                        status="failed",
                        message=str(exc),
                    )
                )
                continue
            plan = _Planned(
                group=group,
                target=resolved.target,
                rule=resolved.rule,
                base_size=base_size,
                normal_has_alpha=(
                    _probe_alpha(stack.read(group.normal), group.normal)
                    if group.normal
                    else False
                ),
            )
            current = chosen.get(plan.target)
            if current is None:
                chosen[plan.target] = plan
            elif _score_group(plan.group, plan.rule) > _score_group(
                current.group, current.rule
            ):
                stats.warnings.append(
                    f"目标名冲突：{current.group.name} 被 {plan.group.name} 取代（{plan.target}）"
                )
                stats.textures_skipped_conflict += 1
                records.append(
                    TextureRecord(
                        java_name=current.group.name,
                        target=current.target,
                        rule=current.rule,
                        status="skipped_conflict",
                        message=f"与 {plan.group.name} 指向同一 Bedrock 贴图，保留后者",
                    )
                )
                chosen[plan.target] = plan
            else:
                stats.warnings.append(
                    f"目标名冲突：{plan.group.name} 与 {current.group.name} 指向 "
                    f"{plan.target}，保留 {current.group.name}"
                )
                stats.textures_skipped_conflict += 1
                records.append(
                    TextureRecord(
                        java_name=plan.group.name,
                        target=plan.target,
                        rule=plan.rule,
                        status="skipped_conflict",
                        message=f"与 {current.group.name} 指向同一 Bedrock 贴图，保留前者",
                    )
                )

        plans = sorted(chosen.values(), key=lambda p: p.target)
        stats.textures_seen = len(groups)
        stats.textures_mapped = len(plans)
        emit(f"{len(plans)} 组贴图完成命名映射")

        # 规划会覆盖的包内路径，merge 模式下从底板拷贝时跳过它们
        planned_files: set[str] = set()
        for plan in plans:
            paths = _target_paths(plan.target)
            planned_files.update(paths[k] for k in ("normal", "mer", "heightmap"))
            if _will_write_pbr(plan, mode):
                planned_files.add(paths["texture_set"])
        if build.copy_color_textures:
            planned_files.update(
                _target_paths(p.target, _color_extension(p.target))["color"]
                for p in plans
            )
        if base_reader is not None and fill_missing_colors:
            # 底板没有的颜色贴图会用 Java 侧补齐，同样要避免重复入口
            for plan in plans:
                if not _base_has_color(base_reader, plan.target):
                    planned_files.add(
                        _target_paths(plan.target, _color_extension(plan.target))["color"]
                    )

        writer = BedrockPackWriter(out_path)
        _write_prologue(
            writer,
            stack=stack,
            base_reader=base_reader,
            build=build,
            planned_files=planned_files,
            emit=emit,
        )

        # ---- 颜色贴图 ----
        colors_written = 0
        for plan in plans:
            ext = _color_extension(plan.target)
            paths = _target_paths(plan.target, ext)
            if base_reader is not None and not fill_missing_colors:
                continue
            if base_reader is not None and _base_has_color(base_reader, plan.target):
                continue
            data = stack.read(plan.group.base)
            if settings.bake_ao and plan.group.normal:
                data = _bake_ao_into_color(stack.read(plan.group.normal), data)
            if ext == "tga":
                data = encode_tga(data)
            if writer.add(paths["color"], data, compress=False):
                colors_written += 1
        if colors_written:
            emit(f"写入颜色贴图 {colors_written} 张")

        # ---- PBR 图层 ----
        workers = jobs if jobs > 0 else min(8, max(1, (len(plans) + 7) // 8))
        records.extend(
            _write_pbr_layers(
                plans,
                stack=stack,
                writer=writer,
                mode=mode,
                settings=settings,
                base_reader=base_reader,
                workers=workers,
                stats=stats,
                emit=emit,
            )
        )

        _write_epilogue(writer, build=build, mode=mode, stats=stats)
        manifest = writer.manifest or {}
        writer.close()
        writer = None

        duration = time.perf_counter() - started
        result = ConversionResult(
            output=out_path,
            report_path=Path(report_path) if report_path else None,
            mode=mode,
            stats=stats,
            records=records,
            duration_s=duration,
            size_bytes=out_path.stat().st_size if out_path.exists() else 0,
            manifest=manifest,
            settings=settings,
        )
        if report_path:
            try:
                from .report import write_report

                write_report(result, Path(report_path), sources=[str(p) for p in sources])
            except Exception as exc:  # 报告失败不应让已完成的包变成失败
                stats.warnings.append(f"写报告失败：{exc}")
                logger.warning("写报告失败：%s", exc)
        emit(result.summary())
        return result
    except Exception:
        if writer is not None:
            writer.abort()
        raise
    finally:
        stack.close()
        if base_reader is not None:
            base_reader.close()


# ---------------------------------------------------------------------- #
# PBR 图层写出
# ---------------------------------------------------------------------- #
def _write_pbr_layers(
    plans: list[_Planned],
    *,
    stack: JavaPackStack,
    writer: BedrockPackWriter,
    mode: PackMode,
    settings: ConversionSettings,
    base_reader: JavaPack | None,
    workers: int,
    stats: PipelineStats,
    emit: Callable[[str], None],
) -> list[TextureRecord]:
    records: list[TextureRecord] = []
    if not plans:
        return records

    def read_inputs(plan: _Planned) -> tuple[bytes | None, bytes | None]:
        group = plan.group
        normal = stack.read(group.normal) if group.normal else None
        spec = stack.read(group.specular) if group.specular else None
        return normal, spec

    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        pending: list[tuple[Future, _Planned]] = []

        def submit(plan: _Planned) -> None:
            try:
                normal, spec = read_inputs(plan)
            except Exception as exc:  # 读取失败也要记录后继续
                stats.textures_failed += 1
                stats.failed[plan.group.name] = str(exc)
                records.append(
                    TextureRecord(
                        java_name=plan.group.name,
                        target=plan.target,
                        rule=plan.rule,
                        status="failed",
                        message=str(exc),
                    )
                )
                return
            pending.append(
                (
                    pool.submit(
                        _convert_one,
                        plan,
                        normal,
                        spec,
                        mode=mode,
                        settings=settings,
                    ),
                    plan,
                )
            )

        iterator = iter(plans)
        window = max(2, workers * 2)
        for plan in iterator:
            submit(plan)
            if len(pending) >= window:
                break

        # 按计划顺序消费结果：既保证 zip 条目顺序确定，又限制在途结果数量。
        while pending:
            future, plan = pending.pop(0)
            try:
                item = future.result()
            except Exception as exc:  # 单张贴图失败 -> 记录并继续
                stats.textures_failed += 1
                stats.failed[plan.group.name] = str(exc)
                records.append(
                    TextureRecord(
                        java_name=plan.group.name,
                        target=plan.target,
                        rule=plan.rule,
                        status="failed",
                        message=str(exc),
                    )
                )
            else:
                record = _write_one(item, writer, base_reader, stats)
                if record is not None:
                    records.append(record)
            completed += 1
            if completed % 100 == 0:
                emit(f"转换进度 {completed}/{len(plans)}")
            nxt = next(iterator, None)
            if nxt is not None:
                submit(nxt)
    return records


def _write_one(
    item: _Converted,
    writer: BedrockPackWriter,
    base_reader: JavaPack | None,
    stats: PipelineStats,
) -> TextureRecord | None:
    plan = item.plan
    paths = _target_paths(plan.target)
    if item.notes:
        stats.warnings.extend(f"{plan.target}: {note}" for note in item.notes)
    written_layers: list[str] = []
    unreferenced: list[str] = []
    if item.normal_png is not None:
        writer.add(paths["normal"], item.normal_png, compress=False)
        written_layers.append("normal")
        stats.textures_with_normal += 1
    if item.mer_png is not None:
        writer.add(paths["mer"], item.mer_png, compress=False)
        written_layers.append("mer")
        stats.textures_with_mer += 1
    if item.heightmap_png is not None:
        writer.add(paths["heightmap"], item.heightmap_png, compress=False)
        if item.heightmap_referenced:
            written_layers.append("heightmap")
        else:
            unreferenced.append("heightmap")
            stats.heightmap_files_unreferenced += 1
    if item.has_height:
        stats.textures_with_height += 1

    if not written_layers:
        # 没有可写的 PBR 图层：保留底板原有 texture_set，不覆盖
        return TextureRecord(
            java_name=plan.group.name,
            target=plan.target,
            rule=plan.rule,
            status="color_only",
            has_normal=bool(plan.group.normal),
            has_specular=bool(plan.group.specular),
        )

    reference = paths["reference"]
    existing: dict | None = None
    if base_reader is not None:
        raw = base_reader.read_optional(paths["texture_set"])
        if raw:
            try:
                existing = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                stats.warnings.append(f"忽略损坏的已有 texture_set：{paths['texture_set']}")
    if existing is not None:
        doc = merge_texture_set(
            existing,
            normal=f"{reference}_normal" if item.normal_png else None,
            mer=f"{reference}_mer" if item.mer_png else None,
            heightmap=(
                f"{reference}_heightmap" if item.heightmap_referenced else None
            ),
        )
    else:
        doc = build_texture_set(
            color=reference,
            normal=f"{reference}_normal" if item.normal_png else None,
            mer=f"{reference}_mer" if item.mer_png else None,
            heightmap=(
                f"{reference}_heightmap" if item.heightmap_referenced else None
            ),
        )
    writer.add_texture_set(paths["texture_set"], doc)
    stats.textures_written += 1
    return TextureRecord(
        java_name=plan.group.name,
        target=plan.target,
        rule=plan.rule,
        status="written",
        has_normal=bool(plan.group.normal),
        has_specular=bool(plan.group.specular),
        has_height=item.has_height,
        layers=",".join(written_layers),
        height_span=item.height_span,
        message="; ".join(item.notes),
        unreferenced=",".join(unreferenced),
    )


def _convert_one(
    plan: _Planned,
    normal_bytes: bytes | None,
    spec_bytes: bytes | None,
    *,
    mode: PackMode,
    settings: ConversionSettings,
) -> _Converted:
    group = plan.group
    decoded_normal = None
    decoded_spec = None
    notes: list[str] = []
    if normal_bytes is not None:
        image = open_png(normal_bytes, path=group.normal)
        rgba = to_rgba8(image, path=group.normal)
        if image.size != plan.base_size:
            if not settings.resize_mismatched:
                raise InvalidImageError(
                    f"法线尺寸 {image.size} 与颜色 {plan.base_size} 不一致",
                    path=group.normal,
                )
            rgba = _resize_rgba(rgba, plan.base_size)
            notes.append(f"法线 {image.size[0]}x{image.size[1]} 已缩放")
        decoded_normal = decode_normal(
            rgba,
            alpha_present=has_alpha(image),
            height_min_span=settings.height_min_span,
        )
    if spec_bytes is not None:
        image = open_png(spec_bytes, path=group.specular)
        rgba = to_rgba8(image, path=group.specular)
        if image.size != plan.base_size:
            if not settings.resize_mismatched:
                raise InvalidImageError(
                    f"高光尺寸 {image.size} 与颜色 {plan.base_size} 不一致",
                    path=group.specular,
                )
            rgba = _resize_rgba(rgba, plan.base_size)
            notes.append(f"高光 {image.size[0]}x{image.size[1]} 已缩放")
        decoded_spec = decode_specular(rgba, alpha_present=has_alpha(image))

    maps: BedrockMaps = encode_maps(
        decoded_normal, decoded_spec, mode=mode, settings=settings
    )
    return _Converted(
        plan=plan,
        normal_png=encode_png(maps.normal, "RGB") if maps.normal is not None else None,
        mer_png=encode_png(maps.mer, "RGB") if maps.mer is not None else None,
        heightmap_png=(
            encode_png(maps.heightmap, "L") if maps.heightmap is not None else None
        ),
        has_height=maps.height_used,
        height_span=maps.height_span,
        notes=tuple(notes),
        heightmap_referenced=maps.heightmap_referenced,
    )


def _resize_rgba(rgba: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """把 RGBA 数组缩放到目标尺寸（双线性，alpha 一起缩放）。"""
    image = Image.fromarray(rgba).resize(size, Image.Resampling.BILINEAR)
    return np.asarray(image, dtype=np.uint8)


# ---------------------------------------------------------------------- #
# 包级附属文件
# ---------------------------------------------------------------------- #
def _write_prologue(
    writer: BedrockPackWriter,
    *,
    stack: JavaPackStack,
    base_reader: JavaPack | None,
    build: BuildSettings,
    planned_files: set[str],
    emit: Callable[[str], None],
) -> None:
    """拷贝底板包（merge 模式）并写入图标。"""
    skip = {README_NAME, LICENSE_NAME, "manifest.json", "pack_icon.png"}
    copied = 0
    if base_reader is not None:
        for name in base_reader.names():
            if name in planned_files or name in skip:
                continue
            data = base_reader.read(name)
            writer.add(name, data, compress=name.endswith(".json"))
            copied += 1
        emit(f"已拷贝底板包 {copied} 个文件")

    license_text = stack.find_license()
    if license_text:
        writer.add(LICENSE_NAME, license_text.encode("utf-8"), compress=True)

    icon = None
    if build.pack_icon and Path(build.pack_icon).exists():
        icon = Path(build.pack_icon).read_bytes()
    elif base_reader is not None:
        icon = base_reader.read_optional("pack_icon.png")
    if icon is None:
        icon = stack.find_icon()
    if icon:
        writer.add("pack_icon.png", icon, compress=False)


def _write_epilogue(
    writer: BedrockPackWriter,
    *,
    build: BuildSettings,
    mode: PackMode,
    stats: PipelineStats,
) -> None:
    if mode is PackMode.HEIGHTMAP:
        mode_line = (
            "高度图为主：texture_set 引用 heightmap + MER；不写 normal。\n"
            "没有 alpha 高度的贴图会写中性 128 高度图；没有法线来源的贴图只有 color + MER。\n"
        )
    elif mode is PackMode.PBR:
        mode_line = (
            "PBR：texture_set 引用 normal + MER；不写 heightmap。\n"
            "这是高度图包的可选补充包，两个包一起启用可同时获得法线与视差。\n"
        )
    else:
        mode_line = (
            "Mixed（兼容旧格式）：有真实高度引用 heightmap，其余引用 normal；\n"
            "两种图层文件都会随包附带。\n"
        )
    readme = (
        "本包由 labpbr2bedrock 自动生成。\n\n"
        f"打包模式：{mode.value}\n"
        f"{mode_line}\n"
        "图层约定：\n"
        "- *_heightmap.png：1 通道高度（128 = 中性，0 = 向内凹陷）\n"
        "- *_normal.png：DirectX 约定法线（由 labPBR _n 的 XY 重建 Z）\n"
        "- *_mer.png：R 金属度 / G 自发光 / B 线性粗糙度\n\n"
        "版权提示：颜色贴图与 PBR 数据来自原始 Java 材质包，版权归原作者所有；"
        "本包仅供个人使用，请遵守原包的 LICENSE（见 LICENSE_source.txt）。\n"
    )
    if stats.unmapped:
        readme += f"\n未映射的 Java 贴图：{len(stats.unmapped)} 个（见报告）。\n"
    writer.add(README_NAME, readme.encode("utf-8"), compress=True)

    manifest = build_manifest(
        name=build.pack_name,
        description=build.pack_description,
        seed=f"{build.source_pack_name}/{build.mode.value}",
        min_engine_version=build.min_engine_version,
        capabilities=build.capabilities,
        license_note="Source pack license is included in " + LICENSE_NAME,
    )
    writer.add_manifest(manifest)


def _bake_ao_into_color(normal_bytes: bytes, color_bytes: bytes) -> bytes:
    """可选：把 labPBR 的 AO 乘进颜色贴图，返回重新编码的 PNG。"""
    normal = open_png(normal_bytes, path="normal")
    color = open_png(color_bytes, path="color")
    if normal.size != color.size:
        return color_bytes
    ao = to_rgba8(normal)[:, :, 2].astype("float32") / 255.0
    rgba = to_rgba8(color).copy()
    multiply_rgb_in_place(rgba[:, :, :3], ao)
    return encode_png(rgba, "RGBA")
