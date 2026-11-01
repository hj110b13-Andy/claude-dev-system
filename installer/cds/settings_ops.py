"""settings.json 操作：只新增／移除帶 HOOK_MARK 標記的 hook 條目，其他鍵一律不碰。"""
from __future__ import annotations

import copy

from . import HOOK_MARK

# (事件, matcher)；matcher None 表示該事件不需要 matcher（UserPromptSubmit）
# PostToolUse 只掛在「會推進工作」的工具：每次觸發都要啟動一個 Python 程序（2026-11-01 實測每次約 120 ms），
# Read／Grep／Glob 這類一場對話幾十上百次的工具不掛，用量檢查本來就有 5 分鐘 TTL，不會漏
HOOK_SPECS = [("UserPromptSubmit", None), ("PostToolUse", "Bash|PowerShell|Agent|Task|Edit|Write|NotebookEdit|Workflow")]
HOOK_SCRIPT = "usage_guard.py"


def hook_command(python: str, script_path: str) -> str:
    return f'"{python}" "{script_path}" {HOOK_MARK}'


def _iter_hooks(settings: dict, event: str):
    for group in (settings.get("hooks") or {}).get(event) or []:
        for h in group.get("hooks") or []:
            yield group, h


def find_unmarked_equivalent(settings: dict, event: str) -> str | None:
    """使用者自己掛的同功能 hook（指令含 usage_guard.py 但沒有本工具標記）。"""
    for _, h in _iter_hooks(settings, event):
        cmd = str(h.get("command", ""))
        if HOOK_SCRIPT in cmd and HOOK_MARK not in cmd:
            return cmd
    return None


def has_marked(settings: dict, event: str) -> list[str]:
    return [str(h.get("command")) for _, h in _iter_hooks(settings, event) if HOOK_MARK in str(h.get("command", ""))]


def add_hooks(settings: dict, command: str, timeout: int = 15) -> tuple[dict, dict]:
    """回傳 (新 settings, 紀錄)。不修改傳入物件。已有同功能的使用者 hook 時不重複註冊。"""
    s = copy.deepcopy(settings)
    rec = {"hooksAdded": [], "hooksSkippedExisting": [], "createdKeys": []}
    for event, matcher in HOOK_SPECS:
        existing = find_unmarked_equivalent(s, event)
        if existing:
            rec["hooksSkippedExisting"].append({"event": event, "command": existing})
            continue
        if "hooks" not in s:
            s["hooks"] = {}
            rec["createdKeys"].append("hooks")
        if event not in s["hooks"]:
            s["hooks"][event] = []
            rec["createdKeys"].append(f"hooks.{event}")
        group = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        if matcher is not None:
            group = {"matcher": matcher, **group}
        s["hooks"][event].append(group)
        rec["hooksAdded"].append({"event": event, "matcher": matcher, "command": command})
    return s, rec


def remove_marked(settings: dict, created_keys: list[str] | None = None) -> tuple[dict, list[str]]:
    """移除所有帶標記的 hook；因此變空的 group 移除；本工具建立的空事件／空 hooks 鍵也移除。"""
    s = copy.deepcopy(settings)
    created = set(created_keys or [])
    removed: list[str] = []
    hooks = s.get("hooks")
    if not isinstance(hooks, dict):
        return s, removed
    for event in list(hooks.keys()):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        new_groups = []
        for g in groups:
            hs = g.get("hooks") or []
            keep = [h for h in hs if HOOK_MARK not in str(h.get("command", ""))]
            removed += [f"{event}: {h.get('command')}" for h in hs if HOOK_MARK in str(h.get("command", ""))]
            if len(keep) == len(hs):
                new_groups.append(g)
            elif keep:
                new_groups.append({**g, "hooks": keep})
        hooks[event] = new_groups
        if not new_groups and f"hooks.{event}" in created:
            del hooks[event]
    if not hooks and "hooks" in created:
        del s["hooks"]
    return s, removed
