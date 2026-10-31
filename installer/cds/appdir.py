"""執行檔模式的「可更新資料夾」：規則、工具、hook、skill、設定範本從 GitHub 下載到 <home>/claude-dev-system/app/，視窗內更新。

為什麼要這層：PyInstaller 打包的 exe 內含一份 repo 快照（sys._MEIPASS/repo），但使用者不該為了規則改一行就換 exe。
所以 exe 啟動時先看 app/ 有沒有更新的版本（config/VERSION 比較大），有就用它當 repo 來源；「檢查更新」按鈕抓 GitHub master 的 VERSION，
比本機新就下載整個 zip、只取需要的資料夾、原子換掉 app/。安裝器程式碼（installer/）也會一起下載，但 exe 本身執行的仍是打包時的程式碼：
程式碼有變時（CHANGELOG 標「需換新 exe」）視窗會提示到 Releases 頁抓新 exe。
只用標準庫；下載走 HTTPS 到使用者自己的公開 repo。
"""
from __future__ import annotations

import io
import shutil
import tempfile
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
