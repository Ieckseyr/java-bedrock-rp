"""Java 贴图名 -> Bedrock 贴图名映射。

Java 与 Bedrock 的方块贴图命名来自同一套历史，但两条线在 1.13 之后各自
演化：

* Java 使用了“压平（flattening）”后的现代名，例如 ``oak_planks``、
  ``light_gray_wool``、``stone_bricks``；
* Bedrock 仍保留大量 1.12 时代名，例如 ``planks_oak``、
  ``wool_colored_silver``、``stonebrick``，新方块（樱花、红树林、树脂等）
  则与现代名一致。

本模块用“规则生成候选 + 词表校验”的方式做映射：

1. 显式别名表（处理不规则名称）；
2. 规则族（颜色、木材、石材、植物、红石机械……）；
3. 原样命中（现代名一致的情况）；
4. 候选必须出现在 Bedrock 词表中才算成功，避免写出一堆游戏不认识的贴图名。

词表来自：
* Mojang/bedrock-samples（1.21.130.3）的 ``textures/blocks`` 颜色贴图名；
* 用户提供的 LEGENDARYB 基岩包中 ``texture_set`` 的 ``color`` 名
  （覆盖 1.16–1.21 的旧命名，优先命中）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).with_name("data")


@dataclass(frozen=True)
class MappingResult:
    """一次名称映射的结果。"""

    source: str
    target: str
    rule: str


COLORS = (
    "white",
    "orange",
    "magenta",
    "light_blue",
    "yellow",
    "lime",
    "pink",
    "gray",
    "light_gray",
    "cyan",
    "purple",
    "blue",
    "brown",
    "green",
    "red",
    "black",
)

# Bedrock 把 light_gray 称作 silver（羊毛、混凝土、玻璃等族）
COLOR_BEDROCK = {c: c for c in COLORS}
COLOR_BEDROCK["light_gray"] = "silver"

# Java 木材前缀 -> Bedrock 旧名木材词干
WOOD_BEDROCK = {
    "oak": "oak",
    "spruce": "spruce",
    "birch": "birch",
    "jungle": "jungle",
    "acacia": "acacia",
    "dark_oak": "big_oak",
    "mangrove": "mangrove",
    "cherry": "cherry",
    "bamboo": "bamboo",
    "crimson": "crimson",
    "warped": "warped",
    "pale_oak": "pale_oak",
}

# 使用 huge_fungus/ 子目录的木材（Bedrock 官方资源包结构）
NETHER_WOODS = {"crimson", "warped"}

# 5 种珊瑚的 Bedrock 颜色名（Java 按形态命名，Bedrock 按颜色命名）
CORAL_COLORS = {
    "brain": "pink",
    "bubble": "purple",
    "fire": "red",
    "horn": "yellow",
    "tube": "blue",
}


def _load_vocabulary() -> tuple[set[str], set[str], set[str]]:
    raw = json.loads((_DATA / "bedrock_textures.json").read_text(encoding="utf-8"))
    modern = set(raw["modern_paths"])
    legacy = set(raw["legacy_paths"])
    return modern, legacy, modern | legacy


def _load_aliases() -> dict[str, str]:
    path = _DATA / "name_map.json"
    if not path.exists():  # pragma: no cover - 数据文件必须随包分发
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return dict(raw.get("aliases", {}))


@lru_cache(maxsize=1)
def vocabulary() -> tuple[set[str], set[str], set[str]]:
    return _load_vocabulary()


@lru_cache(maxsize=1)
def tga_only_paths() -> frozenset[str]:
    """新版 Bedrock 原版只以 ``.tga`` 提供的贴图（相对 textures/blocks）。"""
    raw = json.loads((_DATA / "bedrock_textures.json").read_text(encoding="utf-8"))
    return frozenset(raw.get("modern_tga_only", ()))


class NameMapper:
    """把 Java 贴图相对名（不含扩展名）映射为 Bedrock 相对名。

    ``preferred`` 用于 merge 模式：给出底板包实际使用的贴图名集合，
    解析时优先命中它们，避免把 PBR 写到名字相似但底板并不存在的路径上。
    """

    def __init__(
        self,
        aliases: dict[str, str] | None = None,
        preferred: set[str] | None = None,
    ) -> None:
        self.modern, self.legacy, self.all = vocabulary()
        self._aliases = dict(_load_aliases())
        if aliases:
            self._aliases.update(aliases)
        self._preferred = set(preferred or ())
        self._stem_index: dict[str, list[str]] = {}
        for path in self.all:
            stem = path.rsplit("/", 1)[-1]
            self._stem_index.setdefault(stem, []).append(path)
        # 现代（1.21.130）命名优先于旧命名：当前版本游戏只认前者
        self._priority = {p: (2 if p in self.modern else 1) for p in self.all}

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def resolve(self, java_name: str) -> MappingResult | None:
        """解析单个 Java 贴图名；失败返回 ``None``。"""
        java_name = java_name.strip().lower()
        if not java_name:
            return None

        alias = self._aliases.get(java_name)
        if alias:
            if alias in self._preferred or alias in self.all:
                return MappingResult(java_name, alias, "alias")

        candidates = self._candidates(java_name)
        candidates.append((java_name, "exact"))

        found: list[tuple[int, int, int, int, str, str]] = []
        for index, (target, rule) in enumerate(candidates):
            if target not in self.all:
                continue
            found.append(
                (
                    1 if target in self._preferred else 0,
                    self._priority.get(target, 0),
                    1 if "/" in target else 0,
                    -index,
                    target,
                    rule,
                )
            )
        if not found:
            return None
        # 底板优先 -> 现代名优先 -> 顶层目录优先 -> 规则顺序
        found.sort(reverse=True)
        _, _, _, _, target, rule = found[0]
        return MappingResult(java_name, target, rule)

    # ------------------------------------------------------------------ #
    # 规则族
    # ------------------------------------------------------------------ #
    def _candidates(self, name: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []

        def add(target: str, rule: str) -> None:
            out.append((target, rule))

        # --- 颜色族 ------------------------------------------------------ #
        for color in COLORS:
            cb = COLOR_BEDROCK[color]
            prefix = f"{color}_"
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix) :]
            if rest == "wool":
                add(f"wool_colored_{cb}", "color/wool")
            elif rest == "concrete":
                add(f"concrete_{cb}", "color/concrete")
            elif rest == "concrete_powder":
                add(f"concrete_powder_{cb}", "color/concrete_powder")
            elif rest == "terracotta":
                add(f"hardened_clay_stained_{cb}", "color/terracotta")
            elif rest == "glazed_terracotta":
                add(f"glazed_terracotta_{cb}", "color/glazed_terracotta")
            elif rest == "stained_glass":
                add(f"glass_{cb}", "color/stained_glass")
            elif rest == "stained_glass_pane_top":
                add(f"glass_pane_top_{cb}", "color/stained_glass_pane_top")
            # 地毯在 Bedrock 复用羊毛贴图
            elif rest == "carpet":
                add(f"wool_colored_{cb}", "color/carpet")
        if name == "terracotta":
            add("hardened_clay", "color/terracotta")

        # --- 木材族 ------------------------------------------------------ #
        # 去皮原木以 stripped_ 开头，先单独处理，避免被 "stripped_xxx" 前缀干扰
        if name.startswith("stripped_"):
            rest = name[len("stripped_") :]
            for wood, bw in WOOD_BEDROCK.items():
                if not rest.startswith(f"{wood}_"):
                    continue
                tail = rest[len(wood) + 1 :]
                folder = "huge_fungus/" if wood in NETHER_WOODS else ""
                if tail == "log":
                    add(f"stripped_{bw}_log", "wood/stripped_log")
                    add(f"{folder}stripped_{wood}_stem_side", "wood/stripped_stem")
                    add(f"stripped_{wood}_log_side", "wood/stripped_log_side")
                elif tail == "log_top":
                    add(f"stripped_{bw}_log_top", "wood/stripped_log_top")
                    add(f"{folder}stripped_{wood}_stem_top", "wood/stripped_stem_top")
                elif tail == "stem":
                    add(f"{folder}stripped_{wood}_stem_side", "wood/stripped_stem")
                elif tail == "stem_top":
                    add(f"{folder}stripped_{wood}_stem_top", "wood/stripped_stem_top")

        for wood, bw in WOOD_BEDROCK.items():
            if name.startswith("stripped_"):
                continue
            prefix = f"{wood}_"
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix) :]
            folder = "huge_fungus/" if wood in NETHER_WOODS else ""
            if rest == "planks":
                add(f"{folder}{wood}_planks", "wood/planks")
                if wood not in NETHER_WOODS:
                    add(f"planks_{bw}", "wood/planks-legacy")
            elif rest == "log":
                add(f"log_{bw}", "wood/log")
                add(f"{folder}{wood}_log_side", "wood/log-side")
            elif rest == "log_top":
                add(f"log_{bw}_top", "wood/log_top")
                add(f"{folder}{wood}_log_top", "wood/log-top")
            elif rest == "stem":  # crimson_stem -> huge_fungus/crimson_log_side
                add(f"huge_fungus/{wood}_log_side", "wood/stem")
                add(f"huge_fungus/{wood}_stem_side", "wood/stem_side")
            elif rest == "stem_top":
                add(f"huge_fungus/{wood}_log_top", "wood/stem_top")
                add(f"huge_fungus/{wood}_stem_top", "wood/stem_top_alt")
            elif rest in {"door_bottom", "door_top"}:
                if wood in NETHER_WOODS:
                    side = "lower" if rest.endswith("bottom") else "top"
                else:
                    side = "lower" if rest.endswith("bottom") else "upper"
                if wood == "oak":
                    add(f"door_wood_{side}", "wood/door_oak")
                elif wood == "dark_oak":
                    add(f"door_dark_oak_{side}", "wood/door_dark_oak")
                else:
                    add(f"door_{bw}_{side}", "wood/door")
                    add(f"{folder}{wood}_door_{side}", "wood/door-modern")
                    add(f"{wood}_door_{side}", "wood/door-root")
            elif rest == "trapdoor":
                add(f"{wood}_trapdoor", "wood/trapdoor")
                add(f"{folder}{wood}_trapdoor", "wood/trapdoor-modern")
            elif rest == "sapling":
                add(f"sapling_{bw}", "wood/sapling")
                if wood == "dark_oak":
                    add("sapling_roofed_oak", "wood/sapling-roofed")
            elif rest == "leaves":
                add(f"leaves_{bw}", "wood/leaves")
                add(f"{wood}_leaves", "wood/leaves-modern")

        # --- 石材 -------------------------------------------------------- #
        for stone, bed in (
            ("andesite", "stone_andesite"),
            ("diorite", "stone_diorite"),
            ("granite", "stone_granite"),
            ("polished_andesite", "stone_andesite_smooth"),
            ("polished_diorite", "stone_diorite_smooth"),
            ("polished_granite", "stone_granite_smooth"),
        ):
            if name == stone:
                add(bed, "stone/variant")
        for modern, legacy in (
            ("stone_bricks", "stonebrick"),
            ("cracked_stone_bricks", "stonebrick_cracked"),
            ("mossy_stone_bricks", "stonebrick_mossy"),
            ("chiseled_stone_bricks", "stonebrick_carved"),
            ("mossy_cobblestone", "cobblestone_mossy"),
            ("bricks", "brick"),
            ("nether_bricks", "nether_brick"),
            ("red_nether_bricks", "red_nether_brick"),
            ("end_stone_bricks", "end_bricks"),
        ):
            if name == modern:
                add(legacy, "stone/legacy")

        # 深板岩整族在 Bedrock 位于 deepslate/ 子目录
        if name.startswith("deepslate") or name in {
            "cobbled_deepslate",
            "chiseled_deepslate",
            "polished_deepslate",
            "cracked_deepslate_bricks",
            "cracked_deepslate_tiles",
        }:
            add(f"deepslate/{name}", "stone/deepslate")

        # 石英 / 砂岩
        quartz = {
            "chiseled_quartz_block": "quartz_block_chiseled",
            "chiseled_quartz_block_top": "quartz_block_chiseled_top",
            "quartz_pillar": "quartz_block_lines",
            "quartz_pillar_top": "quartz_block_lines_top",
            "smooth_quartz": "quartz_block_bottom",
            "sandstone": "sandstone_normal",
            "red_sandstone": "red_sandstone_normal",
            "chiseled_sandstone": "sandstone_carved",
            "chiseled_red_sandstone": "red_sandstone_carved",
            "cut_sandstone": "sandstone_smooth",
            "cut_red_sandstone": "red_sandstone_smooth",
        }
        if name in quartz:
            add(quartz[name], "stone/variant")

        # --- 珊瑚 -------------------------------------------------------- #
        for shape, color in CORAL_COLORS.items():
            for dead in (False, True):
                src = f"dead_{shape}_coral" if dead else f"{shape}_coral"
                suffix = "_dead" if dead else ""
                if name.startswith(src):
                    tail = name[len(src) :]
                    if tail == "":
                        # Java 的“珊瑚”是植株；Bedrock 的 coral_plant_* 才是植株
                        add(f"coral_plant_{color}{suffix}", "coral/plant")
                    elif tail == "_block":
                        add(f"coral_{color}{suffix}", "coral/block")
                    elif tail == "_fan":
                        add(f"coral_fan_{color}{suffix}", "coral/fan")

        # --- 铁轨 -------------------------------------------------------- #
        rails = {
            "rail": "rail_normal",
            "rail_corner": "rail_normal_turned",
            "powered_rail": "rail_golden",
            "powered_rail_on": "rail_golden_powered",
            "detector_rail": "rail_detector",
            "detector_rail_on": "rail_detector_powered",
            "activator_rail": "rail_activator",
            "activator_rail_on": "rail_activator_powered",
        }
        if name in rails:
            add(rails[name], "rail")

        # --- 农作物阶段 -------------------------------------------------- #
        crop = re.fullmatch(
            r"(wheat|carrots|potatoes|beetroots|nether_wart)_stage(\d+)", name
        )
        if crop:
            add(f"{crop.group(1)}_stage_{crop.group(2)}", "crop/stage")

        return out

    # ------------------------------------------------------------------ #
    # 诊断
    # ------------------------------------------------------------------ #
    def unexplained(self, names: list[str]) -> list[str]:
        """返回无法映射的名字，供报告与数据维护使用。"""
        return [n for n in names if self.resolve(n) is None]
