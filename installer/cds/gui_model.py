"""設定視窗（gui.py）的純邏輯層：讀真實狀態、算差異、排套用步驟、測金鑰、偵測環境。不碰 tkinter，可單元測試。

原則：畫面上每個狀態都來自這裡的 read_state()，而 read_state() 只讀真實檔案與偵測結果（manifest、settings.json、
~/.claude.json、local.json、pip import、執行檔），不讀表單記憶；套用後必須重新 read_state()。
所有「做事」仍呼叫 commands.*（唯一來源），這裡只決定「做哪些、什麼順序」。
"""
from __future__ import annotations

import copy
import datetime as _dt
import glob
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import commands, manifest as mf, video, web
from .checks import claude_code_status, parse_ver
from .fsio import read_json, write_json
from .paths import FROZEN, REPO, Layout, repo_version

# ---------- 常數 ----------

KEY_INFO = {  # 名稱 → (顯示名, 類別, 說明, 註冊網址)。類別 search 的金鑰有免費優先模式；data 類沒有免金鑰版。
    "cwa": ("中央氣象署", "data", "台灣鄉鎮預報、潮汐、地震、警特報；一般會員每天 2 萬次／2 GB", "https://opendata.cwa.gov.tw/"),
    "moenv": ("環境部空品", "data", "台灣官方測站 AQI；每個 API 每天 5,000 次", "https://data.moenv.gov.tw/"),
    "openaq": ("OpenAQ", "data", "國外官方測站空品；每分鐘 60、每小時 2,000 次", "https://explore.openaq.org/register"),
    "tdx_id": ("TDX Client Id", "data", "交通部停車場等靜態資料；基礎會員每分鐘 5 次、每月約 4,500 次", "https://tdx.transportdata.tw/"),
    "tdx_secret": ("TDX Client Secret", "data", "與 tdx_id 成對", "https://tdx.transportdata.tw/"),
    "youtube": ("YouTube Data API", "data", "影片觀看數、留言、日期篩選搜尋；每天 100 次搜尋、其他 10,000 單位", "https://console.cloud.google.com/apis/credentials"),
    "gemini": ("Gemini", "data", "真的看影片畫面；免費層 3.8 Flash 每天 20 次、3.5 Flash Lite 每天 500 次", "https://aistudio.google.com/api-keys"),
    "tavily": ("Tavily", "search", "搜尋＋乾淨擷取＋整站爬；免費 1,000 credits／月（Pay as you go 預設關）", "https://app.tavily.com/"),
    "exa": ("Exa", "search", "語意搜尋（描述想找的頁面）；免費每月 1 日重置 $10", "https://dashboard.exa.ai/api-keys"),
    "context7": ("Context7", "search", "程式庫官方文件；免費 1,000 次／月", "https://context7.com/dashboard"),
    "parallel": ("Parallel", "search", "一般網頁搜尋＋抓頁；註冊送 $20 一次性、綁卡後每月 $5（自動儲值預設關、只在主動買額度時收費）；有金鑰多 web_research", "https://platform.parallel.ai/"),
    "firecrawl": ("Firecrawl", "search", "JS 動態頁面抓取（讀整頁第三步）；免費 1,000 credits／月", "https://www.firecrawl.dev/app/api-keys"),
}
ENV_DESC = {
    "CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION": "內建 WebSearch 每場對話上限（官方預設 200）",
    "CLAUDE_CODE_WEB_SEARCH_REFILLS_PER_HOUR": "內建 WebSearch 每小時補回次數（官方預設 100）",
    "PYTHONUTF8": "叫 Python 一律用 UTF-8（Windows 碼頁 950 下中文才不亂碼；1＝開）",
    "PYTHONIOENCODING": "Python 輸入輸出編碼（配合上面，固定 utf-8）",
}
ENV_READONLY = {"PYTHONUTF8", "PYTHONIOENCODING"}  # 固定值：視窗只顯示不給改
MCP_DESC = {  # 視窗 MCP 列的功能說明（一句話）
    "parallel": "一般網頁搜尋＋抓頁，台灣在地事實的起手式；一次可下多個查詢",
    "exa": "語意搜尋：用「描述想找的頁面」找，另有論文／公司索引；與 parallel 互補",
    "context7": "程式庫官方文件（寫程式查 API 現況、版本差異）",
    "deepwiki": "任何公開 GitHub repo 的自動文件，可直接問「這個 repo 的 X 怎麼運作」",
    "mslearn": "微軟官方文件（Windows、PowerShell、.NET、Azure、Office）",
    "tavily": "搜尋＋去廣告的乾淨擷取；有金鑰多整站爬",
    "firecrawl": "會執行 JavaScript 的網頁抓取，動態頁面抓不到時的第三步",
}
TOOL_DESC = {  # 其他功能說明
    "core": "規則（查證格式、上網查資料分流、派工原則）合併進全域 CLAUDE.md；10 個 skill（派工、安全重構、文件治理、回饋稽核、波及範圍、專案驗證生成、接手、新專案立規矩、舊專案盤點、分階段重整）",
    "usage_guard": "每次對話與工具後讀用量，到門檻才注入「收尾」提醒；沒到完全不動",
    "task_check": "有背景任務時每 N 分鐘用 CronCreate 醒來檢查，全部結束就刪排程",
    "project_auto": "第一次進一個專案：沒有 CLAUDE.md 就自動立規矩（cds-project-init），沒有盤點索引就自動盤點（cds-project-audit），達門檻只問一次要不要分階段重整（cds-modularize）；小腳本資料夾不做",
    "video": "video.py：搜影片、字幕／語音辨識逐字稿、場景截圖、直播錄一段、觀看數留言、Gemini 看畫面、最高畫質下載",
    "chrome": "Claude in Chrome：實際開網頁看、操作需登入網站、測自己的網站、教你操作前先核對畫面",
}
CHROME_EXT_ID = "fcoeoabgfenejglbffodgkkbkcdhcgfn"
NATIVE_HOST_KEY = r"Software\Google\Chrome\NativeMessagingHosts\com.anthropic.claude_browser_extension"
DEFAULT_THRESHOLDS = {"fiveHour": 85, "sevenDay": 97}


# ---------- 狀態 ----------

@dataclass
class EnvItem:
    ok: bool | None  # True 可用、False 缺、None 警告／無法判定
    detail: str
    action: str | None = None  # 可執行的安裝動作代號（gui 顯示按鈕）：ffmpeg、pwsh7、python、claude、faster_whisper


