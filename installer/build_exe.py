#!/usr/bin/env python3
"""把設定視窗打包成單檔執行檔（Windows；需 `pip install pyinstaller`）。

用法：python installer/build_exe.py [--console] [--dist 資料夾]
產物：dist/claude-dev-system-settings.exe。exe 內含 repo 快照（rules、tools、hooks、skills、config、installer、docs、README、CHANGELOG）
放在 _MEIPASS/repo，cds.paths.REPO 在 frozen 模式會指到那裡；之後的規則更新走視窗的「檢查更新」（cds/appdir.py），不用重打包。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NAME = "claude-dev-system-settings"
DIRS = ("rules", "tools", "hooks", "skills", "config", "installer", "docs")
FILES = ("README.md", "CHANGELOG.md", "CLAUDE.md")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # GitHub Actions 的 Windows runner 主控台是 cp1252，印中文會炸
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--console", action="store_true", help="保留主控台視窗（除錯用）")
    ap.add_argument("--dist", default=str(REPO / "dist"))
    a = ap.parse_args(argv)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺 pyinstaller：py -3 -m pip install pyinstaller")
        return 2
    sep = os.pathsep
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", NAME,
           "--paths", str(REPO / "installer"), "--distpath", a.dist, "--workpath", str(REPO / "build" / "pyinstaller"), "--specpath", str(REPO / "build"),
           "--exclude-module", "PyInstaller"]
    cmd.append("--console" if a.console else "--windowed")
    for d in DIRS:
        cmd += ["--add-data", f"{REPO / d}{sep}repo/{d}"]
    for f in FILES:
        if (REPO / f).exists():
            cmd += ["--add-data", f"{REPO / f}{sep}repo"]
    cmd.append(str(REPO / "installer" / "gui.py"))
    print(" ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        return r.returncode
    exe = Path(a.dist) / (NAME + (".exe" if sys.platform == "win32" else ""))
    print(f"產物：{exe}（{exe.stat().st_size / 1024 / 1024:.1f} MB）" if exe.exists() else "找不到產物")
    for junk in (REPO / "build" / "pyinstaller",):
        shutil.rmtree(junk, ignore_errors=True)
    return 0 if exe.exists() else 1


if __name__ == "__main__":
    sys.exit(main())
