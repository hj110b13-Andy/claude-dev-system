"""影片來源（選用）：依 config/video.json 用「執行安裝器的 Python」pip 安裝 yt-dlp 等套件，讓 tools/video.py 可用。

為什麼不做成 MCP：第三方 YouTube MCP 都是本機常駐程序＋各自依賴，底層仍是 yt-dlp；做成單檔 CLI 由 Claude 依規則呼叫，
沒有背景程序、跨裝置只要 pip。faster-whisper（沒字幕時的語音辨識）體積大、GPU 版要額外 CUDA 套件，不自動裝，verify 以 ⚠️ 提示。
狀態記在 manifest 的 video；`--off` 只取消登記、不解除安裝 pip 套件（可能被別的程式用）。
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys

from .fsio import read_json
from .paths import Layout

CONFIG_REL = "config/video.json"
OK, BAD, WARN = "✅", "❌", "⚠️"


def empty_record() -> dict:
    return {"enabled": False, "packages": [], "python": None}


def config(lay: Layout) -> dict:
    return read_json(lay.payload / CONFIG_REL)


def default_pip(python: str, packages: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run([python, "-m", "pip", "install", "--upgrade", "--quiet", *packages], capture_output=True, timeout=900)
    except Exception as e:  # noqa: BLE001
        return 1, str(e)
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    return r.returncode, "\n".join(x for x in out.splitlines() if "notice" not in x and x.strip())[-800:]


def default_importer(mod: str) -> str | None:
    """回傳版本字串（沒有版本就 ''），匯入失敗回 None。用執行安裝器的 Python 檢查。"""
    try:
        m = importlib.import_module(mod)
    except Exception:  # noqa: BLE001
        return None
    v = getattr(m, "__version__", None)
    if v is None and mod == "yt_dlp":
        try:
            v = m.version.__version__
        except Exception:  # noqa: BLE001
            v = ""
    return str(v or "")


def ffmpeg_path() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    if sys.platform == "win32":
        import glob
        import os
        from pathlib import Path
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        hits = sorted(glob.glob(str(base / "Gyan.FFmpeg*" / "*" / "bin" / "ffmpeg.exe")))
        if hits:
            return hits[-1]
    return None


def sync(lay: Layout, python: str, enable: bool, pip=default_pip, log: list | None = None) -> dict:
    """enable → pip 安裝 config 的 packages；回傳要寫進 manifest 的紀錄。"""
    log = log if log is not None else []
    if not enable:
        return empty_record()
    pk = list(config(lay).get("packages") or [])
    code, out = pip(python, pk)
    if code != 0:
        log.append(f"{BAD} 影片套件安裝失敗（{python} -m pip install {' '.join(pk)}）：{out[-400:]}")
        return {"enabled": True, "packages": [], "python": python}
    log.append(f"影片套件已安裝／更新：{', '.join(pk)}（{python}）")
    return {"enabled": True, "packages": pk, "python": python}


IMPORTS = {"yt_dlp": "yt-dlp", "youtube_transcript_api": "youtube-transcript-api"}


def verify_rows(lay: Layout, rec: dict, importer=default_importer, local_keys: dict | None = None, ffmpeg=ffmpeg_path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if not rec.get("enabled"):
        rows.append((OK, "影片來源：未啟用（選用；`install.py video` 或 `update --with-video` 可開）"))
        return rows
    for mod, name in IMPORTS.items():
        v = importer(mod)
        rows.append((OK if v is not None else BAD, f"影片套件 {name}" + (f" {v}" if v else "") + ("" if v is not None else " 未安裝（重跑 `install.py video`）")))
    ff = ffmpeg()
    rows.append((OK if ff else BAD, f"ffmpeg：{ff}" if ff else "ffmpeg 找不到（winget install Gyan.FFmpeg，或加進 PATH）"))
    fw = importer("faster_whisper")
    rows.append((OK if fw is not None else WARN, f"faster-whisper {fw}（沒字幕的影片可轉逐字稿）" if fw is not None
                 else "faster-whisper 未裝：沒字幕的影片無法轉逐字稿（選用：`pip install faster-whisper`）"))
    keys = local_keys or {}
    rows.append((OK, "影片金鑰：" + (", ".join(sorted(k for k in ("youtube", "gemini") if keys.get(k))) or "無（youtube→數據與留言；gemini→真的看畫面；都選用）")))
    return rows
