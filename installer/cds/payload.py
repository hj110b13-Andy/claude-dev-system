"""要安裝的檔案清單（來源 repo → 目標 CLAUDE_HOME 相對路徑）。"""
from __future__ import annotations

from pathlib import Path

from . import SKILL_MARKER_FILE

PAYLOAD_ROOT = "claude-dev-system"
USER_EDITABLE = [f"{PAYLOAD_ROOT}/config/dispatch-config.json"]
_SKIP = {"__pycache__", ".pytest_cache"}


def _files_under(d: Path):
    for p in sorted(d.rglob("*")):
        if p.is_file() and not (set(p.relative_to(d).parts) & _SKIP) and not p.name.endswith(".pyc"):
            yield p


def _text(p: Path) -> bytes:
    """payload 全是文字檔：換行一律正規化成 LF。否則同一版在不同 checkout（Windows autocrlf、CI runner、exe 內建快照）位元組不同，
    verify 會報「與 repo 不一致」（2026-11-01 使用者用 CI 打的 exe 按 verify，8 個檔只差 CRLF）。"""
    return p.read_bytes().replace(CRLF_B, LF_B)


CRLF_B, LF_B = bytes([13, 10]), bytes([10])


def entries(repo: Path, version: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for sub in ("rules", "tools"):
        for p in _files_under(repo / sub):
            out[f"{PAYLOAD_ROOT}/{sub}/{p.relative_to(repo / sub).as_posix()}"] = _text(p)
    out[f"{PAYLOAD_ROOT}/hooks/usage_guard.py"] = _text(repo / "hooks" / "usage_guard.py")
    for name in ("VERSION", "compat.json", "dispatch-config.json", "web-sources.json", "video.json", "selftest.json"):
        out[f"{PAYLOAD_ROOT}/config/{name}"] = _text(repo / "config" / name)
    for sk in skill_names(repo):
        for p in _files_under(repo / "skills" / sk):
            out[f"skills/{sk}/{p.relative_to(repo / 'skills' / sk).as_posix()}"] = _text(p)
        out[f"skills/{sk}/{SKILL_MARKER_FILE}"] = f"installed-by claude-dev-system v{version}\n".encode("utf-8")
    return out


def skill_names(repo: Path) -> list[str]:
    return sorted(p.name for p in (repo / "skills").iterdir() if (p / "SKILL.md").is_file())


def core_rules(repo: Path) -> str:
    return (repo / "rules" / "core.md").read_text(encoding="utf-8")
