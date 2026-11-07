# labpbr2bedrock 1.0.0

Windows 单文件版：把 Java 版 labPBR 材质包转换为基岩版 PBR 材质包。

**默认以高度图为主**；PBR（法线）是可选额外包。

## 使用

1. 解压后双击 `labpbr2bedrock.exe`。
2. 首次运行自动创建 `config.json`、`input\`、`output\`。
3. 把 Java 材质包的 `.zip` **原样**放进 `input\`（不用解压）。
4. 再次双击。

默认产物在 `output\`：

- `<名字>_bedrock\`：高度图资源包（manifest 在根，可直接放进 resource_packs）
- `<名字>_bedrock.mcpack`：可直接导入的压缩包

## 分包预设

`config.json` 的 `preset`：

- `heightmap`（默认）：`<名字>_bedrock`（heightmap + MER）
- `pbr`：`<名字>_bedrock_pbr`（normal + MER）
- `split`：同时生成两个包；一起启用 = 法线 + 视差

## 其他

- `input\` 里同前缀的多个 zip 自动合并（rotrBLOCKS BASE/DESIGN/... 只出一个包）；
  包名取合并后第一个输入。
- `output_format` 可选 `mcpack` / `folder` / `both`（默认 both）。
- 不需要安装 Python，也不需要解压 Java 材质包。

详细说明见压缩包内 `README.txt`。
