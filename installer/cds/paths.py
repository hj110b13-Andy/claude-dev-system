"""路徑解析：所有平台共用同一套規則（Windows 已驗證；macOS／Linux 未驗證）。"""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path


def _repo() -> Path:
    """原始碼執行：repo 根目錄。PyInstaller 執行檔：打包進去的 _MEIPASS/repo 快照（build_exe.py 用 --add-data 放的）。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "repo"
    return Path(__file__).resolve().parents[2]


REPO = _repo()
FROZEN = bool(getattr(sys, "frozen", False))


def norm(p: Path) -> Path:
    """路徑正規化的唯一來源：展開 ~ 後 resolve（junction、符號連結、Windows 8.3 短檔名都換成真實長路徑；不存在的路徑也可以）。
    IN-05：原本 --claude-home／CLAUDE_CONFIG_DIR 會 resolve、預設的 ~/.claude 不會，~/.claude 是 junction 時
    「GUI 安裝、CLI 驗證」算出兩個不同的腳本路徑與 .claude.json 位置。"""
    p = Path(p).expanduser()
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def claude_home(override: str | None = None) -> Path:
    """Claude Code 使用者設定目錄：--claude-home > 環境變數 CLAUDE_CONFIG_DIR > ~/.claude（三者用同一種正規化）。"""
    if override:
        return norm(Path(override))
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return norm(Path(env))
    return norm(Path.home() / ".claude")


def os_name() -> str:
    s = platform.system().lower()
    return {"windows": "windows", "darwin": "macos", "linux": "linux"}.get(s, s)


@dataclass(frozen=True)
class Layout:
    home: Path

    @property
    def settings(self) -> Path:
        return self.home / "settings.json"

    @property
    def claude_md(self) -> Path:
        return self.home / "CLAUDE.md"

    @property
    def payload(self) -> Path:
        return self.home / "claude-dev-system"

    @property
    def manifest(self) -> Path:
        return self.payload / "manifest.json"

    @property
    def backups(self) -> Path:
        return self.home / "backups"

    @property
    def skills(self) -> Path:
        return self.home / "skills"


def repo_version(repo: Path = REPO) -> str:
    return (repo / "config" / "VERSION").read_text(encoding="utf-8").strip()
