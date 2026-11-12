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
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
# 0.14.2 更正：原本查 com.anthropic.claude_browser_extension，那是 Claude Desktop 的（這台的值指向 Claude_pzs8sxrjxfjjc\…\Claude-NativeHost）；
# Claude Code 的名稱見 code.claude.com/docs/en/chrome「com.anthropic.claude_code_browser_extension」
NATIVE_HOST_KEY = r"Software\Google\Chrome\NativeMessagingHosts\com.anthropic.claude_code_browser_extension"
DEFAULT_THRESHOLDS = {"fiveHour": 85, "sevenDay": 97}


# ---------- 狀態 ----------

@dataclass
class EnvItem:
    ok: bool | None  # True 可用、False 缺、None 警告／無法判定
    detail: str
    action: str | None = None  # 可執行的安裝動作代號（gui 顯示按鈕）：ffmpeg、pwsh7、python、claude、faster_whisper


def _pwsh_msi_location() -> str | None:
    """登錄檔解除安裝清單裡的 PowerShell 7 MSI 安裝位置（任何磁碟都認；2026-11-03 另一台裝在 D 槽被誤判成非 MSI，引導重裝同版 → MSI 1603）。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, base in roots:
        try:
            k = winreg.OpenKey(hive, base)
        except OSError:
            continue
        with k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sk:
                        name = str(winreg.QueryValueEx(sk, "DisplayName")[0])
                        if not name.startswith("PowerShell 7"):
                            continue
                        try:
                            loc = str(winreg.QueryValueEx(sk, "InstallLocation")[0])
                        except OSError:
                            loc = ""
                        return loc or name
                except OSError:
                    continue
    return None


def _pwsh_status(which=shutil.which, run=subprocess.run, msi_location=_pwsh_msi_location) -> EnvItem:
    exe = which("pwsh")
    msi = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PowerShell" / "7" / "pwsh.exe"
    if not exe and msi.exists():
        exe = str(msi)
    reg = msi_location()
    if not exe and reg:
        cand = Path(reg) / "pwsh.exe"
        if cand.exists():
            exe = str(cand)
    if not exe:
        return EnvItem(None if sys.platform != "win32" else False, "未裝 PowerShell 7（Windows 建議裝 MSI 版，Claude Code 會自動改用）", "pwsh7")
    try:
        r = run([exe, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"], capture_output=True, text=True, timeout=20)
        ver = (r.stdout or "").strip() or "?"
    except Exception:  # noqa: BLE001
        ver = "?"
    # Claude Code 偵測不到的是 Store／MSIX 版（路徑在 WindowsApps 底下的別名，issue #55041）；MSI 版裝在哪個磁碟都可以
    # （GU-12：原條件多一段 `(bool(reg) and not store)`，被後面的 `not store` 涵蓋，邏輯等價、拿掉）
    store = "windowsapps" in str(exe).lower()
    good = sys.platform != "win32" or msi.exists() or not store
    if good:
        where = "" if msi.exists() else f"（{Path(exe).parent}）"
        return EnvItem(True, f"PowerShell {ver}{where}", None)
    note = ("（Store 版，Claude Code 可能偵測不到：先在 Claude Code 對話用 PowerShell 工具跑 $PSVersionTable.PSVersion，"
            "顯示 7.x 就不用裝；顯示 5.1 才按右邊裝 MSI 版）")
    return EnvItem(None, f"PowerShell {ver}{note}", "pwsh7")


def find_system_python(which=shutil.which, run=subprocess.run, exists=os.path.isfile) -> tuple[str | None, tuple[int, ...] | None]:
    """exe 模式用：找系統的 Python（py 啟動器優先，再 python3／python），回 (執行檔完整路徑, 版本)。沒有回 (None, None)。
    GU-01（2026-11-12 健檢）：原本用 .split() 依空白切輸出，`C:\\Program Files\\...`、`C:\\Users\\John Smith\\...` 被截成 `C:/Program`，
    exe 模式所有 hook 被註冊成壞路徑。改成逐行解析；子程序強制 UTF-8 輸出（中文使用者名稱不經碼頁 950 亂碼）；路徑要真的存在才採用。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for cand in ("py", "python3", "python"):
        exe = which(cand)
        if not exe:
            continue
        args = [exe, "-3"] if cand == "py" else [exe]
        try:
            r = run(args + ["-c", "import sys;print(sys.executable);print('.'.join(map(str,sys.version_info[:3])))"], capture_output=True, timeout=15, env=env)
            lines = [x.strip() for x in (r.stdout or b"").decode("utf-8", "replace").splitlines() if x.strip()]
            if r.returncode == 0 and len(lines) >= 2 and "windowsapps" not in lines[0].lower() and exists(lines[0]):  # 商店的假 python.exe 排除
                return Path(lines[0]).as_posix(), parse_ver(lines[1])
        except Exception:  # noqa: BLE001
            continue
    return None, None


BATCH_MODS = ("faster_whisper",) + tuple(video.IMPORTS)  # 開窗要查的套件：一次開一個系統 Python 查完（原本每個套件一個程序，共 2.7 秒）
_BATCH_CODE = ("import importlib,json,sys\n"
               "out={}\n"
               "for m in sys.argv[1:]:\n"
               " try:\n  mod=importlib.import_module(m)\n except Exception:\n  out[m]=None\n  continue\n"
               " v=getattr(mod,'__version__',None)\n"
               " if v is None and m=='yt_dlp':\n  v=getattr(getattr(mod,'version',None),'__version__',None)\n"
               " out[m]=v or ''\n"
               "print(json.dumps(out))")


def system_importer(python: str | None, run=subprocess.run):
    """exe 模式用的 importer：在系統 Python 裡 import 模組拿版本（exe 內建的 Python 沒裝 yt-dlp／faster-whisper，直接 import 會誤報未裝）。
    第一次呼叫就把 BATCH_MODS 一次查完快取起來；多執行緒同時叫也只跑一個程序。"""
    if not python:
        return lambda mod: None
    cache: dict = {}
    lock = threading.Lock()

    def batch(mods):
        try:
            r = run([python, "-c", _BATCH_CODE, *mods], capture_output=True, timeout=90)
            txt = (r.stdout or b"").decode("utf-8", "replace").strip()
            if r.returncode != 0 or not txt:
                return {m: None for m in mods}
            got = json.loads(txt.splitlines()[-1])  # 套件 import 時可能先印東西，只取最後一行
            return {m: got.get(m) for m in mods}
        except Exception:  # noqa: BLE001
            return {m: None for m in mods}

    def imp(mod: str):
        with lock:
            if mod not in cache:
                cache.update(batch(BATCH_MODS if mod in BATCH_MODS else (mod,)))
            return cache.get(mod)
    return imp


