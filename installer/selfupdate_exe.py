"""exe 更新的備援：由「檢查更新」下載到 app/ 的這一份（最新程式碼）在系統 Python 執行，查 Release、下載、核對、換掉 exe。

為什麼要它：exe 正在執行的更新程式碼是打包時固定的；那段程式碼本身有 bug（例如 0.11.14 在某台電腦遇到 GitHub 憑證錯誤），
規則雖能更新，exe 卻換不掉，只能手動下載。0.11.16 起 exe 自己的步驟失敗就改跑這支——它來自 app/，永遠是最新版，
所以之後更新程式本身的 bug 修好後，舊 exe 也能靠它換成新 exe。
用法：python selfupdate_exe.py --exe <exe 路徑> --current <exe 內建版本> [--check-only]
輸出最後一行是 JSON：{"newer", "tag", "swapped", "error"}（ASCII 跳脫，避免主控台碼頁亂碼）。只用標準庫。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cds import appdir  # noqa: E402


def run(exe: Path, current: str, check_only: bool = False, log=lambda s: print(s, file=sys.stderr)) -> dict:
    out = {"newer": False, "tag": None, "swapped": False, "error": None}
    try:
        info = appdir.check_exe_update(current)
        out["tag"] = info.get("tag")
        if info.get("error"):
            out["error"] = info["error"]
            return out
        out["newer"] = bool(info["newer"])
        if check_only or not info["newer"]:
            return out
        new = appdir.download_exe(info, exe, log)
        appdir.swap_exe(exe, new)
        out["swapped"] = True
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--current", required=True)
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(Path(a.exe), a.current, a.check_only), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
