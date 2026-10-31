#!/usr/bin/env python3
"""claude-dev-system 安裝器（只用 Python 標準庫，需 Python ≥ 3.10）。

用法：python installer/install.py [--claude-home 路徑] <check|install|verify|update|uninstall|status|web> [選項]
  --claude-home     目標設定目錄（預設：環境變數 CLAUDE_CONFIG_DIR，否則 ~/.claude）；測試時指向暫存資料夾
  --python          hook 用的 Python 執行檔（預設：執行本安裝器的這個 Python）
  --force           install／update：覆蓋使用者改過的本工具檔案或區塊；uninstall：連使用者改過的也刪
  --restore-backup  uninstall 後用第一次安裝前的備份還原 settings.json
  --no-claude       verify 時不呼叫 claude --version（測試用）
  --with-web        install／update：同時啟用聯網來源（免金鑰搜尋 MCP＋WebSearch 上限 env；細節 docs/web-sources.md）
  --with-video      install／update：同時啟用影片來源（pip 裝 yt-dlp 等，讓 tools/video.py 可用；細節 docs/video.md）
web 子命令（改本機偏好並立即套用；偏好存 <CLAUDE_HOME>/claude-dev-system/config/local.json，不進 repo）：
  --key 名稱=值     存金鑰（tavily、exa、cwa、youtube、gemini…）   --enable／--disable 名稱   開關某個 MCP
  --env 鍵=值       覆寫 env 值                   --off  關閉聯網來源並移除   --show  只顯示不套用
  --key-mode 名稱=fallback|always   fallback（預設）：免金鑰版與 <名稱>-key 金鑰版並存、規則先用免金鑰；always：只用金鑰版
video 子命令：不帶參數＝啟用（pip 安裝並登記）；--off 取消登記；--show 只檢查依賴與金鑰
gui 子命令：開設定視窗（同 `python installer/gui.py`）：所有開關、金鑰、門檻在視窗裡改，按套用才生效
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
    ap.add_argument("cmd", choices=["check", "install", "verify", "update", "uninstall", "status", "web", "video", "gui"])
    ap.add_argument("--python", default=Path(sys.executable).as_posix())
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--restore-backup", action="store_true")
    ap.add_argument("--no-claude", action="store_true")
    ap.add_argument("--with-web", action="store_true")
    ap.add_argument("--with-video", action="store_true")
    ap.add_argument("--key", action="append", default=[], metavar="名稱=值")
    ap.add_argument("--enable", action="append", default=[], metavar="MCP名稱")
    ap.add_argument("--disable", action="append", default=[], metavar="MCP名稱")
    ap.add_argument("--env", action="append", default=[], metavar="鍵=值")
    ap.add_argument("--key-mode", action="append", default=[], metavar="名稱=fallback|always")
    ap.add_argument("--off", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args(argv)
    lay = Layout(claude_home(a.claude_home))
    if a.cmd == "gui":
        import gui  # noqa: PLC0415
        return gui.main(["--claude-home", str(lay.home)])
    if a.cmd == "check":
        rows = env_report(lay.home)
        for name, ok, msg in rows:
            mark = "✅" if ok else ("⚠️" if ok is None else "❌")
            print(f"{mark} {name}：{msg}")
        return 1 if any(ok is False for _, ok, _ in rows) else 0
    try:
        if a.cmd in ("install", "update"):
            code, log = commands.apply(lay, a.python, force=a.force, mode=a.cmd, with_web=True if a.with_web else None,
                                       with_video=True if a.with_video else None)
        elif a.cmd == "web":
            code, log = commands.web_config(lay, keys=a.key, enable=a.enable, disable=a.disable, env=a.env, off=a.off, show=a.show,
                                            key_mode=a.key_mode)
        elif a.cmd == "video":
            code, log = commands.video_config(lay, a.python, off=a.off, show=a.show)
        elif a.cmd == "uninstall":
            code, log = commands.uninstall(lay, force=a.force, restore_backup=a.restore_backup)
        elif a.cmd == "verify":
            code, log = commands.verify(lay, check_claude=not a.no_claude)
        else:
            code, log = commands.status(lay)
    except ValueError as e:  # 例如 local.json 壞掉：印一行中文，不噴 traceback
        print(f"❌ {e}")
        return 2
    print("\n".join(log))
    return code


if __name__ == "__main__":
    sys.exit(main())
