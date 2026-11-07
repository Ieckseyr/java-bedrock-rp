# labpbr2bedrock

把 **Java 版 labPBR** 材质转换为 **基岩版（Bedrock）高度图 / PBR** 材质包。

**默认以高度图为主**：生成 `<名字>_bedrock`，包内是颜色 + 高度图 + MER，
`texture_set` 引用 heightmap；PBR（法线 + MER）作为可选的额外包。

- 文件夹工作流：Java 包 zip 直接丢进 `input/`，产物在 `output/`
- 默认 `heightmap` 预设；可选 `pbr` 或 `split`（同时生成两个包）
- 输出同时提供资源包文件夹与 `.mcpack`
- Windows 单文件 exe，双击即用
- 结构校验、逐贴图报告、确定性构建

> **版权提示**：本项目只做格式转换，不改变原材质版权。转换产物仅供个人使用；
> 是否允许分发取决于原材质包的 LICENSE（转换时会原样打包为 `LICENSE_source.txt`）。

---

## 1. 通道对照

| 贴图 | Java labPBR 1.3 | Bedrock |
| --- | --- | --- |
| `_n` | R/G 法线（DirectX，Y 向下），B = AO，A = 高度 | `normal`：RGB 法线；`heightmap`：1 通道高度 |
| `_s` | R 感知光滑度，G F0/金属，A 自发光 | `MER`：R 金属度，G 自发光，B 线性粗糙度 |

Bedrock 规定同一个 `texture_set` 中 **normal 与 heightmap 互斥**。因此本项目：

- 默认生成 **heightmap 包**（只引用 heightmap + MER，不写 normal）；
- 需要 PBR 时再生成 **pbr 包**（只引用 normal + MER，不写 heightmap）；
- 两个包一起启用即可同时获得法线与视差（`split` 预设一次生成）。

## 2. 高度图规则

labPBR `_n` 的 alpha：255 = 无位移，0 = 最深。Bedrock heightmap：128 = 中性。

```text
value = 128 * (1 - depth * (1 - alpha / 255))
```

- 平坦表面（alpha = 255）→ 128
- 无 alpha 的 RGB 法线 → 写中性 128
- 完全没有 `_n` 的贴图 → 只有 color + MER（没有高度数据）

## 3. MER 规则

```text
R 金属度 = 255 if _s.G >= 230 else 0
G 自发光 = 0 if _s.A == 255 else round(_s.A * 255 / 254)
B 粗糙度 = round(((1 - _s.R/255)²) * 255)
```

## 4. 启动

### Windows exe（推荐）

1. 把 `labpbr2bedrock.exe` 放在可写文件夹；
2. 双击一次，自动创建 `config.json`、`input\`、`output\`；
3. 把 Java 材质包 `.zip` 原样放进 `input\`（不用解压）；
4. 再次双击。

默认 preset 为 `heightmap`，生成：

```
output\<名字>_bedrock\            # 资源包文件夹
output\<名字>_bedrock.mcpack      # 可直接导入
```

### 源码 / Python

```bash
python -m pip install -e .
python run.py
```

## 5. 输入与命名

- `input/` 里同前缀的多个 zip 自动合并（例如 rotrBLOCKS BASE/DESIGN/DUNGEONS/FLORA/Emiores）；
- 合并后包名取**第一个输入**的文件名，例如 `rotrBLOCKS_BASE_V73_..._512x_bedrock`；
- 精确顺序：`input/order.txt`，每行一个文件名；
- 子文件夹也会合并；
- `group_by_prefix: false` 可改为每个 zip 单独生成。

## 6. 分包预设

`config.json` 的 `preset`：

| preset | 产物 | 说明 |
| --- | --- | --- |
| `heightmap`（默认） | `<名字>_bedrock` | 颜色 + 高度图 + MER |
| `pbr` | `<名字>_bedrock_pbr` | 颜色 + 法线 + MER |
| `split` | 上面两个包 | 两个一起启用 = 法线 + 视差 |

命令行：`python run.py --preset split`。

`presets` 可在 config 里覆盖/扩展；完整字段见 [docs/CONFIG.md](docs/CONFIG.md)。

## 7. 产物结构

```
<名字>_bedrock/
├─ manifest.json              # capabilities: ["raytraced"]
├─ README.txt
├─ LICENSE_source.txt
├─ pack_icon.png
└─ textures/blocks/
   ├─ <name>.png              # 颜色
   ├─ <name>_heightmap.png    # 1 通道高度
   ├─ <name>_mer.png          # R 金属 / G 自发光 / B 粗糙度
   └─ <name>.texture_set.json # color + heightmap + MER
```

`<名字>_bedrock_pbr` 把 heightmap 换成 normal，其余相同。

## 8. 校验与报告

```bash
python -m labpbr2bedrock validate output/*.mcpack
```

每次转换会生成 `.report.json` / `.report.md`，含映射、图层、高度极差、失败原因。

## 9. 已知限制

1. 只转 `textures/block/**`；实体/物品/盔甲/模型不转。
2. 动画贴图（`.png.mcmeta`）跳过。
3. 无 alpha 高度的贴图在 heightmap 包中为中性 128（平坦），没有视差细节。
4. 介电 F0（`_s.G` 0–229）无对应通道，按非金属处理；230–255 视为金属。
5. AO、孔隙度/SSS 在 MER 中无对应通道，默认丢弃。
6. OptiFine CTM 跳过。
7. 颜色贴图按原始字节拷贝。

## 10. 构建与测试

```bash
python -m pip install -e .
scripts\build_exe.bat                 # 构建 exe
python scripts/make_exe_release.py    # 生成发布 zip
```

## 11. 目录结构

```
src/labpbr2bedrock/
  imaging.py / labpbr.py / bedrock.py / name_map.py
  java_pack.py / pack_writer.py / pipeline.py
  runconfig.py / batch.py / validate.py / report.py / cli.py
  data/                 词表与别名
exe_entry.py            单文件 exe 入口
labpbr2bedrock.spec     PyInstaller 配置
assets/                 图标与版本信息
docs/                   配置、转换、打包、排错
scripts/                构建 exe / 发布 zip / 重建材质包
```

## 12. 实测产物

输入：rotrBLOCKS BASE + DESIGN + DUNGEONS + FLORA + Emiores（按 `order.txt` 合并）。

| 包 | texture_set | heightmap | normal | MER | 体积 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `..._bedrock`（默认） | 837 | 835 | 0 | 760 | ~441 MiB |
| `..._bedrock_pbr`（可选） | 837 | 0 | 835 | 760 | ~767 MiB |

两个包一起启用 = 法线 + 高度视差。

## 13. 许可

工具代码 MIT License；转换产物版权归原材质作者所有。
