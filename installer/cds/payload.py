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


def entries(repo: Path, version: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for sub in ("rules", "tools"):
        for p in _files_under(repo / sub):
            out[f"{PAYLOAD_ROOT}/{sub}/{p.relative_to(repo / sub).as_posix()}"] = p.read_bytes()
    out[f"{PAYLOAD_ROOT}/hooks/usage_guard.py"] = (repo / "hooks" / "usage_guard.py").read_bytes()
    for name in ("VERSION", "compat.json", "dispatch-config.json", "web-sources.json"):
        out[f"{PAYLOAD_ROOT}/config/{name}"] = (repo / "config" / name).read_bytes()
    for sk in skill_names(repo):
        for p in _files_under(repo / "skills" / sk):
            out[f"skills/{sk}/{p.relative_to(repo / 'skills' / sk).as_posix()}"] = p.read_bytes()
        out[f"skills/{sk}/{SKILL_MARKER_FILE}"] = f"installed-by claude-dev-system v{version}\n".encode("utf-8")
    return out


def skill_names(repo: Path) -> list[str]:
    return sorted(p.name for p in (repo / "skills").iterdir() if (p / "SKILL.md").is_file())


def core_rules(repo: Path) -> str:
    return (repo / "rules" / "core.md").read_text(encoding="utf-8")
