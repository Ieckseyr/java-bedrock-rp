"""命令行入口。

用法示例::

    # 生成三种打包（推荐）
    python -m labpbr2bedrock convert \\
        --java-pack "材质包/Java/rotrBLOCKS BASE V73 1.21.4-1.13 512x.zip" \\
        --java-pack "材质包/Java/rotrBLOCKS Emiores 1.20.1-1.13 256-512x.zip" \\
        --all-modes --out out

    # 只生成一种
    python -m labpbr2bedrock convert --java-pack pack.zip --mode mixed -o out/pack_bedrock_mixed.mcpack

    # 校验产物
    python -m labpbr2bedrock validate out/pack_bedrock_mixed.mcpack

    # 查看 Java -> Bedrock 命名映射覆盖率
    python -m labpbr2bedrock map --java-pack pack.zip

    # 文件夹模式：把 zip 丢进 input/，自动生成到 output/
    python -m labpbr2bedrock run            # 首次运行自动创建 config.json 与文件夹
    python -m labpbr2bedrock run --watch    # 持续监视 input/
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from . import __version__
from .config import ConversionSettings, PackMode, RoughnessMode
from .errors import ConversionError
from .pipeline import convert_pack
from .validate import validate_pack

LOGGER = logging.getLogger("labpbr2bedrock")


def _configure_stdio() -> None:
    """Windows 控制台默认可能是 GBK，统一切到 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _sanitize(stem: str) -> str:
    stem = stem.strip().replace(" ", "_")
    stem = re.sub(r"[^0-9A-Za-z_\-\.]+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("._")
    return stem or "pack"


def _settings_from_args(args: argparse.Namespace) -> ConversionSettings:
    return ConversionSettings(
        metal_threshold=args.metal_threshold,
        roughness_mode=RoughnessMode.parse(args.roughness),
        flip_green=args.flip_green,
        height_min_span=args.height_min_span,
        height_depth=args.height_depth,
        bake_ao=args.bake_ao,
        resize_mismatched=not args.no_resize,
        mixed_include_heightmap_files=not args.no_extra_heightmaps,
    )


def _resolve_modes(args: argparse.Namespace) -> list[PackMode]:
    if args.all_modes:
        return [PackMode.PBR, PackMode.HEIGHTMAP, PackMode.MIXED]
    if args.mode:
        return [PackMode.parse(m) for m in args.mode]
    return [PackMode.MIXED]


def _output_paths(out: Path, stem: str, modes: list[PackMode]) -> list[Path]:
    if out.suffix.lower() == ".mcpack":
        if len(modes) != 1:
            raise SystemExit("生成多个模式时 --out 必须是目录，不能是单个 .mcpack")
        if "_bedrock" not in out.stem:
            out = out.with_name(f"{out.stem}_bedrock{out.suffix}")
        return [out]
    return [out / f"{stem}_bedrock_{mode.value}.mcpack" for mode in modes]


def cmd_run(args: argparse.Namespace) -> int:
    from .batch import clear_output, run_once, run_watch
    from .runconfig import ConfigError, ensure_layout, load_config

    config_path = Path(args.config).expanduser()
    missing = not config_path.exists()
    try:
        ensure_layout(config_path)
        config = load_config(
            config_path,
            input_dir=args.input,
            output_dir=args.output,
            modes=args.mode,
            jobs=args.jobs,
            overwrite=True if args.force else None,
            watch=True if args.watch else (False if args.once else None),
            vibrant_visuals=True if args.vv else None,
            preset=args.preset,
        )
    except (ConfigError, OSError) as exc:
        LOGGER.error("配置错误：%s", exc)
        return 2

    if missing:
        LOGGER.info("已创建 %s、%s/、%s/", config_path, config.input_dir, config.output_dir)
        LOGGER.info("把 Java 材质包 zip 放进 %s/ 后重新运行即可。", config.input_dir)
    LOGGER.info("输入目录：%s", config.input_dir)
    LOGGER.info("输出目录：%s", config.output_dir)
    LOGGER.info(
        "预设：%s；模式：%s；并发：%d；监视：%s",
        config.preset,
        ", ".join(m.value for m in config.modes),
        config.jobs,
        "是" if config.watch else "否",
    )
    for warning in config.warnings:
        LOGGER.warning("配置提示：%s", warning)

    if args.init_only:
        LOGGER.info("已初始化，未执行转换。")
        return 0
    if args.clean:
        removed = clear_output(config)
        LOGGER.info("已清理 output/ 中 %d 个旧产物", removed)

    try:
        if config.watch:
            run_watch(config, force=args.force, progress=LOGGER.info)
            return 0
        result = run_once(config, force=args.force, progress=LOGGER.info)
    except KeyboardInterrupt:
        LOGGER.info("已中断")
        return 0
    return 0 if not result.failed else 1


def cmd_convert(args: argparse.Namespace) -> int:
    modes = _resolve_modes(args)
    out = Path(args.out)
    stem = _sanitize(Path(args.java_pack[0]).stem if args.java_pack else "pack")
    outputs = _output_paths(out, stem, modes)
    settings = _settings_from_args(args)
    base_pack = Path(args.base_pack) if args.base_pack else None

    failures = 0
    for mode, output in zip(modes, outputs):
        report = None
        if args.report:
            report_dir = Path(args.report)
            if report_dir.suffix.lower() == ".json":
                report = report_dir if len(modes) == 1 else report_dir.with_name(
                    f"{report_dir.stem}_{mode.value}{report_dir.suffix}"
                )
            else:
                report = report_dir / f"{output.stem}.report.json"
        elif args.all_modes or len(modes) > 1:
            report = output.with_name(f"{output.stem}.report.json")

        pack_name = args.name or f"{stem}_bedrock_{mode.value}"
        description = args.description or (
            f"{stem}: Java labPBR -> Bedrock {mode.value} "
            f"(normal/MER/heightmap texture sets)"
        )
        LOGGER.info("=" * 78)
        LOGGER.info("开始转换：mode=%s -> %s", mode.value, output)
        try:
            result = convert_pack(
                sources=args.java_pack,
                output=output,
                mode=mode,
                settings=settings,
                base_pack=base_pack,
                pack_name=pack_name,
                pack_description=description,
                jobs=args.jobs,
                fill_missing_colors=not args.no_fill_colors,
                pack_icon=args.pack_icon,
                vibrant_visuals=args.vv,
                report_path=report,
                progress=LOGGER.info if args.verbose else None,
            )
        except ConversionError as exc:
            LOGGER.error("转换失败：%s", exc)
            failures += 1
            continue
        except Exception as exc:  # 未预期错误：保留现场，便于排查
            LOGGER.error("转换异常：%s", exc)
            if args.verbose:
                import traceback

                traceback.print_exc()
            failures += 1
            continue

        if result.stats.unmapped:
            preview = ", ".join(sorted(result.stats.unmapped)[:8])
            LOGGER.info("未映射 %d 个：%s ...", len(result.stats.unmapped), preview)
        if args.verify:
            vr = validate_pack(output)
            LOGGER.info(vr.summary())
            for issue in vr.errors[:20]:
                LOGGER.error("  [%s] %s: %s", issue.code, issue.path, issue.message)
            if not vr.ok:
                failures += 1
    return 1 if failures else 0


def cmd_validate(args: argparse.Namespace) -> int:
    failed = 0
    for path in args.packs:
        report = validate_pack(path)
        print(report.summary())
        for issue in report.errors:
            print(f"  ERROR [{issue.code}] {issue.path}: {issue.message}")
        for issue in report.warnings[:50]:
            print(f"  WARN  [{issue.code}] {issue.path}: {issue.message}")
        if not report.ok:
            failed += 1
    return 1 if failed else 0


def cmd_map(args: argparse.Namespace) -> int:
    from .java_pack import BLOCK_ROOT, JavaPack, JavaPackStack
    from .name_map import NameMapper

    stack = JavaPackStack([JavaPack(p) for p in args.java_pack])
    try:
        groups = stack.texture_groups(BLOCK_ROOT)
    finally:
        stack.close()
    mapper = NameMapper()
    unmapped = []
    for name in sorted(groups):
        if mapper.resolve(name) is None:
            unmapped.append(name)
    total = len(groups)
    print(f"方块贴图组：{total}，已映射：{total - len(unmapped)}，未映射：{len(unmapped)}")
    for name in unmapped:
        print(f"  - {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="labpbr2bedrock",
        description="把 Java labPBR 材质转换为 Bedrock RTX PBR 材质包（.mcpack）",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert", help="转换并打包")
    convert.add_argument(
        "--java-pack",
        action="append",
        required=True,
        metavar="PATH",
        help="Java 材质包（zip 或目录）；可重复，后者覆盖前者",
    )
    convert.add_argument("--base-pack", metavar="PATH", help="可选：现有 Bedrock 包作为底板")
    convert.add_argument(
        "--mode",
        action="append",
        choices=[m.value for m in PackMode],
        help="打包模式，可重复；默认 mixed",
    )
    convert.add_argument("--all-modes", action="store_true", help="一次生成三种模式")
    convert.add_argument(
        "-o",
        "--out",
        required=True,
        metavar="PATH",
        help="输出目录，或单个 .mcpack 文件",
    )
    convert.add_argument("--name", help="包显示名")
    convert.add_argument("--description", help="包描述")
    convert.add_argument("--jobs", type=int, default=0, help="并行度，0 = 自动")
    convert.add_argument("--report", metavar="PATH", help="报告路径（.json 或目录）")
    convert.add_argument("--verify", action="store_true", help="打包后立即校验")
    convert.add_argument("--pack-icon", metavar="PATH", help="自定义 pack_icon.png")
    convert.add_argument(
        "--vv",
        action="store_true",
        help="输出 Vibrant Visuals 包（capabilities: [pbr]，min_engine 1.21.120）",
    )
    convert.add_argument(
        "--no-fill-colors",
        action="store_true",
        help="merge 模式下不为底板缺失的颜色贴图补图",
    )
    convert.add_argument("--flip-green", action="store_true", help="翻转法线绿通道")
    convert.add_argument(
        "--metal-threshold",
        type=int,
        default=230,
        help="labPBR 金属阈值（默认 230）",
    )
    convert.add_argument(
        "--roughness",
        choices=[m.value for m in RoughnessMode],
        default="linear",
        help="光滑度->粗糙度换算（默认 linear）",
    )
    convert.add_argument(
        "--height-depth",
        type=float,
        default=1.0,
        help="高度图深度比例（0-1，默认 1.0）",
    )
    convert.add_argument(
        "--height-min-span",
        type=int,
        default=8,
        help="判定“有真实高度”的 alpha 极差阈值（默认 8）",
    )
    convert.add_argument("--bake-ao", action="store_true", help="把 labPBR AO 烘焙进颜色")
    convert.add_argument(
        "--no-resize",
        action="store_true",
        help="图层尺寸与颜色不一致时跳过，而不是缩放对齐",
    )
    convert.add_argument(
        "--no-extra-heightmaps",
        action="store_true",
        help="Mixed 模式不附带未被 JSON 引用的高度图文件",
    )
    convert.add_argument("-v", "--verbose", action="store_true", help="输出进度")

    run = sub.add_parser(
        "run", help="文件夹批处理：把 Java 包放进 input/，自动生成到 output/"
    )
    run.add_argument("--config", default="config.json", help="配置文件（默认 config.json）")
    run.add_argument("--input", metavar="DIR", help="覆盖 input_dir")
    run.add_argument("--output", metavar="DIR", help="覆盖 output_dir")
    run.add_argument(
        "--mode",
        action="append",
        choices=[m.value for m in PackMode],
        help="覆盖生成模式，可重复；默认使用 config 中的 mixed",
    )
    run.add_argument("--jobs", type=int, help="覆盖并发度")
    run.add_argument(
        "--preset",
        help="使用 config.json 里的预设：mixed（默认）/ pbr / heightmap / split / all",
    )
    run.add_argument("--force", action="store_true", help="强制重建已存在的产物")
    run.add_argument("--watch", action="store_true", help="持续监视 input/")
    run.add_argument("--once", action="store_true", help="只跑一次（覆盖 config 的 watch）")
    run.add_argument("--vv", action="store_true", help="生成 Vibrant Visuals 包")
    run.add_argument("--init-only", action="store_true", help="只创建 config 与文件夹")
    run.add_argument("--clean", action="store_true", help="先删除 output/ 中的旧产物")
    run.add_argument("-v", "--verbose", action="store_true", help="输出进度")

    validate = sub.add_parser("validate", help="校验 .mcpack")
    validate.add_argument("packs", nargs="+", metavar="PACK")

    mapped = sub.add_parser("map", help="检查 Java -> Bedrock 命名映射覆盖率")
    mapped.add_argument(
        "--java-pack", action="append", required=True, metavar="PATH"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )
    if args.command == "convert":
        return cmd_convert(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "map":
        return cmd_map(args)
    parser.error("未知命令")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
