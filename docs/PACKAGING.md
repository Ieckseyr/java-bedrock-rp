# 打包规则与产物

## 1. 官方硬性规则

来自 Microsoft 的 Texture Set 文档：

1. `color` 是唯一必填图层；
2. `normal` 与 `heightmap` 不能同时出现，否则整个 texture_set 无效；
3. MER 与 MERS 不能同时出现；
4. heightmap 必须是单通道；
5. texture_set 只能引用同一个包内的贴图。

因此本项目把“高度图包”和“PBR 包”分开生成，而不是塞进同一个 texture_set。

## 2. 高度图包（默认）

`preset: heightmap`，产物 `<名字>_bedrock`：

```json
{
  "color": "stone",
  "heightmap": "stone_heightmap",
  "metalness_emissive_roughness": "stone_mer"
}
```

- 包内只有颜色、高度图、MER（不写 normal）；
- 有 alpha 高度的贴图使用 alpha 生成高度图；
- 纯 RGB 法线（没有 alpha）写中性 128 的平坦高度图；
- 完全没有 `_n` 的贴图只有 color + MER；
- 这是默认产物，`texture_set` 永远不含 normal。

## 3. PBR 包（可选）

`preset: pbr`，产物 `<名字>_bedrock_pbr`：

```json
{
  "color": "stone",
  "normal": "stone_normal",
  "metalness_emissive_roughness": "stone_mer"
}
```

- 包内只有颜色、法线、MER（不写 heightmap）；
- heightmap 包与 pbr 包一起启用，可同时获得高度视差与法线细节；
- 不需要 PBR 时只用默认高度图包即可。

## 4. split 预设

`preset: split` 一次生成两个包：

```
<名字>_bedrock/          # 高度图 + MER
<名字>_bedrock_pbr/      # 法线 + MER
```

两个包内容除高度图/法线外一致（同一套颜色与 MER），建议同时启用。

## 5. 输出容器

| `output_format` | 产物 |
| --- | --- |
| `mcpack` | 只有 `<名字>_bedrock.mcpack` |
| `folder` | 只有 `<名字>_bedrock/` 资源包文件夹 |
| `both`（默认） | 两者都有 |

文件夹可直接放进 Bedrock 资源包目录；`.mcpack` 可双击导入。内部结构相同，manifest 在根目录。

## 6. 命名

- 合并输入的包名 = 合并后**第一个输入**的文件名；
  例如 `rotrBLOCKS_BASE_V73_1.21.4-1.13_512x`。
- 高度图包：`<名字>_bedrock` + 容器后缀；
- PBR 包：`<名字>_bedrock_pbr`；
- `mode_suffixes` 可在预设里改这些后缀。

## 7. merge 模式（`--base-pack`）

给出一个现有 Bedrock 包时：

1. 拷贝底板包全部内容；
2. 跳过将被替换的图层/ texture_set；
3. 按当前模式写入 heightmap 或 normal + MER；
4. 键级合并已有 texture_set，保留 color 与未知键，保证 normal/heightmap 不共存；
5. 底板缺失的颜色贴图会从 Java 侧补齐（可关闭）。

## 8. manifest

```json
{
  "format_version": 2,
  "header": {
    "name": "<包名>",
    "description": "Java labPBR -> Bedrock heightmap|pbr",
    "uuid": "<uuid5(seed/header)>",
    "version": [1, 0, 0],
    "min_engine_version": [1, 16, 0]
  },
  "modules": [{ "type": "resources", "uuid": "...", "version": [1, 0, 0] }],
  "capabilities": ["raytraced"],
  "metadata": { "authors": ["labpbr2bedrock"], "generated_with": { "labpbr2bedrock": ["1.0.0"] } }
}
```

## 9. 扩展名优先级

Bedrock 在同一目录内按 `.tga > .png > .jpg > .jpeg` 选择贴图。新版原版中只提供
`.tga` 的 24 张目标贴图（草、树叶、仙人掌、砂轮等）会输出 `.tga`，其余输出 `.png`。

## 10. 校验

`labpbr2bedrock validate <pack>` 检查：

- manifest 可解析、含 header/resources 模块；
- 每个 texture_set 有 color；
- normal/heightmap 不共存；
- MER/MERS 不共存；
- 引用的贴图存在且可解码；
- heightmap 单通道、normal/MER 3 或 4 通道。
