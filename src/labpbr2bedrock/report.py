"""转换报告。

报告分两份：
* ``*.json``：完整、机器可读，含每张贴图的映射关系与处理结果；
* ``*.md``：人读的摘要（统计、未映射清单、警告）。

报告是排查“为什么某个方块没有 PBR”的第一入口，因此不省略任何被跳过的条目。
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import TYPE_CHECKING

from . import __version__

if TYPE_CHECKING:  # pragma: no cover
    from .pipeline import ConversionResult


def _utc_now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).replace(microsecond=0).isoformat()


def build_report(result: "ConversionResult", *, sources: list[str]) -> dict:
    stats = result.stats
    settings = result.settings
    return {
        "tool": "labpbr2bedrock",
        "version": __version__,
        "generated_at": _utc_now(),
        "mode": result.mode.value,
        "sources": sources,
        "output": str(result.output),
        "size_bytes": result.size_bytes,
        "duration_s": round(result.duration_s, 3),
        "settings": {
            "metal_threshold": settings.metal_threshold,
            "roughness_mode": settings.roughness_mode.value,
            "emissive_full": settings.emissive_full,
            "flip_green": settings.flip_green,
            "normal_z_mode": settings.normal_z_mode,
            "height_min_span": settings.height_min_span,
            "height_neutral": settings.height_neutral,
            "height_depth": settings.height_depth,
            "height_min": settings.height_min,
            "bake_ao": settings.bake_ao,
            "resize_mismatched": settings.resize_mismatched,
        },
        "manifest": result.manifest,
        "stats": {
            "textures_seen": stats.textures_seen,
            "textures_mapped": stats.textures_mapped,
            "textures_written": stats.textures_written,
            "textures_with_normal": stats.textures_with_normal,
            "textures_with_height": stats.textures_with_height,
            "textures_with_mer": stats.textures_with_mer,
            "heightmap_files_unreferenced": stats.heightmap_files_unreferenced,
            "skipped_unmapped": stats.textures_skipped_unmapped,
            "skipped_conflict": stats.textures_skipped_conflict,
            "skipped_animated": stats.textures_skipped_animated,
            "failed": stats.textures_failed,
        },
        "unmapped": stats.unmapped,
        "failed": stats.failed,
        "warnings": stats.warnings,
        "textures": [
            {
                "java": r.java_name,
                "bedrock": r.target,
                "rule": r.rule,
                "status": r.status,
                "layers": r.layers,
                "unreferenced": r.unreferenced,
                "has_normal": r.has_normal,
                "has_specular": r.has_specular,
                "has_height": r.has_height,
                "height_span": r.height_span,
                "message": r.message,
            }
            for r in result.records
        ],
    }


def write_report(result: "ConversionResult", path: Path, *, sources: list[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = build_report(result, sources=sources)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = path.with_suffix(".md")
    md_path.write_text(_render_markdown(data), encoding="utf-8")


def _render_markdown(data: dict) -> str:
    stats = data["stats"]
    lines = [
        "# labpbr2bedrock 转换报告",
        "",
        f"- 时间：{data['generated_at']}",
        f"- 模式：**{data['mode']}**",
        f"- 输出：`{data['output']}`（{data['size_bytes'] / (1024 * 1024):.1f} MiB）",
        f"- 来源：{', '.join(f'`{s}`' for s in data['sources'])}",
        "",
        "## 统计",
        "",
        "| 项目 | 数量 |",
        "| --- | ---: |",
        f"| 扫描贴图 | {stats['textures_seen']} |",
        f"| 完成映射 | {stats['textures_mapped']} |",
        f"| 写出 texture_set | {stats['textures_written']} |",
        f"| 带 normal | {stats['textures_with_normal']} |",
        f"| 带 heightmap | {stats['textures_with_height']} |",
        f"| 附带未引用高度图 | {stats.get('heightmap_files_unreferenced', 0)} |",
        f"| 带 MER | {stats['textures_with_mer']} |",
        f"| 未映射 | {stats['skipped_unmapped']} |",
        f"| 目标名冲突跳过 | {stats['skipped_conflict']} |",
        f"| 动画跳过 | {stats['skipped_animated']} |",
        f"| 失败 | {stats['failed']} |",
        "",
    ]
    if data["unmapped"]:
        lines += ["## 未映射的 Java 贴图", ""]
        lines += [f"- `{name}`" for name in sorted(data["unmapped"])[:200]]
        if len(data["unmapped"]) > 200:
            lines.append(f"- …… 其余 {len(data['unmapped']) - 200} 个见 JSON 报告")
        lines.append("")
    if data["failed"]:
        lines += ["## 失败条目", ""]
        lines += [f"- `{name}`：{msg}" for name, msg in sorted(data["failed"].items())]
        lines.append("")
    if data["warnings"]:
        lines += ["## 警告", ""]
        lines += [f"- {w}" for w in data["warnings"][:200]]
        if len(data["warnings"]) > 200:
            lines.append(f"- …… 其余 {len(data['warnings']) - 200} 条见 JSON 报告")
        lines.append("")
    lines += [
        "## 图层统计说明",
        "",
        "- `heightmap` 仅在有真实 alpha 变化的贴图上出现（`height_min_span` 控制阈值）。",
        "- `mixed` 模式下，有真实高度的贴图使用 heightmap，其余使用 normal。",
        "",
    ]
    return "\n".join(lines)
