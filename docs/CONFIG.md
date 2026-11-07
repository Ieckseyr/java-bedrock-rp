# config.json 参考

`run` 命令（以及 `run.py` / `start.bat` / `start.sh`）读取 `config.json`。
首次运行如果不存在，会自动生成默认配置，并创建 `input/`、`output/`。

所有相对路径都相对于 config.json 所在目录。

## 默认配置

```json
{
  "version": 1,
  "input_dir": "input",
  "output_dir": "output",
  "mode": "heightmap",
  "modes": [],
  "preset": "heightmap",
  "presets": {
    "heightmap": { "modes": ["heightmap"], "output_format": "both", "name_suffix": "_bedrock", "mode_suffixes": { "heightmap": "" } },
    "pbr":       { "modes": ["pbr"],       "output_format": "both", "name_suffix": "_bedrock", "mode_suffixes": { "pbr": "_pbr" } },
    "split":     { "modes": ["heightmap", "pbr"], "output_format": "both", "name_suffix": "_bedrock", "mode_suffixes": { "heightmap": "", "pbr": "_pbr" } }
  },
  "jobs": 8,
  "overwrite": false,
  "watch": false,
  "watch_interval": 5.0,
  "verify": true,
  "report": true,
  "name_suffix": "_bedrock",
  "output_format": "both",
  "include_mode_in_name": false,
  "vibrant_visuals": false,
  "base_pack": null,
  "group_by_prefix": true,
  "conversion": {
    "metal_threshold": 230,
    "roughness": "linear",
    "height_depth": 1.0,
    "height_min_span": 8,
    "flip_green": false,
    "bake_ao": false,
    "resize_mismatched": true,
    "mixed_include_heightmap_files": true,
    "mixed_json": "auto"
  },
  "targets": []
}
```

## 顶层字段

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `input_dir` | `input` | 输入目录 |
| `output_dir` | `output` | 输出目录 |
| `mode` | `heightmap` | 单模式：`heightmap` / `pbr` |
| `modes` | `[]` | 多模式；非空时覆盖 `mode` |
| `preset` | `heightmap` | 分包预设（见下） |
| `presets` | 内置 | 预设定义；同名覆盖内置项 |
| `jobs` | 8 | 转换线程数 |
| `overwrite` | false | 强制重建（等价 `--force`） |
| `watch` | false | 持续监视 `input/` |
| `watch_interval` | 5.0 | 监视间隔（秒） |
| `verify` | true | 转换后结构校验 |
| `report` | true | 输出 `<pack>.report.json/md` |
| `name_suffix` | `_bedrock` | 输出名后缀 |
| `output_format` | `both` | `mcpack` / `folder` / `both` |
| `include_mode_in_name` | false | 强制把模式写进文件名 |
| `vibrant_visuals` | false | 输出 VV 包（`pbr` 能力，min_engine 1.21.120） |
| `base_pack` | null | 可选：注入现有基岩包 |
| `group_by_prefix` | true | 同前缀 zip 自动合并 |
| `conversion` | 见下 | 转换参数 |
| `targets` | `[]` | 显式目标；非空时不扫描 `input/` |

## 分包预设

| preset | 产物 | 说明 |
| --- | --- | --- |
| `heightmap`（默认） | `<名字>_bedrock` | 颜色 + 高度图 + MER |
| `pbr` | `<名字>_bedrock_pbr` | 颜色 + 法线 + MER |
| `split` | 上面两个包 | 两个一起启用 = 法线 + 视差 |

预设字段：

- `modes`：该预设生成的模式，覆盖全局 `modes`/`mode`；
- `name_suffix`：输出名后缀；
- `mode_suffixes`：模式到名字后缀的映射，例如 `{"heightmap": "", "pbr": "_pbr"}`；
- `output_format`：容器形式。

命令行：`python run.py --preset split`。

## conversion

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `metal_threshold` | 230 | `_s.G` >= 该值视为金属 |
| `roughness` | `linear` | `linear`（(1-s)²）或 `perceptual`（255-R） |
| `height_depth` | 1.0 | 高度图向内深度比例 |
| `height_min_span` | 8 | alpha 极差阈值（报告/auto 选择用） |
| `flip_green` | false | 翻转法线绿通道 |
| `bake_ao` | false | 把 AO 乘进颜色 |
| `resize_mismatched` | true | 法线/高光尺寸不一致时缩放 |
| `mixed_include_heightmap_files` | true | 旧 Mixed 兼容项 |
| `mixed_json` | `auto` | 旧 Mixed 兼容项 |

高度图/PBR 预设不需要 `mixed_*`；这两项只用于兼容旧的 `mixed` 模式。

## targets

```json
"targets": [
  {
    "name": "rotrBLOCKS_512x",
    "sources": ["D:/packs/BASE.zip", "D:/packs/Emiores.zip"],
    "modes": ["heightmap"],
    "output": "output/rotrBLOCKS_512x_bedrock.mcpack",
    "base_pack": null
  }
]
```

## 自动发现

```
input/
├─ Pack.zip                 -> Pack_bedrock（或 Pack_bedrock_pbr）
├─ Group/                   -> 组内 zip 合并
│  ├─ 01_BASE.zip
│  └─ 02_ADDON.zip
└─ UnpackedPack/            -> 解压后的单个包
   └─ pack.mcmeta
```

- 同前缀的多个 zip 自动合并，任务名取合并后第一个输入；
- `input/order.txt` 指定顺序；
- `group_by_prefix: false` 关闭自动合并。

## 增量

产物不存在或输入比产物新时才重建；`overwrite: true` / `--force` 强制重建。
