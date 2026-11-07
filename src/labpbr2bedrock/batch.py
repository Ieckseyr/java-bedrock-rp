"""文件夹批处理：input/ -> output/。

- 一次处理任意数量的输入（没有上限），单个任务失败不会中断其余任务；
- 已存在且比输入新的产物默认跳过，``--force`` / ``overwrite`` 可强制重建；
- ``watch`` 模式下持续轮询 input/，新放入的 zip 会自动转换。
"""

from __future__ import annotations

import logging
import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import PackMode
from .pipeline import convert_pack
from .runconfig import RunConfig, Task, discover_tasks, output_name
from .validate import validate_pack

logger = logging.getLogger("labpbr2bedrock")


@dataclass
class BatchItem:
    task: str
    mode: PackMode
    output: Path
    status: str  # built | skipped | failed
    folder: Path | None = None
    message: str = ""
    size_bytes: int = 0
    duration_s: float = 0.0


@dataclass
class BatchResult:
    items: list[BatchItem] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def built(self) -> list[BatchItem]:
        return [i for i in self.items if i.status == "built"]

    @property
    def skipped(self) -> list[BatchItem]:
        return [i for i in self.items if i.status == "skipped"]

    @property
    def failed(self) -> list[BatchItem]:
        return [i for i in self.items if i.status == "failed"]

    def summary(self) -> str:
        return (
            f"完成 {len(self.built)}，跳过 {len(self.skipped)}，"
            f"失败 {len(self.failed)}，用时 {self.duration_s:.1f}s"
        )


