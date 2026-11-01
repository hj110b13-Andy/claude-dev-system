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
    if av and (a / "rules" / "core.md").exists() and (a / "installer" / "install.py").exists() and (not bv or parse_ver(av) >= parse_ver(bv)):
        return a
    return bundled


def _http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "claude-dev-system-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check_update(lay: Layout, bundled: Path = REPO, http=_http_get) -> dict:
    """回 {local, remote, newer, error}。local 是目前生效的 repo 版本。"""
    local = _ver(effective_repo(lay, bundled)) or "0"
    try:
        remote = http(RAW_VERSION_URL, 20).decode("utf-8").strip()
    except Exception as e:  # noqa: BLE001
        return {"local": local, "remote": None, "newer": False, "error": f"連不上 GitHub：{type(e).__name__}: {e}"}
    if not remote or len(remote) > 20:
        return {"local": local, "remote": None, "newer": False, "error": "GitHub 回的版本字串不合法"}
    return {"local": local, "remote": remote, "newer": parse_ver(remote) > parse_ver(local), "error": None}


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
    tag = str(data.get("tag_name") or "").lstrip("v").strip()
    assets = {a.get("name"): a for a in data.get("assets", []) if isinstance(a, dict)}
    exe = assets.get(EXE_NAME)
    if not tag or not exe or not exe.get("browser_download_url"):
        return {**none, "tag": tag or None, "error": "最新 Release 沒有附 exe"}
    sha = assets.get(EXE_NAME + ".sha256")
    return {"tag": tag, "url": exe["browser_download_url"], "size": int(exe.get("size") or 0),
            "sha_url": sha.get("browser_download_url") if sha else None,
            "newer": parse_ver(tag) > parse_ver(bundled_ver or "0"), "error": None}


def download_exe(info: dict, exe_path: Path, log=print, http=_http_get) -> Path:
    """下載新 exe 到 <exe>.new.exe；大小與 Release 附的 .sha256 都對才留下（沒有 .sha256 的舊 Release 至少要像個 exe）。"""
    log(f"下載視窗程式 v{info['tag']}（{info['url']}）…")
    data = http(info["url"], 300)
    if info.get("size") and len(data) != int(info["size"]):
        raise ValueError(f"下載大小 {len(data)} 與 Release 標的 {info['size']} 不符，不換")
    if info.get("sha_url"):
        want = http(info["sha_url"], 20).decode("utf-8").split()[0].lower()
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
    except Exception:
        old.rename(exe_path)
        raise
    return old


def cleanup_old_exe(exe_path: Path) -> int:
    """啟動時刪掉上次更新留下的 .old*.exe；還被鎖著就下次再刪。回刪掉的數量。"""
    n = 0
    for old in exe_path.parent.glob(exe_path.stem + ".old*.exe"):
        for _ in range(10):
            try:
                old.unlink()
                n += 1
                break
            except OSError:
                time.sleep(0.3)
    return n
