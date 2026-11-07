# 转换规则

## 1. 依据

| 主题 | 来源 |
| --- | --- |
| labPBR 通道定义 | shaderLABS LabPBR Material Standard 1.3 |
| Bedrock texture set / MER / heightmap | Microsoft Learn Texture Set 文档 |
| 高度图中性值 = 0.5、normal 与 heightmap 互斥 | NVIDIA Minecraft RTX PBR Texturing Guide |
| 法线 DirectX（Y 向下） | NVIDIA 指南 + labPBR 规范 |

## 2. 高度图（默认主产物）

labPBR `_n.A`：

- 255 = 无位移（表面）
- 0 = 约 25% 深度（向内）
- 规范建议最小值不低于 1

Bedrock heightmap：

- 0 = 最深，128 = 中性（0.5），255 = 最高

映射：

```text
h = max(A, height_min)
value = 128 * (1 - depth * (1 - h / 255))
```

- `A = 255` → 128（中性）
- `A = 0` → `128 * (1 - depth)`，默认 `depth=1` 时约 0
- `--height-depth 0.5` 可让视差更保守
- 纯 RGB 法线（无 alpha）→ 写 128 的平坦高度图
- 没有 `_n` 的贴图 → 只有 color + MER

输出为单通道 PNG（`L` 模式）。

## 3. MER（`_s` -> `_mer`）

```text
R 金属度 = 255 if G >= 230 else 0
G 自发光 = 0 if A == 255 else round(A * 255 / 254)
B 粗糙度 = round(((1 - R/255)²) * 255)
```

- labPBR `_s.G` 230–255 为金属；0–229 是介电 F0，Bedrock 无对应通道，按非金属处理
- `_s.A = 255` 表示不发光
- `_s.R` 是感知光滑度，Bedrock 用线性粗糙度，所以取平方
- `_s.B`（孔隙/SSS）在 MER 中无对应通道，丢弃

## 4. 法线（仅 PBR 可选包）

labPBR `_n`：

```text
x = R/127.5 - 1
y = G/127.5 - 1
z = sqrt(max(0, 1 - x² - y²))
R' = R, G' = G, B' = 127.5 * (z + 1)
```

- 蓝通道是 AO，不是 Z，必须重建
- labPBR 与 Bedrock 都是 DirectX（Y 向下），默认不翻转绿通道
- `--flip-green` 可用于异常工具链
- AO 默认丢弃，`--bake-ao` 可乘进颜色

## 5. 尺寸与 TGA

- 法线/高光与颜色尺寸不一致时，默认双线性缩放对齐；`--no-resize` 改为跳过
- 新版原版只提供 `.tga` 的 24 张目标贴图会输出 `.tga`（RLE，保留 alpha）

## 6. 确定性

- ZIP 时间戳固定 1980-01-01
- manifest UUID 由名称 + 模式派生
- 贴图按目标名排序处理
- 相同输入/工具版本生成字节一致的产物
