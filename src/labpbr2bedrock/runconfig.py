"""文件夹工作流配置（input / output / config.json）。

设计目标：
- 用户把 Java 材质包 zip 丢进 ``input/``，运行程序即可在 ``output/`` 得到
  ``<名字>_bedrock[_<模式>].mcpack``；
- ``input/`` 下的子文件夹会作为“一个材质包”整体转换（例如 BASE + Emiores 合并）；
- ``config.json`` 可直接写 ``targets`` 指定输入、输出与模式，绕过自动发现；
- 首次运行自动创建 config 与文件夹，不需要手动准备目录结构。
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConversionSettings, PackMode, RoughnessMode
from .errors import ConversionError

CONFIG_VERSION = 1
DEFAULT_CONFIG_NAME = "config.json"
DEFAULT_INPUT_DIR = "input"
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_SUFFIX = "_bedrock"

# 内置分包预设；config.json 里的 presets 会覆盖同名项
DEFAULT_PRESETS: dict[str, dict] = {
    "heightmap": {
        "modes": ["heightmap"],
        "output_format": "both",
        "name_suffix": "_bedrock",
        "mode_suffixes": {"heightmap": ""},
    },
    "pbr": {
        "modes": ["pbr"],
        "output_format": "both",
        "name_suffix": "_bedrock",
        "mode_suffixes": {"pbr": "_pbr"},
    },
    "split": {
        "modes": ["heightmap", "pbr"],
        "output_format": "both",
        "name_suffix": "_bedrock",
        "mode_suffixes": {"heightmap": "", "pbr": "_pbr"},
    },
}

INPUT_README = """把 Java 版材质包（.zip，或解压后的包目录）放在这个文件夹里。

- 单个 zip：生成一个基岩包。
- 子文件夹：文件夹内的所有 zip / 包目录按文件名顺序合并，生成一个基岩包。
- 想在子文件夹里指定顺序：新建 order.txt，每行一个文件名（先出现的先加载）。

