"""安裝紀錄（manifest）與舊版設定遷移。

為什麼不把版本寫進 settings.json：Claude Code 會驗證 settings.json 的結構，加入非官方鍵有被警告或日後被拒的風險，
所以本工具的狀態一律記在 <CLAUDE_HOME>/claude-dev-system/manifest.json，settings.json 只放帶標記的 hook 條目。
"""
from __future__ import annotations

from pathlib import Path

from . import MANIFEST_SCHEMA
from .fsio import read_json, write_json


def empty() -> dict:
    return {
        "schemaVersion": MANIFEST_SCHEMA,
        "version": None,
        "files": {},            # 相對 CLAUDE_HOME 的路徑 -> sha256（本工具寫入的每個檔）
        "userEditable": [],     # 使用者可改的檔：update／uninstall 偵測到改動時保留
        "skills": [],
        "claudeMd": {"blockSha256": None, "sep": "", "createdFile": False},
        "settings": {"hooksAdded": [], "hooksSkippedExisting": [], "createdKeys": [], "createdFile": False},
        "web": {"enabled": False, "mcpAdded": [], "envCreatedKeys": [], "skipped": []},  # 聯網來源（選用）
        "video": {"enabled": False, "packages": [], "python": None},  # 影片來源（選用；0.5.0）
        "backups": [],
    }


def _m0_to_1(m: dict) -> dict:
    """遷移骨架範例：schemaVersion 0（或缺）→ 1，補齊新欄位、保留舊值。"""
    base = empty()
    for k, v in m.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k].update(v)
        else:
            base[k] = v
    base["schemaVersion"] = 1
    return base


def _m1_to_2(m: dict) -> dict:
    """1 → 2：補 web 紀錄（0.3.0 聯網來源）；舊安裝視為未啟用。"""
    m.setdefault("web", empty()["web"])
    m["schemaVersion"] = 2
    return m


def _m2_to_3(m: dict) -> dict:
    """2 → 3：補 video 紀錄（0.5.0 影片來源）；舊安裝視為未啟用。"""
    m.setdefault("video", empty()["video"])
    m["schemaVersion"] = 3
    return m


MIGRATIONS = {0: _m0_to_1, 1: _m1_to_2, 2: _m2_to_3}  # 新增 schema 版本時在這裡加 {舊版: 函式}，並寫進 CHANGELOG


def migrate(m: dict) -> dict:
    v = int(m.get("schemaVersion") or 0)
    if v > MANIFEST_SCHEMA:
        raise RuntimeError(f"manifest schemaVersion {v} 比本安裝器支援的 {MANIFEST_SCHEMA} 新，請先更新 claude-dev-system repo")
    while v < MANIFEST_SCHEMA:
        m = MIGRATIONS[v](m)
        v = int(m["schemaVersion"])
    return m


def load(p: Path) -> dict | None:
    if not p.exists():
        return None
    return migrate(read_json(p))


def save(p: Path, m: dict) -> None:
    write_json(p, m)
