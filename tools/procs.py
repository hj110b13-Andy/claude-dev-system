#!/usr/bin/env python3
"""列出這場 Claude Code 對話的工具指令開出、跑很久的程序（只列、不殺）。只用標準庫。

起因（2026-11-08 Stock-web）：一個 agent 留下 `until [ $(grep -c "FULL" …run-s1.log) -ge 13 ] … do sleep 10; done` 的 bash 迴圈
（另有 tail.exe 掛同一個 log），agent 交報告後從 21:02 空轉到隔天，巡檢沒抓到，使用者自己看到才問。

判定（可判定，不猜）：
- 對話程序＝環境變數 CLAUDE_PID（Claude Code 給工具指令的），沒有就從自己往上找名稱是 claude／claude.exe 的祖先。
- 工具指令程序＝對話程序底下的直接子程序，連同它的子孫。直接子程序有兩種：
  ①名稱是 bash／sh／zsh／pwsh／powershell（Bash 工具：claude.exe → bash.exe -c "source …shell-snapshots…"）；
  ②Windows 的 PowerShell 工具是 claude.exe → cmd.exe /d /s /c "chcp 65001 & pwsh.exe …" → pwsh.exe，所以 cmd.exe 也算，
    但只認命令列含 CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT 的（Claude 開殼才有這個標記；使用者自己開的 cmd 不收）。
    （2026-11-12 稽核 TA-11：本機 pwsh 工具實測的程序鏈，原本這條路開出的程序完全抓不到。）
- 跑超過 min_minutes 分鐘（預設讀 dispatch-config.json 的 procCheck.minMinutes，60）才列；自己這條指令（祖先鏈）不列。
- 上層已不在的工具指令程序（對話關了還留著）也列，標「對話已結束」：命令列含 shell-snapshots 或上面那個標記，而且命令列含目前資料夾；
  「上層已不在」＝父 PID 沒有這個程序，或父 PID 被別的程序重用（父程序建立時間比子程序晚，稽核 TA-12）。
  PowerShell 工具的命令列裡沒有工作資料夾，所以它的孤兒殼在有給資料夾時認不出是哪個專案、不列（只列得出仍在對話底下的）。
是不是殘留由 Claude 對照仍在跑的背景任務／agent 判斷：已結束的 agent 或已交報告的任務留下的才是殘留，告訴使用者 PID 與命令、由使用者決定，不自動結束。

用法：
  python procs.py                 # 列出這場對話跑超過門檻的工具指令程序
  python procs.py --min-minutes 0 # 全部列
  python procs.py --json
Windows 用 Toolhelp32／NtQueryInformationProcess（ctypes，數十毫秒）；其他系統用 ps。
非 Windows 平台未驗證：`ps -eo pid=,ppid=,etimes=,comm=,args=` 在 macOS（BSD ps）可能不支援 etimes、comm 欄含空白也可能切錯欄
（稽核 TA-13；這台只有 Windows，沒有機器可實測，所以沒改程式）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

SHELLS = {"bash", "sh", "zsh", "pwsh", "powershell"}
# Claude Code 開 PowerShell 工具的殼是 cmd.exe /d /s /c "chcp 65001 & pwsh.exe …-Command $env:CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT…"（2026-11-12 本機實測）。
LAUNCHER_MARKER = "CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT"
DEFAULTS = {"enabled": True, "minMinutes": 60, "everyMinutes": 10}


def claude_home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def load_cfg(cwd=None):
    """procCheck：全域 dispatch-config.json，再專案 .claude/dispatch-config.json（cwd 往上找）覆蓋。"""
    cfg = dict(DEFAULTS)
    paths = [os.path.join(claude_home(), "claude-dev-system", "config", "dispatch-config.json")]
    d = os.path.abspath(cwd or os.getcwd())
    while True:
        cand = os.path.join(d, ".claude", "dispatch-config.json")
        if os.path.isfile(cand):
            paths.append(cand)
            break
        if os.path.dirname(d) == d:
            break
        d = os.path.dirname(d)
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                t = (json.load(f) or {}).get("procCheck") or {}
        except Exception:  # noqa: BLE001
            continue
        if isinstance(t.get("enabled"), bool):
            cfg["enabled"] = t["enabled"]
        for k in ("minMinutes", "everyMinutes"):
            if isinstance(t.get(k), (int, float)) and not isinstance(t.get(k), bool) and t[k] >= 0:
                cfg[k] = t[k]
    return cfg


def _base(name: str) -> str:
    n = (name or "").lower().rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return n[:-4] if n.endswith(".exe") else n


# ---------- 取得程序表 ----------
def _snapshot_windows():
    import ctypes
    from ctypes import wintypes as W

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")

    class PE32(ctypes.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", W.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k32.CreateToolhelp32Snapshot.restype = W.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(PE32)]
    k32.OpenProcess.restype = W.HANDLE
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.CloseHandle.argtypes = [W.HANDLE]
    k32.GetProcessTimes.argtypes = [W.HANDLE] + [ctypes.POINTER(W.FILETIME)] * 4
    ntdll.NtQueryInformationProcess.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.ULONG, ctypes.POINTER(W.ULONG)]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == W.HANDLE(-1).value:
        return []
    rows = []
    try:
        e = PE32()
        e.dwSize = ctypes.sizeof(PE32)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            rows.append({"pid": int(e.th32ProcessID), "ppid": int(e.th32ParentProcessID), "name": e.szExeFile})
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)

    def details(row):
        """建立時間（epoch 秒）與命令列；拿不到（別的使用者、系統程序）就留 None。"""
        h = k32.OpenProcess(0x1000, False, row["pid"])  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return
        try:
            c, x, kt, ut = W.FILETIME(), W.FILETIME(), W.FILETIME(), W.FILETIME()
            if k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(x), ctypes.byref(kt), ctypes.byref(ut)):
                ft = (c.dwHighDateTime << 32) | c.dwLowDateTime
                row["start"] = ft / 1e7 - 11644473600
            need = W.ULONG(0)
            buf = ctypes.create_string_buffer(8192)
            st = ntdll.NtQueryInformationProcess(h, 60, buf, len(buf), ctypes.byref(need))  # ProcessCommandLineInformation
            if st != 0 and 0 < need.value < 1 << 20:
                buf = ctypes.create_string_buffer(need.value)
                st = ntdll.NtQueryInformationProcess(h, 60, buf, len(buf), ctypes.byref(need))
            if st == 0:
                length = ctypes.c_ushort.from_buffer(buf, 0).value
                ptr = ctypes.c_void_p.from_buffer(buf, ctypes.sizeof(ctypes.c_void_p)).value
                if ptr and length:
                    row["cmd"] = ctypes.wstring_at(ptr, length // 2)
        finally:
            k32.CloseHandle(h)

    return rows, details


def _etime_seconds(s: str) -> int:
    """ps 的 etime 欄：[[dd-]hh:]mm:ss → 秒。"""
    days, rest = s.split("-", 1) if "-" in s else ("0", s)
    nums = [int(x) for x in rest.split(":")]
    nums = [0] * (3 - len(nums)) + nums
    return int(days) * 86400 + nums[0] * 3600 + nums[1] * 60 + nums[2]


def _snapshot_posix():
    # 2026-11-12 健檢第一次在 CI 的 macos-latest 跑：原本用 etimes（只有 Linux 的 procps 有），macOS 的 ps 直接報錯、回空表，
    # 等於 macOS 上永遠列不出任何程序。改用兩邊都有的 etime（[[dd-]hh:]mm:ss）自己換算；-A 是 POSIX 的「全部程序」。
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,etime=,comm=,args="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return [], lambda r: None
    now = time.time()
    rows = []
    for ln in out.splitlines():
        parts = ln.split(None, 4)
        if len(parts) < 4:
            continue
        try:
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "start": now - _etime_seconds(parts[2]), "name": parts[3],
                         "cmd": parts[4] if len(parts) > 4 else parts[3]})
        except ValueError:
            continue
    return rows, lambda r: None


def snapshot():
    """回 (程序列 [{pid, ppid, name}], details(row) 補 start／cmd 的函式)。"""
    if os.name == "nt":
        try:
            r = _snapshot_windows()
            return r if isinstance(r, tuple) else (r, lambda _r: None)
        except Exception:  # noqa: BLE001
            return [], lambda _r: None
    return _snapshot_posix()


# ---------- 判定 ----------
_EVAL = re.compile(r"&& eval '(.*)' < /dev/null", re.S)


def short_cmd(cmd: str, width: int = 160) -> str:
    """Bash 工具的命令列外面包了 source snapshot … eval '…'，只留真正的指令。"""
    cmd = cmd or ""
    m = _EVAL.search(cmd)
    if m:
        cmd = m.group(1).replace("'\\\"'\\\"'", "'").replace('\\"', '"')
    cmd = " ".join(cmd.split())
    return cmd if len(cmd) <= width else cmd[: width - 1] + "…"


def find_session_root(rows, start_pid=None):
    """對話程序 PID：CLAUDE_PID，否則從 start_pid（預設自己）往上找名稱 claude 的祖先；找不到回 None。"""
    env = os.environ.get("CLAUDE_PID")
    by = {r["pid"]: r for r in rows}
    if env and env.isdigit() and int(env) in by:
        return int(env)
    cur = by.get(start_pid or os.getpid())
    seen = set()
    while cur and cur["pid"] not in seen:
        seen.add(cur["pid"])
        if _base(cur["name"]) == "claude":
            return cur["pid"]
        cur = by.get(cur["ppid"])
    return None


def ancestors(rows, pid):
    by = {r["pid"]: r for r in rows}
    out, cur = set(), by.get(pid)
    while cur and cur["pid"] not in out:
        out.add(cur["pid"])
        cur = by.get(cur["ppid"])
    return out


def _tool_shell(r, details) -> bool:
    """這個程序是不是 Claude 工具開的殼：名稱在 SHELLS，或是命令列含 LAUNCHER_MARKER 的 cmd.exe（不收使用者自己的 cmd）。"""
    b = _base(r["name"])
    if b in SHELLS:
        return True
    if b == "cmd":
        details(r)
        return LAUNCHER_MARKER in (r.get("cmd") or "")
    return False


def _parent_gone(r, by, details) -> bool:
    """上層已不在：父 PID 不在程序表，或父 PID 被較新的程序重用（父程序建立時間比子程序晚；稽核 TA-12）。"""
    p = by.get(r["ppid"])
    if p is None:
        return True
    details(r)
    details(p)
    return r.get("start") is not None and p.get("start") is not None and p["start"] > r["start"]


def leftovers(rows, details, root_pid, min_minutes=60.0, now=None, exclude=None, cwd_hint=None):
    """工具指令開出、跑超過 min_minutes 的程序群組：[{pid, name, minutes, cmd, children:[{pid,name,cmd}], orphan}]。
    root_pid 為 None 時只看「上層已不在、命令列含 cwd_hint」的工具殼。"""
    now = now or time.time()
    exclude = exclude or set()
    kids: dict[int, list] = {}
    by = {r["pid"]: r for r in rows}
    for r in rows:
        kids.setdefault(r["ppid"], []).append(r)
    tops = []
    if root_pid is not None:
        tops = [(r, False) for r in kids.get(root_pid, []) if _tool_shell(r, details)]
    for r in rows:  # 上層已不在的工具殼：對話關了還留著
        if r["ppid"] == root_pid or not _tool_shell(r, details) or not _parent_gone(r, by, details):
            continue
        details(r)
        c = r.get("cmd") or ""
        if ("shell-snapshots" in c or LAUNCHER_MARKER in c) and (not cwd_hint or cwd_hint.replace("\\", "/").lower() in c.replace("\\", "/").lower()):
            tops.append((r, True))
    out = []
    for top, orphan in tops:
        if top["pid"] in exclude:
            continue
        details(top)
        if top.get("start") is None:
            continue
        mins = (now - top["start"]) / 60
        if mins < min_minutes:
            continue
        desc, stack = [], list(kids.get(top["pid"], []))
        while stack and len(desc) < 50:
            c = stack.pop()
            details(c)
            desc.append({"pid": c["pid"], "name": c["name"], "cmd": short_cmd(c.get("cmd") or c["name"], 100)})
            stack.extend(kids.get(c["pid"], []))
        out.append({"pid": top["pid"], "name": top["name"], "minutes": int(mins), "cmd": short_cmd(top.get("cmd") or top["name"]),
                    "children": desc, "orphan": orphan})
    return sorted(out, key=lambda g: -g["minutes"])


def session_leftovers(min_minutes=None, cwd=None):
    rows, details = snapshot()
    if not rows:
        return []
    if min_minutes is None:
        min_minutes = float(load_cfg(cwd)["minMinutes"])
    root = find_session_root(rows)
    return leftovers(rows, details, root, min_minutes, exclude=ancestors(rows, os.getpid()), cwd_hint=cwd)


def fmt(groups, limit=5) -> str:
    parts = []
    for g in groups[:limit]:
        h, m = divmod(g["minutes"], 60)
        age = f"{h} 小時 {m} 分" if h else f"{m} 分"
        kid = "；子程序 " + "、".join(f"{c['name']} {c['pid']}" for c in g["children"][:4]) if g["children"] else ""
        parts.append(f"PID {g['pid']} {g['name']}（已跑 {age}{'，對話已結束' if g['orphan'] else ''}）：{g['cmd']}{kid}")
    more = f"（另有 {len(groups) - limit} 組）" if len(groups) > limit else ""
    return "；".join(parts) + more


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="列出這場對話的工具指令開出、跑很久的程序（只列不殺）")
    ap.add_argument("--min-minutes", type=float)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    g = session_leftovers(a.min_minutes, os.getcwd())
    if a.json:
        print(json.dumps(g, ensure_ascii=False, indent=1))
        return 0
    lim = a.min_minutes if a.min_minutes is not None else load_cfg()["minMinutes"]
    if not g:
        print(f"沒有跑超過 {lim:g} 分鐘的工具指令程序（{(time.time() - t0) * 1000:.0f} ms）")
        return 0
    print(f"跑超過 {lim:g} 分鐘的工具指令程序 {len(g)} 組（對照仍在跑的背景任務／agent；已結束的留下的是殘留，告訴使用者 PID，由使用者決定，不自動結束）：")
    for x in g:
        print("  " + fmt([x]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
