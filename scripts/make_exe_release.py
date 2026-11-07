"""把 exe 与最简说明打包成可直接分发的 zip。

用法::

    python scripts/make_exe_release.py

输出::

    dist/labpbr2bedrock-<version>-win64.zip
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:  # GitHub Actions 的 Windows runner 默认不是 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from labpbr2bedrock._version import __version__  # noqa: E402


def main() -> int:
    exe = ROOT / "dist" / "labpbr2bedrock.exe"
    if not exe.exists():
        # PyInstaller 在不同平台/版本上可能把 exe 放进子目录，兜底搜索一下
        candidates = sorted((ROOT / "dist").rglob("*.exe"))
        if not candidates:
            print(f"exe not found under {ROOT / 'dist'}", file=sys.stderr)
            return 1
        exe = candidates[0]

    version = __version__
    prefix = f"labpbr2bedrock-{version}-win64"
    output = ROOT / "dist" / f"{prefix}.zip"

    entries = [
        (exe, f"{prefix}/labpbr2bedrock.exe"),
        (ROOT / "README_EXE.txt", f"{prefix}/README.txt"),
        (ROOT / "config.example.json", f"{prefix}/config.example.json"),
        (ROOT / "LICENSE", f"{prefix}/LICENSE.txt"),
    ]

    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in entries:
            if not path.exists():
                print(f"skip missing file: {path}", file=sys.stderr)
                continue
            archive.write(path, arcname)

    size = output.stat().st_size
    print(f"built {output} ({size / (1024 * 1024):.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
