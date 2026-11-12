"""執行檔模式的「可更新資料夾」：規則、工具、hook、skill、設定範本從 GitHub 下載到 <home>/claude-dev-system/app/，視窗內更新。

為什麼要這層：PyInstaller 打包的 exe 內含一份 repo 快照（sys._MEIPASS/repo），但使用者不該為了規則改一行就換 exe。
所以 exe 啟動時先看 app/ 有沒有更新的版本（config/VERSION 比較大），有就用它當 repo 來源；「檢查更新」按鈕抓 GitHub master 的 VERSION，
比本機新就下載整個 zip、只取需要的資料夾、原子換掉 app/。安裝器程式碼（installer/）也會一起下載，但 exe 本身執行的仍是打包時的程式碼，所以視窗程式有變時要換 exe——
這件事也在視窗內自動做（0.11.7 起）：查 GitHub 最新 Release 的 exe（tag 版本比內建新就下載），大小與 .sha256 都對才換；
Windows 執行中的 exe 可以改名不能刪，所以目前的改成 .old.exe、新的改成原名，重開視窗，下次啟動把 .old 刪掉。
只用標準庫；下載走 HTTPS 到使用者自己的公開 repo。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from .checks import parse_ver
from .paths import REPO, Layout, repo_version

OWNER_REPO = "hj110b13-Andy/claude-dev-system"
BRANCH = "master"
RAW_VERSION_URL = f"https://raw.githubusercontent.com/{OWNER_REPO}/{BRANCH}/config/VERSION"
ZIP_URL = f"https://github.com/{OWNER_REPO}/archive/refs/heads/{BRANCH}.zip"
RELEASES_URL = f"https://github.com/{OWNER_REPO}/releases/latest"
LATEST_API = f"https://api.github.com/repos/{OWNER_REPO}/releases/latest"
EXE_NAME = "claude-dev-system-settings.exe"
KEEP_DIRS = ("rules", "tools", "hooks", "skills", "config", "installer", "docs")
KEEP_FILES = ("README.md", "CHANGELOG.md", "CLAUDE.md", "LICENSE")


NO_VERSION = "0.0.0"  # 讀不到版本時的預設值（必須解析得出來；原本用 "0"，parse_ver("0") 是 None，比較會丟 TypeError）


def is_newer(candidate, current) -> tuple[bool, str | None]:
    """版本比較的唯一來源（check_update、check_exe_update 共用）。回 (candidate 是否比 current 新, 錯誤說明)。
    任何一邊解析不出版本（latest、vtest、None、空字串…）都回 (False, 說明)，不丟例外（GU-03：原本 None > tuple 丟 TypeError，
    因為是例外不是 error 欄位，exe 更新的備援也不會啟動）。"""
    a, b = parse_ver(str(candidate) if candidate is not None else ""), parse_ver(str(current) if current is not None else "")
    if a is None:
        return False, f"版本字串不合法：{candidate!r}"
    if b is None:
        return False, f"目前版本字串不合法：{current!r}"
    return a > b, None


def update_plan(rules: dict, exe: dict | None) -> str:
    """「有沒有東西要更新」的唯一來源（GU-10：開窗自動檢查原本只看規則版本、不查 exe，手動檢查才查，兩處各寫一份）。
    rules 是 check_update 的結果、exe 是 check_exe_update 的結果（原始碼模式或查不到傳 None）。
    回 "rules"（規則／工具有新版，更新流程會順便處理 exe）、"exe_only"（規則最新但視窗程式 exe 有新版）、"none"。"""
    if rules and rules.get("newer"):
        return "rules"
    if exe and exe.get("newer"):
        return "exe_only"
    return "none"


def app_dir(lay: Layout) -> Path:
    return lay.payload / "app"


def _ver(repo: Path) -> str | None:
    try:
        return repo_version(repo)
    except Exception:  # noqa: BLE001
        return None


def effective_repo(lay: Layout, bundled: Path = REPO) -> Path:
    """app/ 有完整內容且版本不比內建舊就用 app/，否則用內建（原始碼執行時就是 repo 本身）。"""
    a = app_dir(lay)
    av, bv = _ver(a), _ver(bundled)
    complete = av and parse_ver(av) is not None and (a / "rules" / "core.md").exists() and (a / "installer" / "install.py").exists()
    if complete and (not bv or parse_ver(bv) is None or parse_ver(av) >= parse_ver(bv)):
        return a
    return bundled


def _is_cert_error(e: Exception) -> bool:
    import ssl
    r = getattr(e, "reason", e)
    return isinstance(r, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(e)


def _curl_get(url: str, timeout: int, run=None) -> bytes:
    """Windows 10 起內建 curl.exe（Schannel）。2026-11-03 另一台：Python 連 api.github.com 回 CERTIFICATE_VERIFY_FAILED
    「unable to get issuer certificate」（缺中繼憑證或防毒／公司網路攔截），同一台的 raw.githubusercontent.com 卻正常。
    Schannel 會照 Windows 的方式補抓中繼憑證並信任系統裝的根憑證，所以改用它重試；憑證仍會驗證，不是關掉檢查。"""
    import shutil
    import subprocess
    exe = shutil.which("curl.exe") or shutil.which("curl")
    if not exe:
        raise OSError("沒有 curl.exe 可重試")
    r = (run or subprocess.run)([exe, "-fsSL", "--ssl-revoke-best-effort", "--max-time", str(int(timeout)), "-A", "claude-dev-system-updater", url],
                                capture_output=True, timeout=timeout + 10)
    if r.returncode != 0:
        raise OSError(f"curl.exe 也失敗（結束碼 {r.returncode}）：{(r.stderr or b'').decode('utf-8', 'replace').strip()[:200]}")
    return r.stdout


def _http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "claude-dev-system-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:  # noqa: BLE001
        if not _is_cert_error(e):
            raise
        return _curl_get(url, timeout)


def check_update(lay: Layout, bundled: Path = REPO, http=_http_get) -> dict:
    """回 {local, remote, newer, error}。local 是目前生效的 repo 版本。"""
    local = _ver(effective_repo(lay, bundled)) or NO_VERSION
    try:
        remote = http(RAW_VERSION_URL, 20).decode("utf-8").strip()
    except Exception as e:  # noqa: BLE001
        return {"local": local, "remote": None, "newer": False, "error": f"連不上 GitHub：{type(e).__name__}: {e}"}
    if not remote or len(remote) > 20 or parse_ver(remote) is None:
        return {"local": local, "remote": None, "newer": False, "error": "GitHub 回的版本字串不合法"}
    newer, err = is_newer(remote, local)
    return {"local": local, "remote": remote, "newer": newer, "error": err}


def download_update(lay: Layout, log=print, http=_http_get) -> Path:
    """下載 master zip → 只留 KEEP_DIRS／KEEP_FILES → 原子換掉 app/。回 app/ 路徑。失敗時舊 app/ 不動。"""
    log(f"下載 {ZIP_URL} …")
    data = http(ZIP_URL, 180)
    log(f"下載完成 {len(data) / 1024:.0f} KB，解壓中…")
    target = app_dir(lay)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cds-app-", dir=str(target.parent)) as td:
        tmp = Path(td)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            top = names[0].split("/")[0] if names else ""
            for n in names:
                parts = n.split("/")
                if len(parts) < 2 or parts[0] != top or n.endswith("/"):
                    continue
                rel = "/".join(parts[1:])
                if not (parts[1] in KEEP_DIRS or (len(parts) == 2 and parts[1] in KEEP_FILES)):
                    continue
                if ".." in parts:
                    continue
                dst = tmp / "new" / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out)
        newv = _ver(tmp / "new")
        if not newv or not (tmp / "new" / "rules" / "core.md").exists():
            raise RuntimeError("下載的內容缺 config/VERSION 或 rules/core.md，不套用")
        old = target.with_name("app.old")
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.rename(old)
        try:
            shutil.move(str(tmp / "new"), str(target))
        except Exception:
            if old.exists() and not target.exists():
                old.rename(target)
            raise
        shutil.rmtree(old, ignore_errors=True)
    log(f"app/ 已更新為 v{newv}：{target}")
    return target


def code_changed_since(bundled: Path, repo: Path) -> bool:
    """app/ 的安裝器程式碼與 exe 內建的不同 → 提示換新 exe（規則／工具不用）。"""
    try:
        a = sorted(p.relative_to(repo / "installer").as_posix() + ":" + str(p.stat().st_size) for p in (repo / "installer").rglob("*.py"))
        b = sorted(p.relative_to(bundled / "installer").as_posix() + ":" + str(p.stat().st_size) for p in (bundled / "installer").rglob("*.py"))
        return a != b
    except Exception:  # noqa: BLE001
        return False


def check_exe_update(bundled_ver: str | None, http=_http_get) -> dict:
    """GitHub 最新 Release 的 exe 是否比執行中的 exe（內建版本）新。回 {tag, url, size, sha_url, newer, error}。"""
    none = {"tag": None, "url": None, "size": 0, "sha_url": None, "newer": False}
    try:
        data = json.loads(http(LATEST_API, 20).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {**none, "error": f"查不到 Releases：{type(e).__name__}: {e}"}
    if not isinstance(data, dict):
        return {**none, "error": "Releases 回的資料格式不對"}
    tag = str(data.get("tag_name") or "").lstrip("v").strip()
    assets = {a.get("name"): a for a in (data.get("assets") if isinstance(data.get("assets"), list) else []) if isinstance(a, dict)}
    exe = assets.get(EXE_NAME)
    if not tag or not exe or not exe.get("browser_download_url"):
        return {**none, "tag": tag or None, "error": "最新 Release 沒有附 exe"}
    sha = assets.get(EXE_NAME + ".sha256")
    try:
        size = int(exe.get("size") or 0)
    except (TypeError, ValueError):
        size = 0  # 沒有標大小就只靠 .sha256 核對
    newer, err = is_newer(tag, bundled_ver or NO_VERSION)  # tag 是 latest／vtest 之類解析不出來 → 不是較新、error 說明（不丟例外）
    return {"tag": tag, "url": exe["browser_download_url"], "size": size,
            "sha_url": sha.get("browser_download_url") if sha else None, "newer": newer, "error": err}


def parse_sha256(raw: bytes) -> str:
    """讀 Release 附的 .sha256（格式「<64 位十六進位>  <檔名>」）。空檔或格式不對丟 ValueError（原本空檔會 IndexError，訊息看不懂）。"""
    parts = (raw or b"").decode("utf-8-sig", "replace").split()
    if not parts or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
        raise ValueError(".sha256 檔是空的或格式不對，不換 exe")
    return parts[0].lower()


def download_exe(info: dict, exe_path: Path, log=print, http=_http_get) -> Path:
    """下載新 exe 到 <exe>.new.exe；大小與 Release 附的 .sha256 都對才留下（沒有 .sha256 的舊 Release 至少要像個 exe）。"""
    log(f"下載視窗程式 v{info['tag']}（{info['url']}）…")
    data = http(info["url"], 300)
    if info.get("size") and len(data) != int(info["size"]):
        raise ValueError(f"下載大小 {len(data)} 與 Release 標的 {info['size']} 不符，不換")
    if info.get("sha_url"):
        want = parse_sha256(http(info["sha_url"], 20))
        got = hashlib.sha256(data).hexdigest()
        if want != got:
            raise ValueError("sha256 不符，不換 exe")
    elif len(data) < 1_000_000 or data[:2] != b"MZ":
        raise ValueError("下載內容不像 exe，不換")
    new = exe_path.with_name(exe_path.stem + ".new.exe")
    new.write_bytes(data)
    log(f"下載完成 {len(data) / 1048576:.1f} MB，已驗證")
    return new


def swap_exe(exe_path: Path, new_path: Path) -> Path:
    """執行中的 exe 在 Windows 可以改名、不能刪：目前的改成 .old.exe，新的改成原名。回 .old 路徑（下次啟動刪）。換不成就把原本的還原。"""
    old = exe_path.with_name(exe_path.stem + ".old.exe")
    if old.exists():
        try:
            old.unlink()
        except OSError:  # 上一個舊檔還被鎖著（例如連續更新兩次）→ 換個名字
            old = exe_path.with_name(f"{exe_path.stem}.old{int(time.time())}.exe")
    exe_path.rename(old)
    try:
        new_path.rename(exe_path)
    except Exception as e:
        try:
            old.rename(exe_path)
        except Exception as e2:  # noqa: BLE001  還原也失敗：原本的 exe 還在 .old 名下，把位置講清楚（原本只丟還原失敗的例外，使用者看不出 exe「不見了」去哪）
            raise OSError(f"換新 exe 失敗（{type(e).__name__}: {e}），而且把原本的程式改回原名也失敗（{type(e2).__name__}: {e2}）。"
                          f"原本的程式現在叫 {old}，請手動把它改回 {exe_path.name}") from e
        raise
    return old


def old_exe_files(exe_path: Path) -> list[Path]:
    """上次更新留下的 .old*.exe（swap_exe 改的名字）。視窗與 cleanup_old_exe 共用這個 glob，不各寫一份。"""
    return sorted(exe_path.parent.glob(exe_path.stem + ".old*.exe"))


def delete_old_exes(paths) -> list[Path]:
    """試刪一輪：回這次刪掉的；被鎖著（舊程序還在收尾）刪不掉的留著，由呼叫端稍後再試。"""
    gone = []
    for old in paths:
        try:
            old.unlink()
            gone.append(old)
        except OSError:
            continue
    return gone


def cleanup_old_exe(exe_path: Path, tries: int = 10, wait: float = 0.3, sleep=time.sleep) -> int:
    """刪掉上次更新留下的 .old*.exe，被鎖著就等 wait 秒再試、最多 tries 輪，回刪掉的數量。
    舊程序關閉要幾秒（Tk 收尾＋PyInstaller 刪自己的暫存夾），期間檔案鎖著刪不掉。
    視窗（gui.py start_old_exe_cleanup）用同一組 old_exe_files／delete_old_exes，但要每輪回報進度給畫面，所以自己控制迴圈（每秒一輪、最多 90 輪）；
    這個函式是不需要進度的呼叫端用的（GU-11：原 docstring 寫成視窗在用它，與實際不符）。"""
    pending = old_exe_files(exe_path)
    n = 0
    for i in range(max(1, tries)):
        gone = delete_old_exes(pending)
        n += len(gone)
        pending = [p for p in pending if p not in gone]
        if not pending:
            break
        if i < tries - 1:
            sleep(wait)
    return n
