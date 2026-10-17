"""路徑解析：所有平台共用同一套規則（Windows 已驗證；macOS／Linux 未驗證）。"""
from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def claude_home(override: str | None = None) -> Path:
    """Claude Code 使用者設定目錄：--claude-home > 環境變數 CLAUDE_CONFIG_DIR > ~/.claude。"""
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".claude"


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
