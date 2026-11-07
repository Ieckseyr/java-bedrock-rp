# 更新日志

## 1.0.0

- **高度图为主**：默认 `preset: heightmap` 生成 `<名字>_bedrock`，
  `texture_set` 引用 `heightmap` + MER，不写 normal。
  - 有 alpha 高度的贴图用 alpha 生成高度图；
  - 纯 RGB 法线写中性 128 高度图；
  - 没有 `_n` 的贴图只有 color + MER。
- **PBR 可选**：`preset: pbr` 生成 `<名字>_bedrock_pbr`（normal + MER）；
  `preset: split` 一次生成高度图包 + PBR 包，两个一起启用可同时获得视差与法线。
- 输出同时提供资源包文件夹 `<名字>_bedrock/` 和 `<名字>_bedrock.mcpack`
  （`output_format` 可改为只出其中一种）。
- 文件夹工作流：`input/` 放 zip 即可；同前缀的多个 zip 自动合并，包名取第一个输入；
  `input/order.txt` 指定顺序；支持 watch、增量跳过、`--force`。
- 命名映射（规则族 + 别名 + Bedrock 词表）、`.tga` 输出、尺寸自动缩放。
- 结构校验、JSON/Markdown 报告、确定性构建。
- Windows 单文件 exe + 最简发布 zip。
- 版本 1.0.0。