def _registry_path_dirs() -> list[str]:
    """登錄檔裡現在的系統＋使用者 PATH（已展開 %VAR%）。非 Windows 回空。"""
    if sys.platform != "win32":
        return []
    import winreg
    out: list[str] = []
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"), (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, key) as k:
                out += winreg.ExpandEnvironmentStrings(str(winreg.QueryValueEx(k, "Path")[0])).split(os.pathsep)
        except OSError:
            continue
    return out


def refresh_path(environ=os.environ, reg_dirs=_registry_path_dirs) -> list[str]:
    """把登錄檔 PATH 新增的資料夾補進這個程序（原有順序不動），回補了哪些。
    程序的 PATH 是啟動時那份：視窗開著才裝的 Python、Claude Code、Deno 在關掉重開前都找不到（新裝置實測：faster-whisper 第一次失敗）。"""
    cur = [d for d in environ.get("PATH", "").split(os.pathsep) if d]
    have = {os.path.normcase(os.path.normpath(d)) for d in cur}
    added = []
    for d in reg_dirs():
        n = os.path.normcase(os.path.normpath(d)) if d else ""
        if n and n not in have:
            have.add(n)
            added.append(d)
    if added:
        environ["PATH"] = os.pathsep.join(cur + added)
    return added


def env_status(repo: Path = REPO, which=shutil.which, importer=video.default_importer, ffmpeg=video.ffmpeg_path,
               claude_status=claude_code_status, run=subprocess.run, python: str | None = None) -> dict[str, EnvItem]:
    out: dict[str, EnvItem] = {}
    # 會開子程序的檢查平行跑（2026-11-02 量測：依序 5.5 秒 → 平行約 1.5 秒，開窗等待的主因）
    sys_py = python and Path(python).resolve() != Path(sys.executable).resolve()
    with ThreadPoolExecutor(max_workers=5) as ex:
        f_py = ex.submit(find_system_python, which, run) if sys_py else None
        f_claude = ex.submit(claude_status, repo)
        f_pwsh = ex.submit(_pwsh_status, which, run)
        f_fw = ex.submit(importer, "faster_whisper")
        ff = ffmpeg()
        if sys_py:  # exe 模式：顯示系統 Python，不是 exe 內建的
            _, pv3 = f_py.result()
            pv = pv3 or (0, 0, 0)
            out["python"] = EnvItem(pv >= (3, 10), f"Python {'.'.join(map(str, pv))}（{python}）" if pv3 else f"Python（{python}）版本讀不到", None if pv >= (3, 10) else "python")
        elif python is None and FROZEN:
            out["python"] = EnvItem(False, "找不到系統的 Python ≥3.10（hook 與影片工具需要；執行檔本身不能代替）", "python")
        else:
            pv = sys.version_info
            out["python"] = EnvItem(pv >= (3, 10), f"Python {pv.major}.{pv.minor}.{pv.micro}（{Path(sys.executable).as_posix()}）", None if pv >= (3, 10) else "python")
        ok, msg = f_claude.result()
        out["claude"] = EnvItem(ok, msg, None if ok else "claude")
    out["ffmpeg"] = EnvItem(bool(ff), (f"ffmpeg 可用（{Path(ff).parent.name}／{Path(ff).parent.parent.name}）" if ff else "未裝（影片截圖與語音辨識需要）"), None if ff else "ffmpeg")  # 全路徑太長會撐出視窗，只顯示最後兩層
    out["pwsh"] = f_pwsh.result()
    out["winget"] = EnvItem(bool(which("winget")), "winget 可用" if which("winget") else "無 winget（安裝按鈕不可用，請手動裝）")
    out["git"] = EnvItem(True, "git 可用") if which("git") else EnvItem(None, "無 git（exe 模式不需要；Claude Code 在 Windows 用 Git Bash 跑指令）", "git")
    # 0.15.0 拆成兩列、各自有按鈕（使用者 11/4：「我覺得Deno與Node兩個都裝可以嗎?」）；版本門檻同一份 jsRuntimeMin
    mins = video.js_min()
    for name, label, use in (("deno", "Deno", "YouTube 解挑戰優先用它"), ("node", "Node.js", "YouTube 解挑戰的備援、其他專案常用")):
        v, low = video.runtime_version(name, which, run), mins.get(name, (0,))
        vs, ls = ".".join(map(str, v)) if v else "", ".".join(map(str, low))
        out[name] = (EnvItem(True, f"{label} {vs} 可用（{use}）") if v and v >= low
                     else EnvItem(None, (f"{label} {vs} 太舊（要 ≥{ls}）" if v else f"無 {label}") + f"（{use}）", name))
    fw = f_fw.result()
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
        return Path(winreg.QueryValue(winreg.HKEY_CURRENT_USER, NATIVE_HOST_KEY)).is_file()  # 機碼的值是設定檔路徑：檔案要真的在
    except OSError:
        return False


def chrome_default_enabled(lay: Layout) -> bool | None:
    """True／False＝可以勾；None＝檔案壞掉讀不到，不可寫。
    0.14.2：檔案在但還沒有這個鍵、或檔案還沒建立，都是「還沒開」＝False。原本回 None 把勾選框鎖住並顯示「找不到 ~/.claude.json」，
    只有先到 /chrome 開過才能勾（新裝置實測）。只含這個鍵的新檔，Claude Code 啟動後會保留它（CLAUDE_CONFIG_DIR 暫存目錄實測，11 個鍵、值仍 true）。"""
    p = web.user_config_path(lay)
    if not p.exists():
        return False
    try:
        return bool(read_json(p).get("claudeInChromeDefaultEnabled"))
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
# 0.16.0 重型工作記憶體門檻（使用者 2026-11-09：「先設固定 3GB就好……記憶體門檻要用成視窗可更改的」）。
# 唯一來源是 dispatch-config.json 的 resourceGate.minFreeMemGB；tools/resgate.py 讀同一個鍵。
DEFAULT_MEM_GB = 3.0
MEM_GB_RANGE = (1.0, 32.0)


