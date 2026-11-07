#!/usr/bin/env python3
"""单文件 exe 的入口。

行为：
- 双击运行时等价于 ``labpbr2bedrock run``：在 exe 所在目录自动创建
  ``config.json``、``input/``、``output/``，然后把 ``input/`` 里的 zip
  （含子文件夹）批量转换；
- 命令行参数原样传给 CLI，例如 ``labpbr2bedrock.exe --watch``；
- 双击运行结束后暂停，便于查看结果；带参数运行不暂停。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _set_utf8_console() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass


def main() -> int:
    _set_utf8_console()
    base = _base_dir()
    os.chdir(base)
    src = base / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from labpbr2bedrock.cli import main as cli_main

    raw_args = sys.argv[1:]
    known = {"run", "convert", "validate", "map", "--help", "-h", "--version"}
    args = raw_args if raw_args and raw_args[0] in known else ["run", *raw_args]
    pause = not raw_args and sys.stdin is not None and sys.stdin.isatty()

    code = 0
    try:
        code = cli_main(args)
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:  # 双击运行时也要让用户看到错误
        print(f"\n[错误] {exc}", file=sys.stderr)
        traceback.print_exc()
        code = 1
    finally:
        if pause:
            try:
                input("\n按回车键退出...")
            except EOFError:
                pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
