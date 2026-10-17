#!/usr/bin/env python3
"""claude-dev-system 安裝器（只用 Python 標準庫，需 Python ≥ 3.10）。

用法：python installer/install.py [--claude-home 路徑] <check|install|verify|update|uninstall|status> [選項]
  --claude-home     目標設定目錄（預設：環境變數 CLAUDE_CONFIG_DIR，否則 ~/.claude）；測試時指向暫存資料夾
  --python          hook 用的 Python 執行檔（預設：執行本安裝器的這個 Python）
  --force           install／update：覆蓋使用者改過的本工具檔案或區塊；uninstall：連使用者改過的也刪
  --restore-backup  uninstall 後用第一次安裝前的備份還原 settings.json
  --no-claude       verify 時不呼叫 claude --version（測試用）
結束碼：0 成功／全部通過；1 check 或 verify 有 ❌；2 用法或狀態錯誤。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cds import commands  # noqa: E402
from cds.checks import env_report  # noqa: E402
from cds.paths import Layout, claude_home  # noqa: E402


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if sys.version_info < (3, 10):
        print("需要 Python 3.10 以上")
        return 2
    ap = argparse.ArgumentParser(description="claude-dev-system 安裝器")
    ap.add_argument("--claude-home")
    ap.add_argument("cmd", choices=["check", "install", "verify", "update", "uninstall", "status"])
    ap.add_argument("--python", default=Path(sys.executable).as_posix())
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--restore-backup", action="store_true")
    ap.add_argument("--no-claude", action="store_true")
    a = ap.parse_args(argv)
    lay = Layout(claude_home(a.claude_home))
    if a.cmd == "check":
        rows = env_report(lay.home)
        for name, ok, msg in rows:
            mark = "✅" if ok else ("⚠️" if ok is None else "❌")
            print(f"{mark} {name}：{msg}")
        return 1 if any(ok is False for _, ok, _ in rows) else 0
    if a.cmd in ("install", "update"):
        code, log = commands.apply(lay, a.python, force=a.force, mode=a.cmd)
    elif a.cmd == "uninstall":
        code, log = commands.uninstall(lay, force=a.force, restore_backup=a.restore_backup)
    elif a.cmd == "verify":
        code, log = commands.verify(lay, check_claude=not a.no_claude)
    else:
        code, log = commands.status(lay)
    print("\n".join(log))
    return code


if __name__ == "__main__":
    sys.exit(main())