def valid_mem_gb(v) -> float:
    """1～32 GB 的數字，否則 ValueError（視窗、匯入共用同一個檢查）。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"記憶體門檻要是數字：{v!r}") from None
    if isinstance(v, bool) or not (MEM_GB_RANGE[0] <= x <= MEM_GB_RANGE[1]):
        raise ValueError(f"記憶體門檻要在 {MEM_GB_RANGE[0]:g}～{MEM_GB_RANGE[1]:g} GB：{v!r}")
    return x


# GU-05（2026-11-12 健檢）：用量門檻原本視窗只 float()、匯入另有一份 1～100 檢查，0、-5、nan 都寫得進去（nan 寫出非法 JSON 的 NaN）。
# 數值欄位的檢查一律走下面這幾個函式：視窗表單（gui.py _collect）、匯入（import_profile）、套用（apply_form → validate_form）、寫檔（write_*）共用。
THRESHOLD_RANGE = (1.0, 100.0)
THRESHOLD_LABELS = {"fiveHour": "5 小時用量門檻", "sevenDay": "7 天用量門檻"}


def valid_threshold(v, label: str = "用量門檻") -> float:
    """1～100（%）的數字，否則 ValueError。nan、inf、布林都不算數字。"""
    if isinstance(v, bool):
        raise ValueError(f"{label}要是數字：{v!r}")
    try:
        x = float(str(v).strip()) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label}要是數字：{v!r}") from None
    if not (THRESHOLD_RANGE[0] <= x <= THRESHOLD_RANGE[1]):  # nan 比較一律 False，會落在這裡
        raise ValueError(f"{label}要在 {THRESHOLD_RANGE[0]:g}～{THRESHOLD_RANGE[1]:g}%：{v!r}")
    return x


def valid_task_minutes(v) -> int:
    """背景任務巡檢分鐘數：≥1 的整數，否則 ValueError（原本視窗 0 會被無聲改成 1、亂打字無聲退回舊值）。"""
    if isinstance(v, bool):
        raise ValueError(f"巡檢分鐘數要是整數：{v!r}")
    try:
        x = float(str(v).strip()) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        raise ValueError(f"巡檢分鐘數要是整數：{v!r}") from None
    if not (x >= 1) or not x.is_integer():  # nan、inf 的 is_integer() 都是 False
        raise ValueError(f"巡檢分鐘數要是 ≥1 的整數：{v!r}")
    return int(x)


def valid_pa_int(k: str, v) -> int:
    """專案自動化的數字欄位：整數、不小於 PA_INT_MIN（minSourceFiles ≥1，其餘 ≥0；0＝不檢查），否則 ValueError。"""
    label = PA_LABELS.get(k, k)
    if isinstance(v, bool):
        raise ValueError(f"{label}要是整數：{v!r}")
    try:
        x = float(str(v).strip()) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label}要是整數：{v!r}") from None
    lo = PA_INT_MIN.get(k, 0)
    if not (x >= lo) or not x.is_integer():
        raise ValueError(f"{label}要是 ≥{lo} 的整數：{v!r}")
    return int(x)


def _unchanged(a, b) -> bool:
    """表單值與目前狀態相同（nan 視為相同）：沒動過的欄位不檢查——使用者自己手改進設定檔的舊值（例如門檻 0.5）不該擋住不相關的套用／更新。"""
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return x == y or (x != x and y != y)


def validate_form(form: "Form", state: dict | None = None) -> None:
    """套用前整份表單的數值檢查；有一項不合格就 ValueError（訊息指出欄位），apply_form 會整個不動。
    給了 state 時，與目前狀態相同的欄位略過（只檢查這次要寫的值）。"""
    st = state or {}
    for k in ("fiveHour", "sevenDay"):
        v = form.thresholds.get(k)
        if not (state and _unchanged(v, (st.get("thresholds") or {}).get(k))):
            valid_threshold(v, THRESHOLD_LABELS[k])
    valid_task_minutes(form.task_check.get("minutes", DEFAULT_TASK_CHECK["minutes"]))
    valid_mem_gb(form.mem_gb)
    for k in PA_INT_KEYS:
        if k in form.project_auto:
            valid_pa_int(k, form.project_auto[k])


def read_mem_gate(lay: Layout) -> float:
    p = lay.payload / "config" / "dispatch-config.json"
    try:
        return valid_mem_gb((read_json(p).get("resourceGate") or {}).get("minFreeMemGB"))
    except Exception:  # noqa: BLE001
        return DEFAULT_MEM_GB


def write_mem_gate(lay: Layout, gb: float) -> None:
    """只改 resourceGate.minFreeMemGB，其餘鍵（waitMinutes、pollSeconds、說明）保留。"""
    gb = valid_mem_gb(gb)
    p = lay.payload / "config" / "dispatch-config.json"
    d = read_json(p) if p.exists() else {}
    t = d.get("resourceGate") if isinstance(d.get("resourceGate"), dict) else {}
    t = {"$說明": t.get("$說明") or "重型工作（回測、全套測試、build、影片轉逐字稿）開跑前可用實體記憶體門檻；不足等 waitMinutes 分鐘仍不足就不跑、登記延後清單（tools/resgate.py）。",
         **{k: v for k, v in t.items() if k != "$說明"}}
    t["minFreeMemGB"] = gb
    t.setdefault("waitMinutes", 10)
    t.setdefault("pollSeconds", 60)
    d["resourceGate"] = t
    d["updated"] = _dt.date.today().isoformat()
    write_json(p, d)
# projectAutomation 的開關與數字。預設值必須與 hooks/usage_guard.py 的 _pa_config 及 config/dispatch-config.json 相同
# （tests/test_gui_model.py 比對三處）。0.20.0 起健康檢查門檻也可在視窗改（使用者 2026-11-11：「好，補到設定視窗」）。
PA_BOOL_KEYS = ("autoInit", "autoAudit", "autoRefactor", "alignOnUpdate", "verifySkill")
PA_INT_KEYS = ("minSourceFiles", "staleFiles", "claudeMdMaxLines", "claudeMdMaxKB", "progressMaxLines", "progressMaxKB", "newSessionAfterCompactions")
DEFAULT_PROJECT_AUTO = {"autoInit": True, "autoAudit": True, "autoRefactor": False, "alignOnUpdate": True, "verifySkill": True,
                        "minSourceFiles": 10, "staleFiles": 20, "claudeMdMaxLines": 180, "claudeMdMaxKB": 20,
                        "progressMaxLines": 600, "progressMaxKB": 100, "newSessionAfterCompactions": 3}
PA_LABELS = {"autoInit": "新專案自動立規矩", "autoAudit": "舊專案自動盤點", "autoRefactor": "達門檻不問直接重整",
             "alignOnUpdate": "全域升版後提示專案對照", "verifySkill": "提醒建驗證 skill",
             "minSourceFiles": "專案門檻（原始碼檔數）", "staleFiles": "盤點過期（改過檔數）", "claudeMdMaxLines": "CLAUDE.md 行數上限",
             "claudeMdMaxKB": "CLAUDE.md KB 上限", "progressMaxLines": "交接紀錄行數上限", "progressMaxKB": "交接紀錄 KB 上限",
             "newSessionAfterCompactions": "壓縮幾次建議開新對話"}
PA_INT_MIN = {"minSourceFiles": 1}  # 其餘數字 0＝不檢查（hook 同規則）


def _pa_clean_int(k, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < PA_INT_MIN.get(k, 0):
        return None
    return int(v)


def read_project_auto(lay: Layout) -> dict:
    p = lay.payload / "config" / "dispatch-config.json"
    out = dict(DEFAULT_PROJECT_AUTO)
    try:
        t = read_json(p).get("projectAutomation") or {}
    except Exception:  # noqa: BLE001
        return out
    for k in PA_BOOL_KEYS:
        if isinstance(t.get(k), bool):
            out[k] = t[k]
    for k in PA_INT_KEYS:
        v = _pa_clean_int(k, t.get(k))
        if v is not None:
            out[k] = v
    return out


def write_project_auto(lay: Layout, auto: dict) -> None:
    """只改視窗管的鍵；bigFileExceptions、各鍵的 $說明 等其他內容保留（0.20.0 前會整段重寫、刪掉其他鍵）。"""
    p = lay.payload / "config" / "dispatch-config.json"
    d = read_json(p) if p.exists() else {}
    t = dict(d.get("projectAutomation")) if isinstance(d.get("projectAutomation"), dict) else {}
    t.setdefault("$說明", "專案自動化：autoInit 新專案自動立規矩；autoAudit 舊專案自動盤點；autoRefactor 達門檻不問直接重整；minSourceFiles 小於此數且非 git 就不當專案。")
    for k in PA_BOOL_KEYS:
        t[k] = bool(auto.get(k, DEFAULT_PROJECT_AUTO[k]))
    for k in PA_INT_KEYS:
        t[k] = valid_pa_int(k, auto.get(k, DEFAULT_PROJECT_AUTO[k]))  # GU-05：不合法就丟 ValueError（原本無聲換成預設值）
    d["projectAutomation"] = t
    d["updated"] = _dt.date.today().isoformat()
    write_json(p, d)


# 0.22.0 派工補充與交報告守門（hooks/usage_guard.py 的 _sub_cfg 讀同一個鍵，預設值要相同）
DEFAULT_SUB_BRIEF = {"enabled": True, "guard": True}


def read_sub_brief(lay: Layout) -> dict:
    out = dict(DEFAULT_SUB_BRIEF)
    try:
        t = read_json(lay.payload / "config" / "dispatch-config.json").get("subagentBrief") or {}
    except Exception:  # noqa: BLE001
        return out
    for k in out:
        if isinstance(t.get(k), bool):
            out[k] = t[k]
    return out


def write_sub_brief(lay: Layout, sb: dict) -> None:
    """只改 enabled／guard，$說明 等其他鍵保留。"""
    p = lay.payload / "config" / "dispatch-config.json"
    d = read_json(p) if p.exists() else {}
    t = dict(d.get("subagentBrief")) if isinstance(d.get("subagentBrief"), dict) else {}
    t.setdefault("$說明", "agent 開工時自動補上不會傳給它的東西（語言、工作目錄與分支、記憶內文路徑、自我核對清單）；guard＝交報告時核對，不合格退回一次。")
    for k in DEFAULT_SUB_BRIEF:
        t[k] = bool(sb.get(k, DEFAULT_SUB_BRIEF[k]))
    d["subagentBrief"] = t
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
    """只改 taskCheck 的 enabled／minutes，段內其他鍵保留（GU-07：原本整段重建，使用者手動加的鍵會被洗掉）。"""
    minutes = valid_task_minutes(minutes)
    p = lay.payload / "config" / "dispatch-config.json"
    d = read_json(p) if p.exists() else {}
    t = dict(d.get("taskCheck")) if isinstance(d.get("taskCheck"), dict) else {}
    t = {"$說明": t.get("$說明") or "背景任務巡檢：有背景任務時每 minutes 分鐘用 CronCreate 醒來檢查，全部結束後刪除排程；enabled=false 完全不做。",
         **{k: v for k, v in t.items() if k != "$說明"}}
    t["enabled"] = bool(enabled)
    t["minutes"] = minutes
    d["taskCheck"] = t
    d["updated"] = _dt.date.today().isoformat()
    write_json(p, d)


def _is_legacy_plan_entry(v) -> bool:
    """舊 plan 格式在 usageThresholdPct 底下每個方案一個 {"fiveHour":…, "sevenDay":…}；扁平化時要拿掉。"""
    return isinstance(v, dict) and ("fiveHour" in v or "sevenDay" in v)


def write_thresholds(lay: Layout, five: float, seven: float) -> None:
    """只改 usageThresholdPct 的兩個數字（扁平格式），段內與檔內其他鍵保留（GU-07）；舊 plan 格式一併扁平化（拿掉各方案的子物件與 plan）。"""
    five, seven = valid_threshold(five, THRESHOLD_LABELS["fiveHour"]), valid_threshold(seven, THRESHOLD_LABELS["sevenDay"])
    p = lay.payload / "config" / "dispatch-config.json"
    d = read_json(p) if p.exists() else {}
    t = dict(d.get("usageThresholdPct")) if isinstance(d.get("usageThresholdPct"), dict) else {}
    t = {"$說明": t.get("$說明") or "觸發收尾的門檻（%）：5 小時用量 >= fiveHour 或 7 天用量 >= sevenDay。沒到就什麼都不做。",
         **{k: v for k, v in t.items() if k != "$說明" and not _is_legacy_plan_entry(v)}}
    t["fiveHour"] = five
    t["sevenDay"] = seven
    d["usageThresholdPct"] = t
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
    if not python:
        return {**read_usage(lay), "text": "找不到系統的 Python ≥3.10，無法讀用量"}
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
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_env = ex.submit(lambda: env(repo, importer=importer, ffmpeg=ffmpeg, python=python) if python is not None or FROZEN else env(repo, importer=importer, ffmpeg=ffmpeg))
        f_pkgs = ex.submit(lambda: {mod: importer(mod) for mod in video.IMPORTS})
        env_items, pkgs = f_env.result(), f_pkgs.result()
    return {
        "installed": bool(m),
        "version": m.get("version") if m else None,
        "repo_version": repo_version(repo),
        "env": env_items,
        "web": {"enabled": bool(m and (m.get("web") or {}).get("enabled")), "servers": servers, "desired_now": sorted(want),
                "env": {k: str(env_vals.get(k)) if env_vals.get(k) is not None else None for k in (src.get("env") or {}) if not k.startswith("_")},
                "env_defaults": {k: str(v) for k, v in (src.get("env") or {}).items() if not k.startswith("_")},
                "env_override": {k: str(v) for k, v in (local.get("env") or {}).items()}},
        "video": {"enabled": bool(m and (m.get("video") or {}).get("enabled")),
                  "packages": pkgs,
                  "download_dir": ((local.get("video") or {}).get("downloadDir") or vcfg.get("downloadDir") or "")},
        "keys": keys,
        "usage": read_usage(lay),
        "thresholds": read_thresholds(lay) if m else dict(DEFAULT_THRESHOLDS),
        "task_check": read_task_check(lay) if m else dict(DEFAULT_TASK_CHECK),
        "sub_brief": read_sub_brief(lay) if m else dict(DEFAULT_SUB_BRIEF),
        "mem_gb": read_mem_gate(lay) if m else DEFAULT_MEM_GB,
        "project_auto": read_project_auto(lay) if m else dict(DEFAULT_PROJECT_AUTO),
        "chrome": {"extension": chrome_extension_installed(), "native_host": chrome_native_host_registered(),
                   "default_enabled": chrome_default_enabled(lay)},
        "hooks": {"usage_guard": bool(m and (m.get("settings") or {}).get("hooksAdded")),
                  "usage_guard_pref": bool(local.get("usageGuard", True)),
                  "source_guard_pref": bool(local.get("sourceGuard", True))},
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
    source_guard: bool = True                          # Stop hook：回覆含年份／數字卻沒「來源」段就退回補一次（local.json sourceGuard）
    task_check: dict = field(default_factory=lambda: dict(DEFAULT_TASK_CHECK))
    sub_brief: dict = field(default_factory=lambda: dict(DEFAULT_SUB_BRIEF))
    mem_gb: float = DEFAULT_MEM_GB                     # 重型工作記憶體門檻（GB）
    project_auto: dict = field(default_factory=lambda: dict(DEFAULT_PROJECT_AUTO))


def form_from_state(state: dict) -> Form:
    f = Form()
    f.usage_guard = state["hooks"]["usage_guard_pref"]
    f.source_guard = state["hooks"].get("source_guard_pref", True)
    f.task_check = dict(state.get("task_check") or DEFAULT_TASK_CHECK)
    f.sub_brief = {**DEFAULT_SUB_BRIEF, **(state.get("sub_brief") or {})}
    f.mem_gb = float(state.get("mem_gb", DEFAULT_MEM_GB))
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
    f.source_guard = on
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
        ch.append(Change("guard", "啟用用量守門 hook" if form.usage_guard else "關閉整支 hook（移除 settings.json 的 7 個 hook 條目：用量守門、查證守門、專案自動化等一起停；規則仍在）"))
    if form.source_guard != state["hooks"].get("source_guard_pref", True):
        ch.append(Change("source_guard", "啟用查證守門（回覆含年份／數字卻沒「來源」段就退回補一次）" if form.source_guard else "關閉查證守門（hook 仍掛著但不檢查）"))
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
    sb0 = {**DEFAULT_SUB_BRIEF, **(state.get("sub_brief") or {})}
    sb_lab = {"enabled": "agent 開工自動補充", "guard": "agent 交報告守門"}
    sb_changed = [k for k in DEFAULT_SUB_BRIEF if bool(form.sub_brief.get(k, sb0[k])) != bool(sb0[k])]
    if sb_changed:
        ch.append(Change("sub_brief", "派工 → " + "、".join(f"{sb_lab[k]}={'開' if form.sub_brief[k] else '關'}" for k in sb_changed)))
    if float(form.mem_gb) != float(state.get("mem_gb", DEFAULT_MEM_GB)):
        ch.append(Change("mem_gate", f"重型工作記憶體門檻：{float(state.get('mem_gb', DEFAULT_MEM_GB)):g} GB → {float(form.mem_gb):g} GB"))
    pa0 = {**DEFAULT_PROJECT_AUTO, **(state.get("project_auto") or {})}
    pa_changed = [k for k in PA_BOOL_KEYS + PA_INT_KEYS if form.project_auto.get(k, pa0[k]) != pa0[k]]
    if pa_changed:
        ch.append(Change("project_auto", "專案自動化 → " + "、".join(f"{PA_LABELS[k]}={'開' if form.project_auto[k] is True else ('關' if form.project_auto[k] is False else form.project_auto[k])}" for k in pa_changed)))
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
    try:
        validate_form(form, state)  # GU-05：數值欄位不合法就整個不動（原本 0、-5、nan 都照寫）
    except ValueError as e:
        log(f"❌ 表單有誤，沒有套用任何變更：{e}")
        return 2
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
    # GU-02：local.json 是壞檔時，下面所有會寫它的步驟都不做（原本 _local() 回空預設值、整檔蓋掉，金鑰無聲消失）；與 commands.web_config 對壞檔的處理一致
    if keys or enable or disable or env_args or modes or any(c.kind in LOCAL_WRITE_KINDS for c in changes):  # env_reset 不算：沒有變更時它也常是非空（全部＝預設值）
        try:
            web.load_local(lay)
        except ValueError as e:
            log(f"❌ {e}（沒有套用任何變更）")
            return 2
    # 0) 用量守門開關只是 local.json 的一個布林，apply 時 _sync_settings 會照它加／移除 hook
    if form.usage_guard != state["hooks"]["usage_guard_pref"]:
        local = _local_strict(lay)
        local["usageGuard"] = bool(form.usage_guard)
        web.save_local(lay, local)
        log(f"用量守門 → {'開' if form.usage_guard else '關'}（local.json usageGuard）")
    if form.source_guard != state["hooks"].get("source_guard_pref", True):
        local = _local_strict(lay)
        local["sourceGuard"] = bool(form.source_guard)
        web.save_local(lay, local)
        log(f"查證守門 → {'開' if form.source_guard else '關'}（local.json sourceGuard；hook 每次回覆結束時讀它）")
    notes = {n: str(v).strip() for n, v in form.key_notes.items() if v is not None and n in state["keys"] and str(v).strip() != state["keys"][n].get("account", "")}
    if notes:
        local = _local_strict(lay)
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
    if any(c.kind == "mem_gate" for c in changes):
        write_mem_gate(lay, float(form.mem_gb))
        log(f"重型工作記憶體門檻寫入 {float(form.mem_gb):g} GB")
    if any(c.kind == "sub_brief" for c in changes):
        write_sub_brief(lay, form.sub_brief)
        log(f"派工補充與交報告守門寫入：{form.sub_brief}")
    if any(c.kind == "task_check" for c in changes):
        write_task_check(lay, bool(form.task_check.get("enabled")), int(form.task_check.get("minutes", DEFAULT_TASK_CHECK["minutes"])))
        log(f"背景任務巡檢寫入：{'每 ' + str(int(form.task_check['minutes'])) + ' 分鐘' if form.task_check.get('enabled') else '關閉'}")
    if any(c.kind == "project_auto" for c in changes):
        write_project_auto(lay, form.project_auto)
        log(f"專案自動化寫入：{form.project_auto}")
    if any(c.kind == "download_dir" for c in changes):
        local = _local_strict(lay)
        local.setdefault("video", {})["downloadDir"] = form.download_dir or ""
        web.save_local(lay, local)
        log(f"下載資料夾寫入 local.json：{form.download_dir or '（預設）'}")
    if any(c.kind == "chrome" for c in changes):
        p = set_chrome_default_enabled(lay, bool(form.chrome_default_enabled))
        log(f"Claude in Chrome 預設{'啟用' if form.chrome_default_enabled else '關閉'}（{p}，已備份）")
    return worst


# 這些變更種類（Change.kind）會寫 local.json；壞檔時整批不套用（見 apply_form 的預檢）
LOCAL_WRITE_KINDS = ("guard", "source_guard", "keys", "env", "download_dir", "web")


def _local(lay: Layout) -> dict:
    """只給畫面讀取與 web.mask 用：壞檔回空預設值。要寫檔一律用 _local_strict，不可把這個回傳值寫回去（GU-02）。"""
    try:
        return web.load_local(lay)
    except ValueError:
        return {"keys": {}, "enable": [], "disable": [], "env": {}}


def _local_strict(lay: Layout) -> dict:
    """寫入路徑用：壞檔丟 ValueError（訊息含檔名與「請修好或刪除」），絕不用空預設值整檔蓋掉。"""
    return web.load_local(lay)


def _prewrite_local(lay, keys, enable, disable, env_args, env_reset, modes):
    local = _local_strict(lay)
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
    try:
        local = _local_strict(lay)
    except ValueError:
        return  # 壞檔：沒東西可重設，也絕不寫（錯誤訊息由 apply_form 預檢與 commands.web_config 給）
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
    # --force：已裝 Store／MSIX 版時 winget 把 install 當 upgrade，回「找不到可用的升級」0x8A15002B 而不裝 MSI（2026-11-02 另一台實測）；
    # 官方：--force = "Direct run the command and continue with non security related issues"（learn.microsoft.com/windows/package-manager/winget/install）
    "pwsh7": ["winget", "install", "--id", "Microsoft.PowerShell", "--source", "winget", "--installer-type", "wix", "--force", "--accept-package-agreements", "--accept-source-agreements"],
    # 選 Deno 不選 Node：yt-dlp wiki/EJS「Deno (recommended) | Enabled by default」「Code is run with restricted permissions」；Node 要另外啟用
    "deno": ["winget", "install", "--id", "DenoLand.Deno", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements"],
    # 0.15.0 一鍵安裝（使用者 11/4：「所有環境安裝的部分可不可以都用成點按鈕就直接安裝…裝的版本就挑穩定又最新的版本」）
    # Node：LTS 線，不用 Current（winget 2026-11-07 為 26.13.0）
    "node": ["winget", "install", "--id", "OpenJS.NodeJS.LTS", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements"],
    # Python 3.14：winget 上最新的正式版（3.14.10），新裝置實測 faster-whisper 1.2.1 可用、ctranslate2 4.8.5 有 Windows cp314 套件
    "python": ["winget", "install", "--id", "Python.Python.3.14", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements"],
    "git": ["winget", "install", "--id", "Git.Git", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements"],
    # Claude Code 用官方原生安裝的 stable 通道，不用 winget：code.claude.com/docs/en/setup「WinGet installations do not auto-update」；
    # stable＝「typically about one week old, skipping releases with major regressions」，之後自動更新也跟 stable
    "claude": ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
               "& ([scriptblock]::Create((irm https://claude.ai/install.ps1))) stable"],
}
INSTALL_LABELS = {"ffmpeg": "安裝 ffmpeg（winget）", "pwsh7": "安裝 PowerShell 7（MSI，會跳 UAC）", "faster_whisper": "安裝 faster-whisper（pip）",
                  "deno": "安裝 Deno（winget）", "node": "安裝 Node.js LTS（winget）", "python": "安裝 Python 3.14（winget）",
                  "git": "安裝 Git（winget）", "claude": "安裝 Claude Code（官方，stable）"}
INSTALL_CONFIRM = {  # 按下去前要問的（會跳 UAC、或裝完還有使用者要做的步驟）
    "pwsh7": "會用 winget 安裝 MSI 版並跳出 UAC，安裝後請重開 Claude Code。繼續？",
    "node": "會用 winget 安裝 Node.js LTS，可能跳出 UAC。繼續？",
    "git": "會用 winget 安裝 Git for Windows，可能跳出 UAC。繼續？",
    "python": "會用 winget 安裝 Python 3.14，可能跳出 UAC。裝好後這個視窗會自動找到它，不用重開。繼續？",
    "claude": "會執行官方安裝腳本（stable 通道，之後自動更新）。裝好後要在終端機打 claude 登入一次。繼續？",
}
DOWNLOAD_PAGES = {"python": "https://www.python.org/downloads/", "claude": "https://code.claude.com/docs/en/setup"}  # 沒有 winget 時的備案


def install_button(action: str | None, has_winget: bool) -> tuple[str, str] | None:
    """環境列右邊要放什麼按鈕：("install", 文字)、("page", 網址) 或 None。需要 winget 卻沒有時退回開下載頁。"""
    if not action:
        return None
    needs_winget = action in INSTALL_ACTIONS and INSTALL_ACTIONS[action][0] == "winget"
    if action in INSTALL_LABELS and not (needs_winget and not has_winget):
        return "install", INSTALL_LABELS[action]
    if action in DOWNLOAD_PAGES:
        return "page", DOWNLOAD_PAGES[action]
    return None

# winget／MSI 失敗代碼的白話說明（官方：learn.microsoft.com/troubleshoot/windows-server/application-management/msi-installation-error-1603、
# learn.microsoft.com/intune/configmgr/tenant-attach/app-install-error-reference）
INSTALL_HINTS = {
    "1603": "MSI 1603（安裝時發生嚴重錯誤）。微軟列的常見原因：①同一個程式已經裝了（最常見：PowerShell 7 已裝在別的磁碟或位置）"
            "②目標資料夾加密 ③磁碟是 subst 替代磁碟 ④SYSTEM 帳號對目標資料夾沒有完整控制權限。先按「重新整理」看環境列是否已經 ✅；"
            "已有 7.x 就不用再裝。",
    "1602": "使用者取消了安裝（UAC 按了否或關掉）。",
    "1618": "另一個安裝正在進行，等它結束再試。",
    "1638": "已經裝了另一個版本，先到「設定 → 應用程式」移除舊版再裝。",
    "0x8A15002B": "winget：找不到可用的升級（已經裝了同一版）。",
    "2316632107": "winget：找不到可用的升級（已經裝了同一版）。",
}


def install_hint(code: int, out: str) -> str | None:
    """依結束碼與輸出找白話說明；找不到回 None。"""
    text = f"{out} {code}"
    for k, v in INSTALL_HINTS.items():
        if (k.isdigit() and len(k) == 4 and f"結束代碼為: {k}" in out) or (k.isdigit() and len(k) == 4 and f"exit code: {k}" in out.lower()) \
                or (k == str(code)) or (k.startswith("0x") and k.lower() in text.lower()):
            return v
    return None


def decode_output(b: bytes | None, fallback: str | None = None) -> str:
    """外部程式（winget、powershell.exe）被重導向時輸出的編碼不固定：先照 UTF-8 嚴格解；不是合法 UTF-8 就改用系統碼頁（台灣為 cp950）解，
    仍有解不開的位元組才用 errors=replace（M：絕不丟 UnicodeDecodeError；碼頁 950 的中文訊息不會整段變成 U+FFFD，
    install_hint 才找得到「結束代碼為: 1603」這類在地化字串）。"""
    import locale
    b = b or b""
    try:
        return b.decode("utf-8", "strict")
    except UnicodeDecodeError:
        pass
    try:
        return b.decode(fallback or locale.getpreferredencoding(False) or "utf-8", "replace")
    except LookupError:
        return b.decode("utf-8", "replace")


def should_close_after_apply(close_requested: bool, apply_code: int | None) -> bool:
    """關窗時選「先套用」：套用工作結束後要不要關窗。只有真的跑完套用而且成功（結束碼 0）才關；
    失敗（1、2）或套用根本沒跑（None）都不關，讓使用者看得到 ❌（GU-06：原本失敗也照樣關窗）。"""
    return bool(close_requested) and apply_code == 0


def relaunch_command(executable: str, home) -> list[str]:
    """視窗內換完 exe 後重開的指令：要把目前用的設定目錄帶過去，否則用 --claude-home 開的視窗重開後會跑到預設目錄（GU-12）。"""
    return [str(executable), "--claude-home", str(home), "--after-update"]


def install_action(action: str, python: str, gpu: bool = False, run=subprocess.run) -> tuple[int, str]:
    if action == "faster_whisper":
        if not python:  # 原本把 None 傳給 subprocess，顯示「expected str, bytes or os.PathLike object, not NoneType」
            return 1, "找不到系統的 Python ≥3.10。先安裝 Python（環境區「開下載頁」），裝好按「重新整理」再試，不用關視窗。"
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
    out = decode_output((r.stdout or b"") + (r.stderr or b""))
    return r.returncode, out[-1500:]


def chrome_live_test(run=subprocess.run, timeout: int = 150, which=shutil.which) -> tuple[bool, str]:
    """第三層：背景跑一次 claude -p --chrome 叫它開 example.com 讀標題。會用掉約一場對話開場的用量，只手動觸發。"""
    exe = which("claude")
    if not exe:
        return False, "找不到 claude 指令"
    # 不能用 about:blank：擴充功能會拒絕「browser-internal or unparseable URLs」（2026-11-01 使用者按視窗按鈕實測失敗），改開 example.com
    # 帳號連著兩台以上的瀏覽器時，無頭模式沒有 AskUserQuestion 可問，模型會停下來「請你選」→ 測試失敗（2026-11-02 另一台實測）。
    # list_connected_browsers 每台有 onThisComputer（正在或剛在這台電腦上跑）、isLocal（OS 相同，弱線索），叫它照這順序自己選本機那台
    prompt = ("用 Claude in Chrome 開一個新分頁到 https://example.com ，用 get_page_text 或 read_page 確認頁面標題含 Example Domain，然後關掉這個分頁。"
              "如果回報有多台瀏覽器連線：這是自動化測試，我已授權你自己選——呼叫 list_connected_browsers，用 select_browser 選 onThisComputer 為 true 的那台；沒有就選 isLocal 為 true 的；再沒有就選第一台。不要問我、不要停下來。"
              "成功只回答「CHROME_OK」，失敗回答「CHROME_FAIL: 原因」。不要做其他事。")
    allowed = ",".join(f"mcp__claude-in-chrome__{t}" for t in ("tabs_context_mcp", "tabs_create_mcp", "navigate", "get_page_text", "read_page", "find", "computer", "tabs_close_mcp",
                                                              "list_connected_browsers", "select_browser", "switch_browser"))
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
         "source_guard": form.source_guard, "task_check": dict(form.task_check), "project_auto": dict(form.project_auto),
         "sub_brief": dict(form.sub_brief),
         "mem_gb": float(form.mem_gb),
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


def _bad_profile(field: str, want: str, v) -> ValueError:
    return ValueError(f"設定檔的 {field} 不合格（要{want}）：{v!r}；整份設定檔不匯入")


def import_profile(form: Form, data: dict) -> Form:
    """把設定檔套到表單上。GU-08：每個欄位先做型別與範圍檢查，任何一項不合格就丟 ValueError、整份不匯入（原本 "abc"、"yes"、"no" 都放行，
    之後 int("abc") 在 Tk callback 外丟例外、bool("no") 變成 True）。數值規則與視窗表單共用 valid_*（唯一來源）。"""
    if not isinstance(data, dict) or data.get("claude-dev-system-profile") != 1:
        raise ValueError("不是本工具的設定檔（缺 claude-dev-system-profile: 1）")
    f = copy.deepcopy(form)
    for k in ("web_enabled", "video_enabled", "usage_guard", "source_guard"):
        if k in data and not isinstance(data[k], bool):
            raise ValueError(f"設定檔的 {k} 必須是 true／false")
    if "download_dir" in data and not isinstance(data["download_dir"], str):
        raise ValueError("設定檔的 download_dir 必須是字串")
    if "chrome_default_enabled" in data and data["chrome_default_enabled"] is not None and not isinstance(data["chrome_default_enabled"], bool):
        raise _bad_profile("chrome_default_enabled", " true／false 或 null", data["chrome_default_enabled"])
    if "mem_gb" in data:
        f.mem_gb = valid_mem_gb(data["mem_gb"])
    for k in ("web_enabled", "video_enabled", "download_dir", "chrome_default_enabled", "usage_guard", "source_guard"):
        if k in data:
            setattr(f, k, data[k])
    th = data.get("thresholds")
    if th is not None and not isinstance(th, dict):
        raise _bad_profile("thresholds", "是物件", th)
    for k in ("fiveHour", "sevenDay"):
        if isinstance(th, dict) and k in th:
            try:
                f.thresholds[k] = valid_threshold(th[k], f"設定檔的門檻 {k}")
            except ValueError as e:
                raise ValueError(f"{e}；整份設定檔不匯入") from None
    tc = data.get("task_check")
    if tc is not None and not isinstance(tc, dict):
        raise _bad_profile("task_check", "是物件", tc)
    if isinstance(tc, dict):
        if "enabled" in tc:
            if not isinstance(tc["enabled"], bool):
                raise _bad_profile("task_check.enabled", " true／false", tc["enabled"])
            f.task_check["enabled"] = tc["enabled"]
        if "minutes" in tc:
            try:
                f.task_check["minutes"] = valid_task_minutes(tc["minutes"])
            except ValueError as e:
                raise ValueError(f"設定檔的 task_check.minutes：{e}；整份設定檔不匯入") from None
    pa = data.get("project_auto")
    if pa is not None and not isinstance(pa, dict):
        raise _bad_profile("project_auto", "是物件", pa)
    if isinstance(pa, dict):
        for k in PA_BOOL_KEYS:
            if k in pa:
                if not isinstance(pa[k], bool):
                    raise _bad_profile(f"project_auto.{k}", " true／false", pa[k])
                f.project_auto[k] = pa[k]
        for k in PA_INT_KEYS:
            if k in pa:
                try:
                    f.project_auto[k] = valid_pa_int(k, pa[k])
                except ValueError as e:
                    raise ValueError(f"設定檔的 project_auto.{k}：{e}；整份設定檔不匯入") from None
    sb = data.get("sub_brief")
    if sb is not None and not isinstance(sb, dict):
        raise _bad_profile("sub_brief", "是物件", sb)
    if isinstance(sb, dict):
        for k, v in sb.items():
            if k in DEFAULT_SUB_BRIEF:
                if not isinstance(v, bool):
                    raise _bad_profile(f"sub_brief.{k}", " true／false", v)
                f.sub_brief[k] = v
    sv = data.get("servers")
    if sv is not None and not isinstance(sv, dict):
        raise _bad_profile("servers", "是物件", sv)
    if isinstance(sv, dict):
        for n, v in sv.items():
            if n in f.servers:  # 別台機器才有的 MCP 名稱略過
                if not isinstance(v, bool):
                    raise _bad_profile(f"servers.{n}", " true／false", v)
                f.servers[n] = v
    ev = data.get("env")
    if ev is not None and not isinstance(ev, dict):
        raise _bad_profile("env", "是物件", ev)
    if isinstance(ev, dict):
        for k, v in ev.items():
            if isinstance(v, bool) or not isinstance(v, (str, int, float)):
                raise _bad_profile(f"env.{k}", "是字串或數字", v)
            f.env[k] = v
    km = data.get("key_modes")
    if km is not None and not isinstance(km, dict):
        raise _bad_profile("key_modes", "是物件", km)
    if isinstance(km, dict):
        f.key_modes.update({n: v for n, v in km.items() if n in KEY_INFO and v in web.KEY_MODES})
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
