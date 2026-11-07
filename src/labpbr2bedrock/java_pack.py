"""Java 材质包读取。

支持 ``.zip`` 与解压后的目录；多个包可以叠加（后者覆盖前者），
用于把 rotrBLOCKS 的 BASE 与 DESIGN / DUNGEONS / FLORA / Emiores 等
附加包合成一个逻辑材质包。

只做“读取与索引”，不做任何图像转换。
"""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .errors import PackFormatError, SourceError

TEXTURE_ROOT = "assets/minecraft/textures"
BLOCK_ROOT = f"{TEXTURE_ROOT}/block"


@dataclass(frozen=True)
class TextureGroup:
    """同一个逻辑贴图的 base / normal / specular 组合。"""

    name: str
    """相对 ``textures/block`` 的名字（含子目录，不含扩展名）。"""

    base: str
    """base 贴图的完整 zip/目录内路径。"""

    normal: str | None = None
    specular: str | None = None
    animated: bool = False
    """是否存在 ``.png.mcmeta`` 动画定义。"""

    mcmeta: str | None = None


class JavaPack:
    """单个 Java 材质包（zip 或目录）。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise SourceError(f"输入路径不存在：{self.path}")
        self._zip: zipfile.ZipFile | None = None
        if self.path.is_dir():
            self._files: dict[str, Path] = {}
            for root, _dirs, files in os.walk(self.path):
                for filename in files:
                    abs_path = Path(root) / filename
                    rel = abs_path.relative_to(self.path).as_posix()
                    self._files[rel] = abs_path
        else:
            try:
                self._zip = zipfile.ZipFile(self.path)
            except zipfile.BadZipFile as exc:
                raise SourceError(f"不是有效的 zip：{self.path}") from exc
            self._files = {}

    # ------------------------------------------------------------------ #
    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"JavaPack({self.path.name})"

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def __enter__(self) -> "JavaPack":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def names(self) -> list[str]:
        if self._zip is not None:
            return [n for n in self._zip.namelist() if not n.endswith("/")]
        return list(self._files)

    def has(self, name: str) -> bool:
        if self._zip is not None:
            try:
                self._zip.getinfo(name)
                return True
            except KeyError:
                return False
        return name in self._files

    def read(self, name: str) -> bytes:
        if self._zip is not None:
            try:
                return self._zip.read(name)
            except KeyError as exc:
                raise SourceError(f"包内不存在文件：{name}", path=name) from exc
        try:
            return self._files[name].read_bytes()
        except OSError as exc:
            raise SourceError(f"无法读取文件：{name}", path=name) from exc

    def read_optional(self, name: str) -> bytes | None:
        try:
            return self.read(name)
        except SourceError:
            return None

    def read_json(self, name: str) -> dict:
        raw = self.read_optional(name)
        if raw is None:
            return {}
        try:
            return json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackFormatError(f"JSON 解析失败：{name}", path=name) from exc

    def description(self) -> str:
        """读取 pack.mcmeta 描述（用于产物命名/说明）。"""
        meta = self.read_json("pack.mcmeta")
        pack = meta.get("pack") or {}
        return str(pack.get("description") or "")


class JavaPackStack:
    """多个 Java 包的叠加视图：后加入的包优先。"""

    def __init__(self, packs: list[JavaPack]) -> None:
        if not packs:
            raise SourceError("至少需要一个 Java 材质包")
        self.packs = packs

    def close(self) -> None:
        for pack in self.packs:
            pack.close()

    def __enter__(self) -> "JavaPackStack":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def read(self, name: str) -> bytes:
        """按优先级读取；高优先级包覆盖低优先级。"""
        for pack in reversed(self.packs):
            data = pack.read_optional(name)
            if data is not None:
                return data
        raise SourceError(f"所有输入包中都不存在：{name}", path=name)

    def has(self, name: str) -> bool:
        return any(pack.has(name) for pack in self.packs)

    def read_optional(self, name: str) -> bytes | None:
        """按优先级读取；不存在时返回 ``None`` 而不是抛错。"""
        for pack in reversed(self.packs):
            data = pack.read_optional(name)
            if data is not None:
                return data
        return None

    def all_names(self) -> set[str]:
        names: set[str] = set()
        for pack in self.packs:
            names.update(pack.names())
        return names

    def texture_groups(self, root: str = BLOCK_ROOT) -> dict[str, TextureGroup]:
        """扫描 ``root`` 下的所有 base 贴图并配对 ``_n`` / ``_s``。

        配对规则：

        * ``foo.png``          -> base
        * ``foo_n.png``        -> normal（labPBR ``_n``）
        * ``foo_s.png``        -> specular（labPBR ``_s``）
        * ``foo.png.mcmeta``   -> 动画元数据

        子目录会被保留在 ``name`` 中（例如 ``deepslate/deepslate``），
        但 Java 版通常把方块贴图平铺在 ``block/`` 下。
        """
        prefix = root.rstrip("/") + "/"
        names = self.all_names()
        groups: dict[str, TextureGroup] = {}

        suffix_map: dict[str, dict[str, str]] = {}
        for full in names:
            if not full.startswith(prefix) or not full.endswith(".png"):
                continue
            rel = full[len(prefix) : -len(".png")]
            stem = rel
            for suffix, key in (("_n", "normal"), ("_s", "specular")):
                if rel.endswith(suffix):
                    stem = rel[: -len(suffix)]
                    suffix_map.setdefault(stem, {})[key] = full
                    break
            else:
                suffix_map.setdefault(stem, {})["base"] = full

        for stem, parts in sorted(suffix_map.items()):
            base = parts.get("base")
            if base is None:
                # 只有 _n/_s 而没有颜色贴图：无法形成 texture_set（color 必填）
                continue
            mcmeta = f"{base}.mcmeta"
            animated = False
            if mcmeta in names:
                try:
                    meta = json.loads(self.read(mcmeta).decode("utf-8-sig"))
                    animated = bool(meta.get("animation"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    animated = True  # 保守：坏掉的 mcmeta 当作动画跳过
            groups[stem] = TextureGroup(
                name=stem,
                base=base,
                normal=parts.get("normal"),
                specular=parts.get("specular"),
                animated=animated,
                mcmeta=mcmeta if mcmeta in names else None,
            )
        return groups

    # ------------------------------------------------------------------ #
    def find_icon(self) -> bytes | None:
        for name in ("pack.png",):
            data = self.read_optional(name)
            if data:
                return data
        return None

    def find_license(self) -> str | None:
        for candidate in ("LICENSE", "LICENSE.txt", "license.txt", "License"):
            data = self.read_optional(candidate)
            if data:
                try:
                    return data.decode("utf-8", errors="replace")
                except Exception:  # pragma: no cover
                    return None
        return None