def _pwsh_status(which=shutil.which, run=subprocess.run) -> EnvItem:
    exe = which("pwsh")
    msi = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PowerShell" / "7" / "pwsh.exe"
    if not exe and msi.exists():
        exe = str(msi)
    if not exe:
        return EnvItem(None if sys.platform != "win32" else False, "未裝 PowerShell 7（Windows 建議裝 MSI 版，Claude Code 會自動改用）", "pwsh7")
    try:
        r = run([exe, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"], capture_output=True, text=True, timeout=20)
        ver = (r.stdout or "").strip() or "?"
    except Exception:  # noqa: BLE001
        ver = "?"
    note = "" if (sys.platform != "win32" or msi.exists()) else "（非 MSI 路徑，Claude Code 可能偵測不到，建議改裝 MSI 版）"
    return EnvItem(True if (sys.platform != "win32" or msi.exists()) else None, f"PowerShell {ver}{note}", None if msi.exists() else "pwsh7")


def find_system_python(which=shutil.which, run=subprocess.run) -> tuple[str | None, tuple[int, ...] | None]:
    """exe 模式用：找系統的 Python（py 啟動器優先，再 python3／python），回 (執行檔完整路徑, 版本)。沒有回 (None, None)。"""
    for cand in ("py", "python3", "python"):
        exe = which(cand)
        if not exe:
            continue
        args = [exe, "-3"] if cand == "py" else [exe]
        try:
            r = run(args + ["-c", "import sys;print(sys.executable);print('.'.join(map(str,sys.version_info[:3])))"], capture_output=True, timeout=15)
            lines = (r.stdout or b"").decode("utf-8", "replace").split()
            if r.returncode == 0 and len(lines) >= 2 and "WindowsApps" not in lines[0]:  # 商店的假 python.exe 排除
                return Path(lines[0]).as_posix(), parse_ver(lines[1])
        except Exception:  # noqa: BLE001
            continue
    return None, None


def system_importer(python: str | None):
    """exe 模式用的 importer：在系統 Python 裡 import 模組拿版本（exe 內建的 Python 沒裝 yt-dlp／faster-whisper，直接 import 會誤報未裝）。"""
    if not python:
        return lambda mod: None

    def imp(mod: str):
        code = ("import importlib,sys\n"
                "try:\n m=importlib.import_module(sys.argv[1])\nexcept Exception:\n sys.exit(3)\n"
                "v=getattr(m,'__version__',None)\n"
                "if v is None and sys.argv[1]=='yt_dlp':\n"
                " v=getattr(getattr(m,'version',None),'__version__',None)\n"
                "print(v or '')")
        try:
            r = subprocess.run([python, "-c", code, mod], capture_output=True, timeout=60)
        except Exception:  # noqa: BLE001
            return None
        return (r.stdout or b"").decode("utf-8", "replace").strip() if r.returncode == 0 else None
    return imp


def env_status(repo: Path = REPO, which=shutil.which, importer=video.default_importer, ffmpeg=video.ffmpeg_path,
               claude_status=claude_code_status, run=subprocess.run, python: str | None = None) -> dict[str, EnvItem]:
    out: dict[str, EnvItem] = {}
    if python and Path(python).resolve() != Path(sys.executable).resolve():  # exe 模式：顯示系統 Python，不是 exe 內建的
        _, pv3 = find_system_python(which, run)
        pv = pv3 or (0, 0, 0)
        out["python"] = EnvItem(pv >= (3, 10), f"Python {'.'.join(map(str, pv))}（{python}）" if pv3 else f"Python（{python}）版本讀不到", None if pv >= (3, 10) else "python")
    elif python is None and FROZEN:
        out["python"] = EnvItem(False, "找不到系統的 Python ≥3.10（hook 與影片工具需要；執行檔本身不能代替）", "python")
    else:
        pv = sys.version_info
        out["python"] = EnvItem(pv >= (3, 10), f"Python {pv.major}.{pv.minor}.{pv.micro}（{Path(sys.executable).as_posix()}）", None if pv >= (3, 10) else "python")
    ok, msg = claude_status(repo)
    out["claude"] = EnvItem(ok, msg, None if ok else "claude")
    ff = ffmpeg()
    out["ffmpeg"] = EnvItem(bool(ff), (f"ffmpeg 可用（{Path(ff).parent.name}／{Path(ff).parent.parent.name}）" if ff else "未裝（影片截圖與語音辨識需要）"), None if ff else "ffmpeg")  # 全路徑太長會撐出視窗，只顯示最後兩層
    out["pwsh"] = _pwsh_status(which, run)
    out["winget"] = EnvItem(bool(which("winget")), "winget 可用" if which("winget") else "無 winget（安裝按鈕不可用，請手動裝）")
    out["git"] = EnvItem(True if which("git") else None, "git 可用" if which("git") else "無 git（exe 模式不需要）")
    out["node"] = EnvItem(True if which("node") else None, "node 可用（YouTube 解挑戰用）" if which("node") else "無 node／deno（YouTube 高畫質可能缺、下載較慢）")
    fw = importer("faster_whisper")
    out["faster_whisper"] = EnvItem(True if fw is not None else None, f"faster-whisper {fw}" if fw is not None else "未裝（沒字幕的影片無法轉逐字稿）", None if fw is not None else "faster_whisper")
    return out


def chrome_extension_installed(local_appdata: str | None = None) -> bool:
    base = Path(local_appdata or os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    if not base.exists():
        return False
    return bool(glob.glob(str(base / "*" / "Extensions" / CHROME_EXT_ID)))


def chrome_native_host_registered() -> bool | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NATIVE_HOST_KEY):
            return True
    except OSError:
        return False


def chrome_default_enabled(lay: Layout) -> bool | None:
    p = web.user_config_path(lay)
    if not p.exists():
        return None
    try:
        v = read_json(p).get("claudeInChromeDefaultEnabled")
        return bool(v) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


def set_chrome_default_enabled(lay: Layout, enabled: bool) -> str:
    """寫 ~/.claude.json 的單一鍵（先備份到 backups/）。這是本工具唯一直接寫該檔的地方。"""
    p = web.user_config_path(lay)
    data = read_json(p) if p.exists() else {}
    lay.backups.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bk = lay.backups / f"claude-json-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        shutil.copy2(p, bk)
        olds = sorted(lay.backups.glob("claude-json-*.json"))
        for stale in olds[:-10]:  # 與 settings.json 備份一樣只留最近 10 份
            stale.unlink(missing_ok=True)
    data["claudeInChromeDefaultEnabled"] = bool(enabled)
    try:
        write_json(p, data)
    except OSError as e:
        raise OSError(f"寫 {p} 失敗（Claude Code 可能正在用這個檔，關掉對話再試）：{e}") from None
    return str(p)


def read_thresholds(lay: Layout) -> dict:
    p = lay.payload / "config" / "dispatch-config.json"
    try:
        d = read_json(p)
    except Exception:  # noqa: BLE001
        return dict(DEFAULT_THRESHOLDS)
    t = d.get("usageThresholdPct") or {}
    if isinstance(t.get("fiveHour"), (int, float)) and isinstance(t.get("sevenDay"), (int, float)):
        return {"fiveHour": t["fiveHour"], "sevenDay": t["sevenDay"]}
    plan = d.get("plan") or {}
    cur = (plan.get("current") if isinstance(plan, dict) else None)
    if cur and isinstance(t.get(cur), dict):
        return {"fiveHour": t[cur].get("fiveHour", DEFAULT_THRESHOLDS["fiveHour"]), "sevenDay": t[cur].get("sevenDay", DEFAULT_THRESHOLDS["sevenDay"])}
    return dict(DEFAULT_THRESHOLDS)


DEFAULT_TASK_CHECK = {"enabled": True, "minutes": 15}
DEFAULT_PROJECT_AUTO = {"autoInit": True, "autoAudit": True, "autoRefactor": False, "minSourceFiles": 10}


def read_project_auto(lay: Layout) -> dict:
    p = lay.payload / "config" / "dispatch-config.json"
    out = dict(DEFAULT_PROJECT_AUTO)
    try:
        t = read_json(p).get("projectAutomation") or {}
    except Exception:  # noqa: BLE001
        return out
    for k in ("autoInit", "autoAudit", "autoRefactor"):
        if isinstance(t.get(k), bool):
            out[k] = t[k]
    if isinstance(t.get("minSourceFiles"), (int, float)) and t["minSourceFiles"] >= 1:
        out["minSourceFiles"] = int(t["minSourceFiles"])
    return out


def write_project_auto(lay: Layout, auto: dict) -> None:
    p = lay.payload / "config" / "dispatch-config.json"
    d = read_json(p) if p.exists() else {}
    t = d.get("projectAutomation") if isinstance(d.get("projectAutomation"), dict) else {}
    desc = t.get("$說明") or "專案自動化：autoInit 新專案自動立規矩；autoAudit 舊專案自動盤點；autoRefactor 達門檻不問直接重整；minSourceFiles 小於此數且非 git 就不當專案。"
    d["projectAutomation"] = {"$說明": desc, "autoInit": bool(auto.get("autoInit", True)), "autoAudit": bool(auto.get("autoAudit", True)),
                              "autoRefactor": bool(auto.get("autoRefactor", False)), "minSourceFiles": int(auto.get("minSourceFiles", 10))}
    d["updated"] = _dt.date.today().isoformat()
    write_json(p, d)


def read_task_check(lay: Layout) -> dict:
    p = lay.payload / "config" / "dispatch-config.json"
    try:
        t = read_json(p).get("taskCheck") or {}
    except Exception:  # noqa: BLE001
        return dict(DEFAULT_TASK_CHECK)
    out = dict(DEFAULT_TASK_CHECK)
    if isinstance(t.get("enabled"), bool):
        out["enabled"] = t["enabled"]
    if isinstance(t.get("minutes"), (int, float)) and t["minutes"] > 0:
        out["minutes"] = int(t["minutes"])
    return out


def write_task_check(lay: Layout, enabled: bool, minutes: int) -> None:
    p = lay.payload / "config" / "dispatch-config.json"
    d = read_json(p) if p.exists() else {}
    t = d.get("taskCheck") if isinstance(d.get("taskCheck"), dict) else {}
    desc = t.get("$說明") or "背景任務巡檢：有背景任務時每 minutes 分鐘用 CronCreate 醒來檢查，全部結束後刪除排程；enabled=false 完全不做。"
    d["taskCheck"] = {"$說明": desc, "enabled": bool(enabled), "minutes": int(minutes)}
    d["updated"] = _dt.date.today().isoformat()
    write_json(p, d)


def write_thresholds(lay: Layout, five: float, seven: float) -> None:
    """只改 usageThresholdPct 的兩個數字（扁平格式），其餘鍵保留；舊 plan 格式一併扁平化。"""
    p = lay.payload / "config" / "dispatch-config.json"
    d = read_json(p) if p.exists() else {}
    t = d.get("usageThresholdPct") if isinstance(d.get("usageThresholdPct"), dict) else {}
    desc = t.get("$說明") or "觸發收尾的門檻（%）：5 小時用量 >= fiveHour 或 7 天用量 >= sevenDay。沒到就什麼都不做。"
    d["usageThresholdPct"] = {"$說明": desc, "fiveHour": five, "sevenDay": seven}
    d.pop("plan", None)
    d["updated"] = _dt.date.today().isoformat()
    write_json(p, d)


def _local_time(iso: str | None) -> str:
    """hook 寫的重置時間是 UTC ISO；畫面顯示本地時間 月/日 時:分。"""
    if not iso:
        return "？"
    try:
        return _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().strftime("%m/%d %H:%M")
    except Exception:  # noqa: BLE001
        return str(iso)[:16]


def read_usage(lay: Layout) -> dict:
    """讀用量守門 hook 寫的 <home>/state/usage.json（只有百分比與重置時間，沒有權杖）。沒有檔就回 text 說明。"""
    p = lay.home / "state" / "usage.json"
    try:
        d = read_json(p)
    except Exception:  # noqa: BLE001
        return {"five": None, "seven": None, "text": "尚無用量資料（用量守門 hook 跑過一次對話後才有；或按「重新讀取用量」）"}
    five, seven = d.get("five_hour_pct"), d.get("seven_day_pct")
    fmt = lambda v: f"{v:.0f}%" if isinstance(v, (int, float)) else "？"  # noqa: E731
    text = (f"目前用量：5 小時 {fmt(five)}（重置 {_local_time(d.get('five_hour_resets_at'))}）；"
            f"7 天 {fmt(seven)}（重置 {_local_time(d.get('seven_day_resets_at'))}）；讀於 {str(d.get('updated_at') or '？')[:16].replace('T', ' ')}")
    return {"five": five, "seven": seven, "five_reset": d.get("five_hour_resets_at"), "seven_reset": d.get("seven_day_resets_at"),
            "updated_at": d.get("updated_at"), "text": text}


def refresh_usage(lay: Layout, python: str, run=subprocess.run) -> dict:
    """主動打一次用量端點（跑已安裝的 hooks/usage_guard.py --print），再讀 usage.json。失敗時 text 說明原因。"""
    script = lay.payload / "hooks" / "usage_guard.py"
    if not script.exists():
        return {**read_usage(lay), "text": "尚未安裝核心（hooks/usage_guard.py 不存在），無法讀用量"}
    try:
        r = run([python, str(script), "--print"], capture_output=True, timeout=30, env={**os.environ, "CLAUDE_CONFIG_DIR": str(lay.home), "PYTHONUTF8": "1"})
        out = (r.stdout or b"").decode("utf-8", "replace").strip()
    except Exception as e:  # noqa: BLE001
        return {**read_usage(lay), "text": f"讀用量失敗：{type(e).__name__}"}
    u = read_usage(lay)
    if not out:
        u["text"] = u["text"] + "（這次沒拿到新資料：沒有登入憑證或端點改版）"
    return u


def read_state(lay: Layout, repo: Path = REPO, env=env_status, importer=video.default_importer, ffmpeg=video.ffmpeg_path,
               python: str | None = None) -> dict:
    """畫面的唯一真相來源。python：exe 模式傳系統 Python 路徑（None＝找不到）。"""
    m = mf.load(lay.manifest)
    src = web.sources(lay) if (lay.payload / web.SOURCES_REL).exists() else read_json(repo / "config" / "web-sources.json")
    try:
        local = web.load_local(lay)
    except ValueError:
        local = {"keys": {}, "enable": [], "disable": [], "env": {}}
    have = web.installed_servers(lay)
    settings = read_json(lay.settings) if lay.settings.exists() else {}
    env_vals = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    want = web.desired_servers(src, local) if (m and (m.get("web") or {}).get("enabled")) else {}
    servers = {}
    for name, spec in (src.get("mcpServers") or {}).items():
        on = bool(spec.get("default"))
        if name in local.get("enable", []):
            on = True
        if name in local.get("disable", []):
            on = False
        servers[name] = {"default": bool(spec.get("default")), "wanted": on, "registered": name in have,
                         "key_registered": (name + "-key") in have, "keyable": bool(spec.get("keyParam") or spec.get("keyHeader")),
                         "tools": spec.get("tools") or [], "note": spec.get("note", "")}
    keys = {}
    for name, (label, kind, note, url) in KEY_INFO.items():
        val = (local.get("keys") or {}).get(name) or ""
        keys[name] = {"label": label, "kind": kind, "note": note, "url": url, "present": bool(val), "value": val,  # value 只給畫面輸入框用，不可寫進紀錄
                      "mode": web.key_mode(local, name) if kind == "search" else None,
                      "account": str((local.get("keyNotes") or {}).get(name) or "")}  # 使用者自填：這把金鑰是哪個帳號申請的
    vcfg = {}
    vp = lay.payload / "config" / "video.json"
    if vp.exists():
        try:
            vcfg = read_json(vp)
        except Exception:  # noqa: BLE001
            vcfg = {}
    return {
        "installed": bool(m),
        "version": m.get("version") if m else None,
        "repo_version": repo_version(repo),
        "env": env(repo, importer=importer, ffmpeg=ffmpeg, python=python) if python is not None or FROZEN else env(repo, importer=importer, ffmpeg=ffmpeg),
        "web": {"enabled": bool(m and (m.get("web") or {}).get("enabled")), "servers": servers, "desired_now": sorted(want),
                "env": {k: str(env_vals.get(k)) if env_vals.get(k) is not None else None for k in (src.get("env") or {}) if not k.startswith("_")},
                "env_defaults": {k: str(v) for k, v in (src.get("env") or {}).items() if not k.startswith("_")},
                "env_override": {k: str(v) for k, v in (local.get("env") or {}).items()}},
        "video": {"enabled": bool(m and (m.get("video") or {}).get("enabled")),
                  "packages": {mod: importer(mod) for mod in video.IMPORTS},
                  "download_dir": ((local.get("video") or {}).get("downloadDir") or vcfg.get("downloadDir") or "")},
        "keys": keys,
        "usage": read_usage(lay),
        "thresholds": read_thresholds(lay) if m else dict(DEFAULT_THRESHOLDS),
        "task_check": read_task_check(lay) if m else dict(DEFAULT_TASK_CHECK),
        "project_auto": read_project_auto(lay) if m else dict(DEFAULT_PROJECT_AUTO),
        "chrome": {"extension": chrome_extension_installed(), "native_host": chrome_native_host_registered(),
                   "default_enabled": chrome_default_enabled(lay)},
        "hooks": {"usage_guard": bool(m and (m.get("settings") or {}).get("hooksAdded")),
                  "usage_guard_pref": bool(local.get("usageGuard", True))},
    }


# ---------- 表單與差異 ----------

@dataclass
class Form:
    web_enabled: bool = False
    servers: dict = field(default_factory=dict)        # name -> bool（想要開）
    env: dict = field(default_factory=dict)            # KEY -> str
    video_enabled: bool = False
    keys: dict = field(default_factory=dict)           # name -> None（不變）| ""（清掉）| "值"
    key_modes: dict = field(default_factory=dict)      # name -> fallback|always
    key_notes: dict = field(default_factory=dict)      # name -> None（不變）| "帳號備註"（""＝清除）
    thresholds: dict = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    download_dir: str = ""
    chrome_default_enabled: bool | None = None
    usage_guard: bool = True
    task_check: dict = field(default_factory=lambda: dict(DEFAULT_TASK_CHECK))
    project_auto: dict = field(default_factory=lambda: dict(DEFAULT_PROJECT_AUTO))


def form_from_state(state: dict) -> Form:
    f = Form()
    f.usage_guard = state["hooks"]["usage_guard_pref"]
    f.task_check = dict(state.get("task_check") or DEFAULT_TASK_CHECK)
    f.project_auto = dict(state.get("project_auto") or DEFAULT_PROJECT_AUTO)
    f.web_enabled = state["web"]["enabled"]
    f.servers = {n: s["wanted"] for n, s in state["web"]["servers"].items()}
    f.env = {k: (state["web"]["env_override"].get(k) or state["web"]["env"].get(k) or state["web"]["env_defaults"].get(k) or "")
             for k in state["web"]["env_defaults"]}
    f.video_enabled = state["video"]["enabled"]
    f.keys = {n: None for n in state["keys"]}
    f.key_modes = {n: k["mode"] for n, k in state["keys"].items() if k["mode"]}
    f.key_notes = {n: None for n in state["keys"]}
    f.thresholds = dict(state["thresholds"])
    f.download_dir = state["video"]["download_dir"]
    f.chrome_default_enabled = state["chrome"]["default_enabled"]
    return f


def preset(form: Form, state: dict, on: bool) -> Form:
    """全部啟用／全部關閉：只動開關，不動金鑰與數值。"""
    f = copy.deepcopy(form)
    f.web_enabled = on
    f.servers = {n: on for n in state["web"]["servers"]}
    f.video_enabled = on
    f.usage_guard = on
    if on and state["chrome"]["default_enabled"] is not None:
        f.chrome_default_enabled = True
    if not on:
        f.chrome_default_enabled = False if state["chrome"]["default_enabled"] is not None else None
    return f


@dataclass
class Change:
    kind: str      # install|update|web|video|keys|env|thresholds|download_dir|chrome
    text: str


def source_older(state: dict) -> bool:
    """來源 repo（原始碼、exe 內建或 app/）的版本比已安裝的舊（例如用舊 exe 開已從原始碼更新過的機器）。"""
    if not state.get("installed"):
        return False
    a, b = parse_ver(state["repo_version"]), parse_ver(state["version"] or "0")
    return bool(a and b and a < b)


def diff(state: dict, form: Form) -> list[Change]:
    ch: list[Change] = []
    if not state["installed"]:
        ch.append(Change("install", "安裝核心（規則、skill、用量守門）"))
    elif source_older(state):
        pass  # exe 內建或 app/ 比已安裝舊：不提「更新」（安裝器會拒絕降版）；視窗另外顯示提醒，其他設定仍可套用
    elif parse_ver(state["repo_version"]) != parse_ver(state["version"] or "0"):
        ch.append(Change("update", f"更新 {state['version']} → {state['repo_version']}"))
    if form.usage_guard != state["hooks"]["usage_guard_pref"]:
        ch.append(Change("guard", "啟用用量守門 hook" if form.usage_guard else "關閉用量守門 hook（移除 settings.json 的兩條 hook；規則仍在）"))
    if form.web_enabled != state["web"]["enabled"]:
        ch.append(Change("web", "啟用聯網來源" if form.web_enabled else "關閉聯網來源（移除本工具註冊的 MCP 與 env）"))
    if form.web_enabled:
        for n, s in state["web"]["servers"].items():
            if form.servers.get(n, s["wanted"]) != s["wanted"]:
                ch.append(Change("web", f"{'開啟' if form.servers[n] else '關閉'} MCP {n}"))
        for k, v in form.env.items():
            cur = state["web"]["env_override"].get(k) or state["web"]["env"].get(k) or state["web"]["env_defaults"].get(k) or ""
            v = str(v).strip() or str(state["web"]["env_defaults"].get(k, ""))  # 清空＝還原預設（原本會變成永遠套不掉的假變更）
            if v != str(cur):
                ch.append(Change("env", f"{k}：{cur} → {v}"))
    if form.video_enabled != state["video"]["enabled"]:
        ch.append(Change("video", "啟用影片來源（pip 裝 yt-dlp 等）" if form.video_enabled else "關閉影片來源（取消登記，不解除安裝套件）"))
    for n, v in form.keys.items():
        if v is None:
            continue
        had = state["keys"][n]["present"]
        if v == "" and had:
            ch.append(Change("keys", f"清除金鑰 {state['keys'][n]['label']}"))
        elif v:
            ch.append(Change("keys", f"{'更新' if had else '新增'}金鑰 {state['keys'][n]['label']}"))
    for n, m in form.key_modes.items():
        if state["keys"].get(n, {}).get("mode") and m != state["keys"][n]["mode"]:
            ch.append(Change("keys", f"{state['keys'][n]['label']} 金鑰模式 → {dict(fallback='免費優先', always='一律用金鑰', free='只用免金鑰').get(m, m)}"))
    for n, v in form.key_notes.items():
        if v is not None and n in state["keys"] and str(v).strip() != state["keys"][n].get("account", ""):
            ch.append(Change("keys", f"{state['keys'][n]['label']} 帳號備註 → {str(v).strip() or '（清除）'}"))
    for k in ("fiveHour", "sevenDay"):
        if float(form.thresholds.get(k, state["thresholds"][k])) != float(state["thresholds"][k]):
            ch.append(Change("thresholds", f"用量門檻 {'5 小時' if k == 'fiveHour' else '7 天'}：{state['thresholds'][k]}% → {form.thresholds[k]}%"))
    tc0 = state.get("task_check") or DEFAULT_TASK_CHECK
    if bool(form.task_check.get("enabled")) != bool(tc0["enabled"]) or int(form.task_check.get("minutes", tc0["minutes"])) != int(tc0["minutes"]):
        ch.append(Change("task_check", "背景任務巡檢 → " + (f"每 {int(form.task_check['minutes'])} 分鐘" if form.task_check.get("enabled") else "關閉")))
    pa0 = state.get("project_auto") or DEFAULT_PROJECT_AUTO
    pa_changed = [k for k in ("autoInit", "autoAudit", "autoRefactor", "minSourceFiles") if form.project_auto.get(k, pa0[k]) != pa0[k]]
    if pa_changed:
        lab = {"autoInit": "新專案自動立規矩", "autoAudit": "舊專案自動盤點", "autoRefactor": "達門檻不問直接重整", "minSourceFiles": "專案門檻（原始碼檔數）"}
        ch.append(Change("project_auto", "專案自動化 → " + "、".join(f"{lab[k]}={'開' if form.project_auto[k] is True else ('關' if form.project_auto[k] is False else form.project_auto[k])}" for k in pa_changed)))
    if (form.download_dir or "") != (state["video"]["download_dir"] or ""):
        ch.append(Change("download_dir", f"下載資料夾 → {form.download_dir or '~/Downloads（預設）'}"))
    if form.chrome_default_enabled is not None and form.chrome_default_enabled != state["chrome"]["default_enabled"]:
        ch.append(Change("chrome", f"Claude in Chrome 預設{'啟用' if form.chrome_default_enabled else '關閉'}"))
    return ch


# ---------- 套用 ----------

def apply_form(lay: Layout, python: str, state: dict, form: Form, log, repo: Path = REPO,
               runner=web.default_runner, pip=video.default_pip, force: bool = False) -> int:
    """依表單執行安裝器命令。順序：金鑰／開關／env／模式（先寫 local.json，不套用）→ install/update（含 web、video）→ 門檻 → 下載資料夾 → Chrome。
    回傳 0 成功、1 有 ❌、2 用法錯誤。log 是 callable(str)。"""
    changes = diff(state, form)
    if not changes:
        log("沒有變更。")
        return 0
    worst = 0

    def run(code, lines):
        nonlocal worst
        lines = list(lines)
        if code in (1, 2) and lines and not any(str(x).startswith(("❌", "⚠️")) for x in lines):
            lines[-1] = "❌ " + str(lines[-1])  # 安裝器的拒絕訊息（例如降版）沒有標記，補上讓人找得到
        for ln in lines:
            log(web.mask(ln, _local(lay)))
        worst = max(worst, code if code in (1, 2) else 0)

    keys = [f"{n}={v}" for n, v in form.keys.items() if v is not None]
    enable = [n for n, on in form.servers.items() if on and not state["web"]["servers"][n]["wanted"]]
    disable = [n for n, on in form.servers.items() if not on and state["web"]["servers"][n]["wanted"]]
    env_args = [f"{k}={v}" for k, v in form.env.items() if str(v).strip() not in ("", str(state["web"]["env_defaults"].get(k, "")))]
    env_reset = [k for k, v in form.env.items() if str(v).strip() in ("", str(state["web"]["env_defaults"].get(k, "")))]
    modes = [f"{n}={m}" for n, m in form.key_modes.items() if state["keys"].get(n, {}).get("mode") and m != state["keys"][n]["mode"]]
    # 0) 用量守門開關只是 local.json 的一個布林，apply 時 _sync_settings 會照它加／移除 hook
    if form.usage_guard != state["hooks"]["usage_guard_pref"]:
        local = _local(lay)
        local["usageGuard"] = bool(form.usage_guard)
        web.save_local(lay, local)
        log(f"用量守門 → {'開' if form.usage_guard else '關'}（local.json usageGuard）")
    notes = {n: str(v).strip() for n, v in form.key_notes.items() if v is not None and n in state["keys"] and str(v).strip() != state["keys"][n].get("account", "")}
    if notes:
        local = _local(lay)
        kn = local.get("keyNotes") if isinstance(local.get("keyNotes"), dict) else {}
        for n, v in notes.items():
            if v:
                kn[n] = v
            else:
                kn.pop(n, None)
        local["keyNotes"] = kn
        web.save_local(lay, local)
        log(f"金鑰帳號備註寫入 local.json：{'、'.join(notes)}")
    # 1) 先只寫 local.json（keys／enable／disable／env／keyMode），用 show=True 避免中途套用
    if keys or enable or disable or env_args or modes or env_reset:
        if not state["installed"]:
            _prewrite_local(lay, keys, enable, disable, env_args, env_reset, modes)
            log("本機偏好已先寫入 local.json")
        else:
            code, lines = commands.web_config(lay, keys=keys, enable=enable, disable=disable, env=env_args, show=True, runner=runner, key_mode=modes)
            _reset_env_override(lay, env_reset)
            run(code, [x for x in lines if x.startswith("本機偏好")])
    # 2) install／update（帶 web、video 開關）；來源比已安裝舊時不跑（安裝器會拒絕降版），改用 web／video 子命令直接套用
    if source_older(state) and not force:
        log(f"⚠️ 來源 v{state['repo_version']} 比已安裝的 v{state['version']} 舊，不更新規則與工具檔（按「檢查更新」下載最新版再套用）；其他設定照常套用")
        if form.web_enabled != state["web"]["enabled"] or keys or enable or disable or env_args or modes or env_reset:
            if form.web_enabled:
                code, lines = commands.web_config(lay, keys=[], runner=runner)  # 依 local.json 重新對齊 MCP 與 env
                run(code, lines)
            else:
                code, lines = commands.web_config(lay, off=True, runner=runner)
                run(code, lines)
        if form.video_enabled != state["video"]["enabled"]:
            code, lines = commands.video_config(lay, python, off=not form.video_enabled, pip=pip)
            run(code, lines)
    else:
        mode = "install" if not state["installed"] else "update"
        code, lines = commands.apply(lay, python, repo=repo, force=force, mode=mode, with_web=form.web_enabled, with_video=form.video_enabled,
                                     runner=runner, pip=pip)
        run(code, lines)
    # 3) 門檻、下載資料夾、Chrome
    if any(c.kind == "thresholds" for c in changes):
        write_thresholds(lay, float(form.thresholds["fiveHour"]), float(form.thresholds["sevenDay"]))
        log(f"用量門檻寫入 {form.thresholds['fiveHour']}／{form.thresholds['sevenDay']}")
    if any(c.kind == "task_check" for c in changes):
        write_task_check(lay, bool(form.task_check.get("enabled")), int(form.task_check.get("minutes", DEFAULT_TASK_CHECK["minutes"])))
        log(f"背景任務巡檢寫入：{'每 ' + str(int(form.task_check['minutes'])) + ' 分鐘' if form.task_check.get('enabled') else '關閉'}")
    if any(c.kind == "project_auto" for c in changes):
        write_project_auto(lay, form.project_auto)
        log(f"專案自動化寫入：{form.project_auto}")
    if any(c.kind == "download_dir" for c in changes):
        local = _local(lay)
        local.setdefault("video", {})["downloadDir"] = form.download_dir or ""
        web.save_local(lay, local)
        log(f"下載資料夾寫入 local.json：{form.download_dir or '（預設）'}")
    if any(c.kind == "chrome" for c in changes):
        p = set_chrome_default_enabled(lay, bool(form.chrome_default_enabled))
        log(f"Claude in Chrome 預設{'啟用' if form.chrome_default_enabled else '關閉'}（{p}，已備份）")
    return worst


def _local(lay: Layout) -> dict:
    try:
        return web.load_local(lay)
    except ValueError:
        return {"keys": {}, "enable": [], "disable": [], "env": {}}


def _prewrite_local(lay, keys, enable, disable, env_args, env_reset, modes):
    local = _local(lay)
    for kv in keys:
        web.set_key_arg(local, kv)
    for kv in env_args:
        web.set_env_arg(local, kv)
    for k in env_reset:
        (local.get("env") or {}).pop(k, None)
    for kv in modes:
        web.set_key_mode_arg(local, kv)
    for n in enable:
        local["enable"] = sorted(set(local.get("enable", [])) | {n})
        local["disable"] = [x for x in local.get("disable", []) if x != n]
    for n in disable:
        local["disable"] = sorted(set(local.get("disable", [])) | {n})
        local["enable"] = [x for x in local.get("enable", []) if x != n]
    web.save_local(lay, local)


def _reset_env_override(lay: Layout, keys: list[str]) -> None:
    if not keys:
        return
    local = _local(lay)
    env = local.get("env") or {}
    changed = False
    for k in keys:
        if k in env:
            del env[k]
            changed = True
    if changed:
        web.save_local(lay, local)


# ---------- 金鑰測試 ----------

def _ssl_context():
    """台灣政府站（氣象署、環境部）的 TWCA 根憑證缺 Subject Key Identifier，Python 3.13+ 預設 VERIFY_X509_STRICT 會拒絕；
    只清該旗標、不關驗證（規則 2b 節的正確修法）。"""
    import ssl
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return ctx


def _http(url: str, headers: dict | None = None, data: bytes | None = None, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            return r.status, r.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def test_key(name: str, value: str, all_keys: dict | None = None, http=_http) -> tuple[bool, str]:
    """各打一次最便宜的呼叫。回 (有效?, 一句說明)。金鑰值不出現在回傳字串。"""
    k = (value or "").strip()
    if not k:
        return False, "空白"
    all_keys = all_keys or {}
    try:
        if name == "cwa":
            s, b = http(f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization={urllib.parse.quote(k)}&limit=1")
            return (s == 200 and '"success":"true"' in b.replace(" ", "")), f"HTTP {s}"
        if name == "moenv":
            s, b = http(f"https://data.moenv.gov.tw/api/v2/aqx_p_432?api_key={urllib.parse.quote(k)}&limit=1&format=JSON")
            # 環境部：金鑰錯誤也回 200，內容是「該 API KEY 不存在或是已經到期。」；正確時是 JSON 陣列
            ok = s == 200 and b.lstrip().startswith("[")
            return ok, f"HTTP {s}" + ("" if ok else "（" + b.strip()[:40] + "）")
        if name == "openaq":
            s, b = http("https://api.openaq.org/v3/locations?limit=1", {"X-API-Key": k})
            return s == 200, f"HTTP {s}"
        if name in ("tdx_id", "tdx_secret"):
            cid = k if name == "tdx_id" else all_keys.get("tdx_id", "")
            sec = k if name == "tdx_secret" else all_keys.get("tdx_secret", "")
            if not cid or not sec:
                return False, "tdx_id 與 tdx_secret 要一起填才能測"
            body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
            s, b = http("https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token",
                        {"Content-Type": "application/x-www-form-urlencoded"}, body)
            return (s == 200 and "access_token" in b), f"HTTP {s}"
        if name == "youtube":
            s, b = http(f"https://www.googleapis.com/youtube/v3/videos?part=id&id=jNQXAC9IVRw&key={urllib.parse.quote(k)}")
            return s == 200, f"HTTP {s}" + ("（配額用完或金鑰限制）" if s == 403 else "")
        if name == "gemini":
            s, b = http("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", {"x-goog-api-key": k})
            return s == 200, f"HTTP {s}"
        if name == "tavily":
            s, b = http("https://api.tavily.com/search", {"Content-Type": "application/json", "Authorization": f"Bearer {k}"},
                        json.dumps({"query": "test", "max_results": 1}).encode())
            return s == 200, f"HTTP {s}"
        if name == "exa":
            s, b = http("https://api.exa.ai/search", {"Content-Type": "application/json", "x-api-key": k},
                        json.dumps({"query": "test", "numResults": 1}).encode())
            return s == 200, f"HTTP {s}" + ("（額度用完）" if s == 402 else "")
        if name == "context7":
            s, b = http("https://context7.com/api/v2/libs/search?query=react", {"Authorization": f"Bearer {k}"})
            return s == 200, f"HTTP {s}"
        if name == "parallel":
            s, b = http("https://api.parallel.ai/v1beta/search", {"Content-Type": "application/json", "x-api-key": k},
                        json.dumps({"objective": "test", "search_queries": ["test"], "max_results": 1}).encode())
            return s == 200, f"HTTP {s}"
        if name == "firecrawl":
            s, b = http("https://api.firecrawl.dev/v2/team/credit-usage", {"Authorization": f"Bearer {k}"})
            return s == 200, f"HTTP {s}"
    except Exception as e:  # noqa: BLE001
        return False, f"測試失敗：{type(e).__name__}"
    return False, "沒有這種金鑰的測試"


# ---------- 安裝動作與 Chrome 連線測試 ----------

INSTALL_ACTIONS = {
    "ffmpeg": ["winget", "install", "--id", "Gyan.FFmpeg", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements"],
    "pwsh7": ["winget", "install", "--id", "Microsoft.PowerShell", "--source", "winget", "--installer-type", "wix", "--accept-package-agreements", "--accept-source-agreements"],
}
DOWNLOAD_PAGES = {"python": "https://www.python.org/downloads/", "claude": "https://code.claude.com/docs/en/setup"}


def install_action(action: str, python: str, gpu: bool = False, run=subprocess.run) -> tuple[int, str]:
    if action == "faster_whisper":
        pk = ["faster-whisper"] + (["nvidia-cublas-cu12", "nvidia-cudnn-cu12"] if gpu else [])
        cmd = [python, "-m", "pip", "install", "--upgrade", *pk]
    elif action in INSTALL_ACTIONS:
        cmd = INSTALL_ACTIONS[action]
    else:
        return 2, f"沒有這個安裝動作：{action}"
    try:
        r = run(cmd, capture_output=True, timeout=1800)
    except Exception as e:  # noqa: BLE001
        return 1, str(e)
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    return r.returncode, out[-1500:]


def chrome_live_test(run=subprocess.run, timeout: int = 150, which=shutil.which) -> tuple[bool, str]:
    """第三層：背景跑一次 claude -p --chrome 叫它開 example.com 讀標題。會用掉約一場對話開場的用量，只手動觸發。"""
    exe = which("claude")
    if not exe:
        return False, "找不到 claude 指令"
    # 不能用 about:blank：擴充功能會拒絕「browser-internal or unparseable URLs」（2026-11-01 使用者按視窗按鈕實測失敗），改開 example.com
    prompt = ("用 Claude in Chrome 開一個新分頁到 https://example.com ，用 get_page_text 或 read_page 確認頁面標題含 Example Domain，然後關掉這個分頁。"
              "成功只回答「CHROME_OK」，失敗回答「CHROME_FAIL: 原因」。不要做其他事。")
    allowed = ",".join(f"mcp__claude-in-chrome__{t}" for t in ("tabs_context_mcp", "tabs_create_mcp", "navigate", "get_page_text", "read_page", "find", "computer", "tabs_close_mcp"))
    try:
        r = run([exe, "-p", prompt, "--chrome", "--max-turns", "8", "--output-format", "json", "--no-session-persistence", "--allowedTools", allowed],
                capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{timeout} 秒內沒有結果（Chrome 可能沒開或擴充未連線）"
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    raw = (r.stdout or b"").decode("utf-8", "replace")
    try:
        d = json.loads(raw)
        res = (d.get("result") or "").strip()
        cost = d.get("total_cost_usd")
        return res.startswith("CHROME_OK"), res[:200] + (f"（用量約 ${cost:.2f} 等值）" if isinstance(cost, (int, float)) else "")
    except Exception:  # noqa: BLE001
        return False, raw[-300:] or (r.stderr or b"").decode("utf-8", "replace")[-300:]


# ---------- 匯出／匯入、備份 ----------

def export_profile(state: dict, form: Form, include_keys: bool = False, current_keys: dict | None = None) -> dict:
    """開關、env、模式、門檻、下載資料夾、用量守門、Chrome 預設、金鑰帳號備註；include_keys=True 時另附金鑰明文（給搬到新裝置用，檔案要妥善保管）。
    不含環境安裝（ffmpeg、PowerShell 7、faster-whisper 是裝在系統裡的，匯入後在新裝置按安裝鈕）。"""
    d = {"claude-dev-system-profile": 1, "web_enabled": form.web_enabled, "servers": dict(form.servers), "env": dict(form.env),
         "video_enabled": form.video_enabled, "key_modes": dict(form.key_modes), "thresholds": dict(form.thresholds),
         "download_dir": form.download_dir, "chrome_default_enabled": form.chrome_default_enabled, "usage_guard": form.usage_guard,
         "task_check": dict(form.task_check), "project_auto": dict(form.project_auto),
         "key_notes": {n: (form.key_notes.get(n) if form.key_notes.get(n) is not None else k.get("account", "")) for n, k in state["keys"].items()
                       if (form.key_notes.get(n) if form.key_notes.get(n) is not None else k.get("account", ""))}}
    if include_keys:
        keys = dict(current_keys or {})
        for n, v in form.keys.items():  # 表單裡尚未套用的新值優先
            if v is not None:
                keys[n] = v
        d["keys"] = {n: v for n, v in keys.items() if v}
        d["_warning"] = "此檔含金鑰明文，請勿分享或放進 repo"
    return d


def import_profile(form: Form, data: dict) -> Form:
    if data.get("claude-dev-system-profile") != 1:
        raise ValueError("不是本工具的設定檔（缺 claude-dev-system-profile: 1）")
    f = copy.deepcopy(form)
    th = data.get("thresholds")
    if isinstance(th, dict):
        for k in ("fiveHour", "sevenDay"):
            if k in th and not (isinstance(th[k], (int, float)) and 1 <= float(th[k]) <= 100):
                raise ValueError(f"設定檔的門檻 {k} 不是 1～100 的數字：{th[k]!r}")
    tc = data.get("task_check")
    if isinstance(tc, dict) and "minutes" in tc and not (isinstance(tc["minutes"], (int, float)) and tc["minutes"] >= 1):
        raise ValueError(f"設定檔的巡檢分鐘數不合法：{tc['minutes']!r}")
    for k in ("web_enabled", "video_enabled", "usage_guard"):
        if k in data and not isinstance(data[k], bool):
            raise ValueError(f"設定檔的 {k} 必須是 true／false")
    if "download_dir" in data and not isinstance(data["download_dir"], str):
        raise ValueError("設定檔的 download_dir 必須是字串")
    for k in ("web_enabled", "video_enabled", "download_dir", "chrome_default_enabled", "usage_guard"):
        if k in data:
            setattr(f, k, data[k])
    for k in ("servers", "env", "key_modes", "thresholds", "task_check", "project_auto"):
        if isinstance(data.get(k), dict):
            vals = data[k]
            if k == "servers":
                vals = {n: bool(v) for n, v in vals.items() if n in f.servers}  # 別台機器才有的 MCP 名稱略過
            if k == "key_modes":
                vals = {n: v for n, v in vals.items() if n in KEY_INFO and v in web.KEY_MODES}
            getattr(f, k).update(vals)
    if isinstance(data.get("keys"), dict):
        for n, v in data["keys"].items():
            if n in KEY_INFO and isinstance(v, str) and v:
                f.keys[n] = v
    if isinstance(data.get("key_notes"), dict):
        for n, v in data["key_notes"].items():
            if n in KEY_INFO and isinstance(v, str):
                f.key_notes[n] = v
    return f


def list_backups(lay: Layout) -> list[tuple[str, str]]:
    m = mf.load(lay.manifest) or {}
    out = []
    for b in m.get("backups", []):
        if b.get("settings") and Path(b["settings"]).exists():
            out.append((b.get("at", "?"), b["settings"]))
    return out


def restore_backup(lay: Layout, path: str) -> str:
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(path)
    if lay.settings.exists():  # 還原也要有回頭路
        lay.backups.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lay.settings, lay.backups / f"claude-dev-system-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-before-restore.json")
    shutil.copy2(src, lay.settings)
    return str(lay.settings)