运行 start.bat / start.sh，或 python run.py，结果会出现在 output/。
"""


class ConfigError(ConversionError):
    """config.json 无法解析或字段非法。"""

    code = "config_error"


@dataclass
class TargetSpec:
    """config.json 中显式指定的一个转换目标。"""

    name: str
    sources: list[Path]
    modes: list[PackMode] | None = None
    output: Path | None = None
    base_pack: Path | None = None


@dataclass
class RunConfig:
    path: Path
    input_dir: Path
    output_dir: Path
    modes: list[PackMode]
    jobs: int = 8
    overwrite: bool = False
    watch: bool = False
    watch_interval: float = 5.0
    verify: bool = True
    report: bool = True
    name_suffix: str = DEFAULT_SUFFIX
    output_format: str = "both"
    include_mode_in_name: bool = False
    vibrant_visuals: bool = False
    base_pack: Path | None = None
    group_by_prefix: bool = True
    preset: str = "heightmap"
    presets: dict[str, dict] = field(default_factory=dict)
    mode_suffixes: dict[str, str] = field(default_factory=dict)
    conversion: ConversionSettings = field(default_factory=ConversionSettings)
    targets: list[TargetSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.path.parent


# ---------------------------------------------------------------------- #
# 默认配置
# ---------------------------------------------------------------------- #
def default_config_dict() -> dict:
    data = {
        "_readme": [
            "把 Java 材质包 zip 放进 input/，运行 start.bat / start.sh / python run.py。",
            "input/ 的子文件夹会当作一个材质包整体合并。",
            "targets 非空时只处理 targets，不再自动扫描 input/。",
            "所有相对路径都相对于本文件所在目录。",
        ],
        "version": CONFIG_VERSION,
        "input_dir": DEFAULT_INPUT_DIR,
        "output_dir": DEFAULT_OUTPUT_DIR,
        "mode": "heightmap",
        "modes": [],
        "preset": "heightmap",
        "presets": DEFAULT_PRESETS,
        "jobs": 8,
        "overwrite": False,
        "watch": False,
        "watch_interval": 5.0,
        "verify": True,
        "report": True,
        "name_suffix": DEFAULT_SUFFIX,
        "output_format": "both",
        "include_mode_in_name": False,
        "vibrant_visuals": False,
        "base_pack": None,
        "group_by_prefix": True,
        "conversion": {
            "metal_threshold": 230,
            "roughness": "linear",
            "height_depth": 1.0,
            "height_min_span": 8,
            "flip_green": False,
            "bake_ao": False,
            "resize_mismatched": True,
            "mixed_include_heightmap_files": True,
            "mixed_json": "auto",
        },
        "targets": [],
    }
    data["presets"] = copy.deepcopy(DEFAULT_PRESETS)
    return data


def ensure_layout(config_path: str | Path) -> Path:
    """首次运行时创建 config.json、input/、output/ 与说明文件。"""
    path = Path(config_path).expanduser()
    root = path.parent
    root.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            json.dumps(default_config_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    data = _read_json(path)
    input_dir = _resolve(path, data.get("input_dir") or DEFAULT_INPUT_DIR)
    output_dir = _resolve(path, data.get("output_dir") or DEFAULT_OUTPUT_DIR)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    readme = input_dir / "README.txt"
    if not readme.exists():
        readme.write_text(INPUT_README, encoding="utf-8")
    return path


# ---------------------------------------------------------------------- #
# 读取与校验
# ---------------------------------------------------------------------- #
def load_config(
    config_path: str | Path,
    *,
    input_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    modes: list[str] | None = None,
    jobs: int | None = None,
    overwrite: bool | None = None,
    watch: bool | None = None,
    vibrant_visuals: bool | None = None,
    preset: str | None = None,
) -> RunConfig:
    path = Path(config_path).expanduser()
    if not path.exists():
        raise ConfigError(f"配置文件不存在：{path}", path=str(path))
    data = _read_json(path)
    warnings: list[str] = []

    version = data.get("version")
    if version is not None and int(version) > CONFIG_VERSION:
        warnings.append(
            f"config 版本 {version} 高于程序支持的 {CONFIG_VERSION}，未知字段会被忽略"
        )

    # 预设：CLI > config.preset > mixed
    presets = _parse_presets(data.get("presets"), path)
    selected_preset = str(preset or data.get("preset") or "heightmap").strip()
    if selected_preset not in presets:
        raise ConfigError(
            f"未知预设 {selected_preset!r}，可用：{', '.join(sorted(presets))}",
            path=str(path),
        )
    chosen = presets[selected_preset]

    # 模式：CLI > 预设 modes > config.modes > config.mode > mixed
    raw_modes = modes
    if not raw_modes:
        raw_modes = chosen.get("modes") or data.get("modes") or []
    if not raw_modes:
        raw_modes = [chosen.get("mode") or data.get("mode") or PackMode.HEIGHTMAP.value]
    try:
        parsed_modes = [PackMode.parse(str(m)) for m in raw_modes]
    except ValueError as exc:
        raise ConfigError(str(exc), path=str(path)) from exc

    conversion_raw = data.get("conversion") or {}
    if not isinstance(conversion_raw, dict):
        raise ConfigError("conversion 必须是对象", path=str(path))
    conversion = ConversionSettings(
        metal_threshold=_int(conversion_raw, "metal_threshold", 230),
        roughness_mode=_roughness(conversion_raw.get("roughness", "linear")),
        height_depth=_float(conversion_raw, "height_depth", 1.0),
        height_min_span=_int(conversion_raw, "height_min_span", 8),
        flip_green=bool(conversion_raw.get("flip_green", False)),
        bake_ao=bool(conversion_raw.get("bake_ao", False)),
        resize_mismatched=bool(conversion_raw.get("resize_mismatched", True)),
        mixed_include_heightmap_files=bool(
            conversion_raw.get("mixed_include_heightmap_files", True)
        ),
        mixed_json=str(conversion_raw.get("mixed_json", "auto")),
    )
    try:
        conversion.validate()
    except ValueError as exc:
        raise ConfigError(f"conversion 参数非法：{exc}", path=str(path)) from exc

    targets_raw = data.get("targets") or []
    if not isinstance(targets_raw, list):
        raise ConfigError("targets 必须是数组", path=str(path))
    targets: list[TargetSpec] = []
    for index, item in enumerate(targets_raw):
        targets.append(_parse_target(path, index, item))

    resolved_input = (
        _resolve(path, input_dir)
        if input_dir is not None
        else _resolve(path, data.get("input_dir") or DEFAULT_INPUT_DIR)
    )
    resolved_output = (
        _resolve(path, output_dir)
        if output_dir is not None
        else _resolve(path, data.get("output_dir") or DEFAULT_OUTPUT_DIR)
    )

    config = RunConfig(
        path=path,
        input_dir=resolved_input,
        output_dir=resolved_output,
        modes=parsed_modes,
        jobs=jobs if jobs is not None else _int(data, "jobs", 8),
        overwrite=overwrite
        if overwrite is not None
        else bool(data.get("overwrite", False)),
        watch=watch if watch is not None else bool(data.get("watch", False)),
        watch_interval=_float(data, "watch_interval", 5.0),
        verify=bool(data.get("verify", True)),
        report=bool(data.get("report", True)),
        name_suffix=str(
            chosen.get("name_suffix") or data.get("name_suffix") or DEFAULT_SUFFIX
        ),
        output_format=str(
            chosen.get("output_format") or data.get("output_format") or "both"
        ),
        include_mode_in_name=bool(
            chosen.get("include_mode_in_name", data.get("include_mode_in_name", False))
        ),
        vibrant_visuals=vibrant_visuals
        if vibrant_visuals is not None
        else bool(data.get("vibrant_visuals", False)),
        base_pack=_resolve_optional(path, data.get("base_pack")),
        group_by_prefix=bool(data.get("group_by_prefix", True)),
        preset=selected_preset,
        presets=presets,
        mode_suffixes={
            str(k): str(v)
            for k, v in (chosen.get("mode_suffixes") or {}).items()
        },
        conversion=conversion,
        targets=targets,
        warnings=warnings,
    )
    if config.jobs < 0:
        raise ConfigError("jobs 不能为负数", path=str(path))
    if config.watch_interval <= 0:
        raise ConfigError("watch_interval 必须大于 0", path=str(path))
    if not config.name_suffix:
        raise ConfigError("name_suffix 不能为空", path=str(path))
    if config.output_format not in {"mcpack", "folder", "both"}:
        raise ConfigError(
            "output_format 必须是 mcpack / folder / both", path=str(path)
        )
    return config


def _parse_presets(raw: object, path: Path) -> dict[str, dict]:
    presets = copy.deepcopy(DEFAULT_PRESETS)
    if raw is None:
        return presets
    if not isinstance(raw, dict):
        raise ConfigError("presets 必须是对象", path=str(path))
    for name, value in raw.items():
        if not isinstance(value, dict):
            raise ConfigError(f"presets.{name} 必须是对象", path=str(path))
        merged = {**presets.get(str(name), {}), **value}
        if "modes" in merged:
            modes = merged["modes"]
            if isinstance(modes, str):
                modes = [modes]
            if not isinstance(modes, list) or not modes:
                raise ConfigError(f"presets.{name}.modes 不能为空", path=str(path))
            try:
                merged["modes"] = [PackMode.parse(str(m)).value for m in modes]
            except ValueError as exc:
                raise ConfigError(f"presets.{name}.modes 非法：{exc}", path=str(path)) from exc
        suffixes = merged.get("mode_suffixes")
        if suffixes is not None:
            if not isinstance(suffixes, dict):
                raise ConfigError(f"presets.{name}.mode_suffixes 必须是对象", path=str(path))
            merged["mode_suffixes"] = {str(k): str(v) for k, v in suffixes.items()}
        fmt = merged.get("output_format")
        if fmt is not None and fmt not in {"mcpack", "folder", "both"}:
            raise ConfigError(
                f"presets.{name}.output_format 必须是 mcpack / folder / both",
                path=str(path),
            )
        presets[str(name)] = merged
    return presets


def _read_json(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"无法读取配置：{exc}", path=str(path)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"config.json 解析失败（第 {exc.lineno} 行第 {exc.colno} 列）：{exc.msg}",
            path=str(path),
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError("config.json 顶层必须是对象", path=str(path))
    return data


def _resolve(config_path: Path, value: str | Path) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    return (config_path.parent / path).resolve()


def _resolve_optional(config_path: Path, value: object) -> Path | None:
    if value in (None, ""):
        return None
    return _resolve(config_path, value)  # type: ignore[arg-type]


def _parse_target(config_path: Path, index: int, item: object) -> TargetSpec:
    if not isinstance(item, dict):
        raise ConfigError(f"targets[{index}] 必须是对象", path=str(config_path))
    name = str(item.get("name") or f"target_{index + 1}").strip()
    raw_sources = item.get("sources") or []
    if isinstance(raw_sources, str):
        raw_sources = [raw_sources]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ConfigError(
            f"targets[{index}].sources 至少要有一个输入；"
            "文件夹会作为一个包整体处理",
            path=str(config_path),
        )
    sources = [_resolve(config_path, s) for s in raw_sources]
    raw_modes = item.get("modes")
    modes = None
    if raw_modes:
        if isinstance(raw_modes, str):
            raw_modes = [raw_modes]
        try:
            modes = [PackMode.parse(str(m)) for m in raw_modes]
        except ValueError as exc:
            raise ConfigError(f"targets[{index}] 模式非法：{exc}", path=str(config_path)) from exc
    output = _resolve_optional(config_path, item.get("output"))
    base_pack = _resolve_optional(config_path, item.get("base_pack"))
    return TargetSpec(
        name=name,
        sources=sources,
        modes=modes,
        output=output,
        base_pack=base_pack,
    )


def _int(data: dict, key: str, default: int) -> int:
    value = data.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} 必须是整数") from exc


def _float(data: dict, key: str, default: float) -> float:
    value = data.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} 必须是数字") from exc


def _roughness(value: object) -> RoughnessMode:
    try:
        return RoughnessMode.parse(str(value))
    except ValueError as exc:
        raise ConfigError(f"roughness 非法：{exc}") from exc


# ---------------------------------------------------------------------- #
# 任务发现
# ---------------------------------------------------------------------- #
@dataclass
class Task:
    name: str
    sources: list[Path]
    modes: list[PackMode]
    base_pack: Path | None = None
    explicit_output: Path | None = None


def discover_tasks(config: RunConfig) -> list[Task]:
    """把 config / input 目录解析成待转换任务列表（顺序稳定）。"""
    if config.targets:
        tasks: list[Task] = []
        for target in config.targets:
            missing = [str(p) for p in target.sources if not p.exists()]
            if missing:
                raise ConfigError(
                    f"target {target.name!r} 的输入不存在：{', '.join(missing)}",
                    path=str(config.path),
                )
            tasks.append(
                Task(
                    name=target.name,
                    sources=target.sources,
                    modes=target.modes or config.modes,
                    base_pack=target.base_pack or config.base_pack,
                    explicit_output=target.output,
                )
            )
        return tasks

    config.input_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[Task] = []
    root_zips: list[Path] = []

    for entry in sorted(config.input_dir.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith(".") or entry.name.lower() == "readme.txt":
            continue
        if entry.is_file() and entry.suffix.lower() == ".zip":
            root_zips.append(entry)
            continue
        if entry.is_dir():
            if (entry / "pack.mcmeta").exists():
                # 解压后的单个材质包
                tasks.append(
                    Task(
                        name=entry.name,
                        sources=[entry],
                        modes=config.modes,
                        base_pack=config.base_pack,
                    )
                )
                continue
            sources = _group_sources(entry)
            if sources:
                tasks.append(
                    Task(
                        name=entry.name,
                        sources=sources,
                        modes=config.modes,
                        base_pack=config.base_pack,
                    )
                )

    if config.group_by_prefix and len(root_zips) > 1:
        # 同一前缀的 zip 视为同一个材质包的多个模块，例如：
        # rotrBLOCKS BASE/DESIGN/DUNGEONS/FLORA/Emiores/CTM
        order = _read_order(config.input_dir)
        groups: dict[str, list[Path]] = {}
        for path in root_zips:
            prefix = _name_prefix(path.stem)
            key = prefix.lower() if prefix else f"__{path.stem.lower()}"
            groups.setdefault(key, []).append(path)
        for key in sorted(groups):
            paths = groups[key]
            if len(paths) == 1:
                path = paths[0]
                tasks.append(
                    Task(
                        name=path.stem,
                        sources=[path],
                        modes=config.modes,
                        base_pack=config.base_pack,
                    )
                )
            else:
                ordered = _apply_order(paths, order)
                # 包名沿用合并后第一个输入的名字，例如 rotrBLOCKS BASE...
                tasks.append(
                    Task(
                        name=ordered[0].stem,
                        sources=ordered,
                        modes=config.modes,
                        base_pack=config.base_pack,
                    )
                )
    else:
        for path in root_zips:
            tasks.append(
                Task(
                    name=path.stem,
                    sources=[path],
                    modes=config.modes,
                    base_pack=config.base_pack,
                )
            )

    tasks.sort(key=lambda task: task.name.lower())
    return tasks


def _name_prefix(stem: str) -> str:
    """取文件名第一个空格/下划线/横线前的部分作为组前缀。

    例：``rotrBLOCKS BASE V73`` -> ``rotrBLOCKS``；
    前缀太短（<3 字符）时返回空串，避免误合并。
    """
    prefix = stem
    for sep in (" ", "_", "-"):
        prefix = prefix.split(sep)[0]
    prefix = prefix.strip()
    return prefix if len(prefix) >= 3 else ""


def _read_order(folder: Path) -> list[str]:
    order_file = folder / "order.txt"
    if not order_file.exists():
        return []
    try:
        return [
            line.strip()
            for line in order_file.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except OSError:
        return []


def _apply_order(paths: list[Path], order: list[str]) -> list[Path]:
    if not order:
        return sorted(paths, key=lambda p: p.name.lower())
    by_name = {p.name: p for p in paths}
    ordered: list[Path] = []
    for name in order:
        if name in by_name:
            ordered.append(by_name.pop(name))
    ordered.extend(sorted(by_name.values(), key=lambda p: p.name.lower()))
    return ordered


def _group_sources(folder: Path) -> list[Path]:
    """一个子文件夹 = 一个材质包：按 order.txt 或文件名合并 zip / 包目录。"""
    order: list[str] = []
    order_file = folder / "order.txt"
    if order_file.exists():
        try:
            order = [
                line.strip()
                for line in order_file.read_text(encoding="utf-8-sig").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        except OSError:
            order = []

    entries = [
        p
        for p in folder.iterdir()
        if not p.name.startswith(".")
        and (p.is_dir() or p.suffix.lower() == ".zip")
        and not (p.is_dir() and not (p / "pack.mcmeta").exists())
    ]
    by_name = {p.name: p for p in entries}
    ordered: list[Path] = []
    for name in order:
        if name in by_name:
            ordered.append(by_name.pop(name))
    ordered.extend(sorted(by_name.values(), key=lambda p: p.name.lower()))
    return ordered


def output_name(task: Task, mode: PackMode, config: RunConfig) -> str:
    suffix = config.name_suffix
    base = sanitize_name(task.name)
    if config.include_mode_in_name:
        mode_suffix = f"_{mode.value}"
    elif mode.value in config.mode_suffixes:
        mode_suffix = config.mode_suffixes[mode.value]
    elif len(task.modes) > 1:
        mode_suffix = f"_{mode.value}"
    else:
        mode_suffix = ""
    return f"{base}{suffix}{mode_suffix}.mcpack"


def sanitize_name(name: str) -> str:
    name = name.strip().replace(" ", "_")
    name = re.sub(r"[^0-9A-Za-z_\-.]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("._")
    return name or "pack"
