"""環境檢查：OS、Python、Node、git、Claude Code 版本與相容範圍。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .paths import REPO, os_name


def parse_ver(s: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", s or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None


def run_version(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *cmd[1:]], capture_output=True, timeout=30)
        return (r.stdout or r.stderr).decode("utf-8", "replace").strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return None


def compat(repo: Path = REPO) -> dict:
    return json.loads((repo / "config" / "compat.json").read_text(encoding="utf-8"))


def claude_code_status(repo: Path = REPO) -> tuple[bool | None, str]:
    raw = run_version(["claude", "--version"])
    if not raw:
        return None, "找不到 claude 指令（安裝仍可進行，但無法確認版本相容）"
    v = parse_ver(raw)
    c = compat(repo)["claudeCode"]
    lo, hi = parse_ver(c["min"]), parse_ver(c["maxExclusive"])
    ok = v is not None and lo <= v < hi
    tested = "（已實測）" if raw.split()[0] in c.get("tested", []) else "（範圍內但未實測此版本）"
    return ok, f"Claude Code {raw}；相容範圍 ≥{c['min']} 且 <{c['maxExclusive']}" + (tested if ok else "（超出範圍）")


def env_report(home: Path, repo: Path = REPO) -> list[tuple[str, bool | None, str]]:
    """回傳 [(項目, 通過?, 說明)]；通過? None＝警告不擋。"""
    c = compat(repo)
    rows = []
    osn = os_name()
    rows.append(("作業系統", True if osn in c["platforms"] else None, f"{osn}：{c['platforms'].get(osn, '未列入支援清單')}"))
    pv = sys.version_info[:3]
    pmin = parse_ver(c["python"]["min"])
    rows.append(("Python", pv[:2] >= pmin[:2], f"{sys.version.split()[0]}（需 ≥{c['python']['min']}）；執行檔 {sys.executable}"))
    node = run_version(["node", "--version"])
    rows.append(("Node.js", True if node else None, (node or "未安裝") + "（本工具不需要；看板 mod 由 Claude Code 自己執行）"))
    git = run_version(["git", "--version"])
    rows.append(("git", True if git else None, (git or "未安裝") + "（跨裝置取得本工具需要）"))
    ok, msg = claude_code_status(repo)
    rows.append(("Claude Code", ok, msg))
    rows.append(("設定目錄", home.is_dir() or None, str(home) + ("" if home.is_dir() else "（不存在，安裝時會建立）")))
    st = home / "settings.json"
    if st.exists():
        try:
            json.loads(st.read_text(encoding="utf-8"))
            rows.append(("settings.json", True, f"{st}（可解析）"))
        except Exception as e:  # noqa: BLE001
            rows.append(("settings.json", False, f"{st} 不是合法 JSON：{e}（請先修好，安裝器不會覆寫壞檔）"))
    else:
        rows.append(("settings.json", None, f"{st} 不存在（安裝時會建立）"))
    md = home / "CLAUDE.md"
    rows.append(("CLAUDE.md", True if md.exists() else None, f"{md}" + ("" if md.exists() else "（不存在，安裝時會建立）")))
    return rows
