# 故障排查

## 先看报告

每次转换生成 `<pack>.report.json` 与 `.report.md`：

| 字段 | 含义 |
| --- | --- |
| `stats` | 扫描 / 映射 / 写出 / 跳过 / 失败计数 |
| `unmapped` | 没有 Bedrock 对应名的 Java 贴图 |
| `failed` | 失败原因 |
| `warnings` | 目标名冲突、图层缩放等 |
| `textures[]` | 每张贴图的 `java` / `bedrock` / `layers` / `status` |

## 高度图包

### 没有视差效果

1. 确认生成的是 **heightmap** 包，而不是 pbr 包：
   - 默认 `<名字>_bedrock` 的 texture_set 应包含 `"heightmap"`，不含 `"normal"`；
   - `<名字>_bedrock_pbr` 是法线包，没有高度图。
2. 打开 `textures/blocks/<方块>.texture_set.json`，确认有 `"heightmap"`；
3. 确认对应的 `_heightmap.png` 存在且是单通道；
4. 贴图本身可能没有高度：纯 RGB 法线的贴图会得到中性 128 的平坦高度图，
   平坦图没有可见视差，这是源数据限制；
5. `height_depth` 默认 1.0，可调小让视差更保守；
6. RTX 需要在世界设置里开启光线追踪；Vibrant Visuals 需要在视频设置里开启。

### 想要法线 + 视差同时存在

一个 texture_set 不能同时有 normal 和 heightmap。请用 `split` 预设生成两个包：

```
<名字>_bedrock/        # 高度图
<名字>_bedrock_pbr/    # 法线
```

两个都启用即可。

### 高度图包里有 normal 文件吗

默认不写 normal。`find ... -name "*_normal.png"` 可能匹配到名字本身以
`_normal` 结尾的颜色贴图（例如 `sandstone_normal.png`），这是颜色贴图不是法线图层。

## PBR 包（可选）

- 默认 `preset: heightmap` 不会生成 pbr 包；
- 改 `preset: pbr` 生成 `<名字>_bedrock_pbr`；
- `preset: split` 一次生成两个包；
- 命令行：`python run.py --preset pbr` / `--preset split`。

## 文件夹模式

### output 为空

- `input/` 里要有 `.zip` 或含 zip 的子文件夹；
- 已有产物比输入新时会跳过，用 `--force`；
- `targets` 非空时不会扫描 `input/`；
- 只有 OptiFine CTM 的包没有方块贴图，会正常结束但 texture_set 为 0。

### 多个 zip 怎么合并

- 同前缀的 zip 自动合并（rotrBLOCKS BASE/DESIGN/...）；
- 或用子文件夹包住它们；
- `input/order.txt` 指定顺序；
- 包名取合并后第一个输入的名字。

### 命名不是想要的

- 高度图包：`<名字>_bedrock`；
- PBR 包：`<名字>_bedrock_pbr`；
- 在 `presets` 的 `mode_suffixes` / `name_suffix` 里改。

## 其他

- 法线看起来是反的：`--flip-green`；
- 颜色变暗：是否用了 `--bake-ao`；
- 贴图不生效：确认包已启用、目标名与游戏版本一致、`.tga` 优先级；
- 杀毒误报：PyInstaller 单文件程序偶发误报，可加入信任或源码运行。
