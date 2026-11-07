labpbr2bedrock 1.0.0（Windows 单文件版）
========================================

默认生成**高度图**材质包；PBR（法线）是可选额外包。

三步使用
--------
1. 把 labpbr2bedrock.exe 放在一个可写的文件夹里（不要放 C:\Program Files）。
2. 双击一次，自动生成 config.json、input\、output\。
3. 把 Java 材质包 .zip 原样放进 input\（不用解压），再双击。

产物在 output\：
  <名字>_bedrock\           资源包文件夹（默认，高度图 + MER）
  <名字>_bedrock.mcpack     可直接导入

需要的说明
----------
- input\ 里同前缀的多个 zip 会自动合并（例如 rotrBLOCKS BASE/DESIGN/...）。
- 默认 preset = heightmap，只有高度图，不再生成混合模式。
- 想额外要 PBR：把 config.json 的 "preset" 改成 "pbr"（生成 _bedrock_pbr），
  或改成 "split"（一次生成 _bedrock + _bedrock_pbr，两个一起启用 = 法线 + 视差）。
- 输出同时包含资源包文件夹和 .mcpack；"output_format" 可改为 mcpack 或 folder。
- 不需要安装 Python，也不需要解压 Java 材质包。

注意
----
- 转换产物仅供个人使用，请遵守原材质包的 LICENSE。
- 详细配置见同目录 config.example.json；工具代码为 MIT License。