def run_once(
    config: RunConfig,
    *,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> BatchResult:
    """扫描一次输入并转换所有到期任务。"""
    started = time.perf_counter()
    result = BatchResult()
    try:
        tasks = discover_tasks(config)
    except Exception as exc:
        logger.error("扫描输入失败：%s", exc)
        result.items.append(
            BatchItem(task="<discover>", mode=config.modes[0], output=config.output_dir, status="failed", message=str(exc))
        )
        result.duration_s = time.perf_counter() - started
        return result

    if not tasks:
        logger.info(
            "input/ 里还没有可转换的材质包（支持 .zip，或含多个 zip 的子文件夹）"
        )
        result.duration_s = time.perf_counter() - started
        return result

    used_outputs: set[Path] = set()
    for task in tasks:
        missing = [str(p) for p in task.sources if not p.exists()]
        if missing:
            logger.error("输入不存在：%s（%s）", task.name, ", ".join(missing))
            result.items.append(
                BatchItem(
                    task=task.name,
                    mode=task.modes[0],
                    output=config.output_dir,
                    status="failed",
                    message="输入不存在：" + ", ".join(missing),
                )
            )
            continue
        for mode in task.modes:
            output = _resolve_output(task, mode, config, used_outputs)
            folder = output.with_suffix("") if config.output_format in {"folder", "both"} else None
            artifact = folder if (folder is not None and config.output_format == "folder") else output
            try:
                if not force and not config.overwrite and not _needs_build(artifact, task.sources):
                    logger.info("跳过已是最新：%s", output.name)
                    result.items.append(
                        BatchItem(task=task.name, mode=mode, output=output, status="skipped")
                    )
                    continue

                logger.info("转换 %s -> %s", task.name, output)
                t0 = time.perf_counter()
                conversion = convert_pack(
                    sources=task.sources,
                    output=output,
                    mode=mode,
                    settings=config.conversion,
                    base_pack=task.base_pack,
                    pack_name=output.stem,
                    pack_description=f"{task.name}: Java labPBR -> Bedrock {mode.value}",
                    jobs=config.jobs,
                    vibrant_visuals=config.vibrant_visuals,
                    report_path=output.with_name(output.stem + ".report.json")
                    if config.report
                    else None,
                    progress=progress,
                )
                item = BatchItem(
                    task=task.name,
                    mode=mode,
                    output=output,
                    folder=folder,
                    status="built",
                    size_bytes=conversion.size_bytes,
                    duration_s=time.perf_counter() - t0,
                )
                if config.verify:
                    report = validate_pack(output)
                    if not report.ok:
                        item.status = "failed"
                        item.message = "产物校验失败：" + "; ".join(
                            f"{e.code} {e.path}" for e in report.errors[:5]
                        )
                        logger.error(item.message)
                if folder is not None and item.status != "failed":
                    try:
                        _write_folder(output, folder)
                        if config.output_format == "folder":
                            output.unlink(missing_ok=True)
                    except Exception as exc:
                        item.status = "failed"
                        item.message = f"解包到文件夹失败：{exc}"
                        logger.error(item.message)
                result.items.append(item)
            except Exception as exc:  # 单任务失败不中断批处理
                logger.error("转换失败 %s：%s", task.name, exc)
                result.items.append(
                    BatchItem(
                        task=task.name,
                        mode=mode,
                        output=output,
                        status="failed",
                        message=str(exc),
                    )
                )
            used_outputs.add(output)
            if progress is not None:
                progress(
                    f"{task.name} [{mode.value}] -> {output.name} "
                    f"({result.items[-1].status})"
                )
    result.duration_s = time.perf_counter() - started
    logger.info("批处理：%s", result.summary())
    return result


def run_watch(
    config: RunConfig,
    *,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> None:
    """持续监视 input/；Ctrl+C 退出。"""
    logger.info(
        "监视 %s（每 %.1f 秒扫描一次，Ctrl+C 退出）", config.input_dir, config.watch_interval
    )
    first = True
    try:
        while True:
            run_once(config, force=force and first, progress=progress)
            first = False
            time.sleep(config.watch_interval)
    except KeyboardInterrupt:
        logger.info("已停止监视")


# ---------------------------------------------------------------------- #
def _resolve_output(
    task: Task,
    mode: PackMode,
    config: RunConfig,
    used: set[Path],
) -> Path:
    if task.explicit_output is not None:
        explicit = task.explicit_output
        if explicit.suffix.lower() != ".mcpack":
            # 显式给的是目录
            output = explicit / output_name(task, mode, config)
        elif len(task.modes) > 1:
            output = explicit.with_name(f"{explicit.stem}_{mode.value}{explicit.suffix}")
        else:
            output = explicit
    else:
        output = config.output_dir / output_name(task, mode, config)
    output = _unique_path(output, used)
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _unique_path(path: Path, used: set[Path]) -> Path:
    """只解决“不同任务撞到同一个输出名”的情况；同名任务自身允许覆盖。"""
    if path not in used:
        return path
    stem, suffix = path.stem, path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if candidate not in used:
            return candidate
        index += 1


def _write_folder(mcpack: Path, folder: Path) -> None:
    """把 .mcpack 解包成资源包文件夹（文件夹名即包名）。"""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(mcpack) as archive:
        archive.extractall(folder)
    # 让文件夹 mtime 指向当前时间，便于增量跳过
    try:
        os.utime(folder, None)
    except OSError:
        pass


def _needs_build(output: Path, sources: list[Path]) -> bool:
    if not output.exists():
        return True
    try:
        out_mtime = output.stat().st_mtime
    except OSError:
        return True
    return any(_newest_mtime(source) > out_mtime for source in sources)


def _newest_mtime(path: Path) -> float:
    if not path.exists():
        return 0.0
    if path.is_file():
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0
    newest = path.stat().st_mtime
    for child in path.rglob("*"):
        if child.is_file():
            try:
                newest = max(newest, child.stat().st_mtime)
            except OSError:
                continue
    return newest


def clear_output(config: RunConfig) -> int:
    """删除 output/ 下的 .mcpack 与报告，返回删除的文件数。"""
    if not config.output_dir.exists():
        return 0
    removed = 0
    for pattern in ("*.mcpack", "*.report.json", "*.report.md"):
        for path in config.output_dir.glob(pattern):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    # output_format=folder 时没有 .mcpack，只剩资源包文件夹
    for path in config.output_dir.iterdir():
        if path.is_dir() and path.name.endswith(config.name_suffix) and (path / "manifest.json").exists():
            try:
                shutil.rmtree(path)
                removed += 1
            except OSError:
                continue
    return removed
