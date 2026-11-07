#!/usr/bin/env python3
"""便携启动器：不安装包也能直接运行。

双击 / 命令行运行后：
1. 首次运行自动创建 ``config.json``、``input/``、``output/``；
2. 把 Java 材质包 zip 放进 ``input/``（或子文件夹）后再次运行；
3. 产物出现在 ``output/``。

直接运行本文件等价于 ``labpbr2bedrock run``；也可以传其它子命令::

    python run.py --watch
    python run.py convert --java-pack a.zip -o out/a.mcpack
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from labpbr2bedrock.cli import main  # noqa: E402

_KNOWN = {"run", "convert", "validate", "map", "--help", "-h", "--version"}


def _argv() -> list[str]:
    argv = sys.argv[1:]
    if not argv or argv[0] not in _KNOWN:
        return ["run", *argv]
    return argv


if __name__ == "__main__":
    raise SystemExit(main(_argv()))
