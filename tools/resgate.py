#!/usr/bin/env python3
"""重型工作記憶體閘門＋延後清單（agent 與主對話共用同一套；只用標準庫）。

使用者 2026-11-09：「等 10 分鐘還不夠就不跑：直接回報「記憶體不足、沒有執行」，由我決定之後再跑。……要寫清楚規則當有其他agent完成時，
要確認記憶體是否足夠了，並開始跑「記憶體不足、沒有執行」的任務。然後先設固定 3GB就好，提醒就不用了，記憶體門檻要用成視窗可更改的。」

門檻唯一來源：dispatch-config.json 的 resourceGate（minFreeMemGB／waitMinutes／pollSeconds；專案 .claude/dispatch-config.json 優先，
設定視窗可改 minFreeMemGB）。延後清單唯一一份：<CLAUDE_HOME>/state/deferred-jobs.json（全部專案共用，每筆記專案）。

用法（重型＝回測、全套測試、build、影片轉逐字稿）：
  python resgate.py check                                   # 可用記憶體 ≥ 門檻 exit 0，否則 exit 1
  python resgate.py wait --project <路徑> --desc "<工作>" --rerun "<怎麼重跑>"
        # 不足就每 pollSeconds 秒看一次、最多等 waitMinutes 分鐘；夠了 exit 0 開跑；仍不足 exit 1、印「記憶體不足、沒有執行」並登記延後清單
        # （Bash 工具前景跑要 timeout 600000；最後一次檢查在 waitMinutes 前 15 秒，不會被 10 分鐘上限砍掉）
  python resgate.py list                                    # 延後清單（依登記順序）
  python resgate.py next                                    # 記憶體夠且清單有項目：印最早一筆 exit 0；否則 exit 1
  python resgate.py done <編號>                              # 開始重跑後從清單移除
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

DEFAULTS = {"minFreeMemGB": 3.0, "waitMinutes": 10.0, "pollSeconds": 60.0}
GB = 1024 ** 3


def claude_home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def deferred_path():
    return os.path.join(claude_home(), "state", "deferred-jobs.json")


def load_cfg(cwd=None):
    """resourceGate：全域 dispatch-config.json → 專案 .claude/dispatch-config.json（cwd 往上找）覆蓋。"""
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
                t = (json.load(f) or {}).get("resourceGate") or {}
        except Exception:  # noqa: BLE001
            continue
        for k in DEFAULTS:
            if isinstance(t.get(k), (int, float)) and not isinstance(t.get(k), bool) and t[k] > 0:
                cfg[k] = float(t[k])
    return cfg


def free_gb():
    """可用實體記憶體（GB）；讀不到回 None（當作不擋）。"""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.ullAvailPhys / GB
            return None
        with open("/proc/meminfo", encoding="utf-8") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) * 1024 / GB
    except Exception:  # noqa: BLE001
        return None
    try:  # macOS 等：可用頁數 × 頁大小
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / GB
    except (ValueError, OSError, AttributeError):
        return None


def enough(cfg=None, free=None):
    """(夠不夠, 可用 GB, 門檻 GB)。讀不到記憶體當作夠（不因量不到就卡住工作）。"""
    cfg = cfg or load_cfg()
    free = free_gb() if free is None else free
    return (free is None or free >= cfg["minFreeMemGB"]), free, cfg["minFreeMemGB"]


# ---------- 延後清單 ----------
def load_jobs(path=None):
    try:
        with open(path or deferred_path(), encoding="utf-8") as f:
            d = json.load(f) or {}
        return d if isinstance(d.get("items"), list) else {"version": 1, "nextId": 1, "items": []}
    except Exception:  # noqa: BLE001
        return {"version": 1, "nextId": 1, "items": []}


def save_jobs(d, path=None):
    path = path or deferred_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def defer(project, desc, rerun, free=None, need=None, agent=None, path=None):
    d = load_jobs(path)
    n = int(d.get("nextId") or 1)
    item = {"id": n, "project": os.path.abspath(project) if project else "", "desc": desc, "rerun": rerun or "",
            "agent": agent or "", "registeredAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "freeGB": round(free, 2) if isinstance(free, (int, float)) else None, "needGB": need}
    d["items"].append(item)
    d["nextId"] = n + 1
    save_jobs(d, path)
    return item


def done(job_id, path=None):
    d = load_jobs(path)
    before = len(d["items"])
    d["items"] = [x for x in d["items"] if int(x.get("id", -1)) != int(job_id)]
    save_jobs(d, path)
    return len(d["items"]) < before


def wait(cfg, sleep=time.sleep, clock=time.monotonic, probe=free_gb):
    """不足就每 pollSeconds 看一次、最多 waitMinutes 分鐘（最後一次檢查留 15 秒餘裕）。回 (夠不夠, 最後一次可用 GB, 等了幾秒)。"""
    t0 = clock()
    deadline = t0 + max(0.0, cfg["waitMinutes"] * 60 - 15)
    while True:
        free = probe()
        if free is None or free >= cfg["minFreeMemGB"]:
            return True, free, clock() - t0
        left = deadline - clock()
        if left <= 0:
            return False, free, clock() - t0
        sleep(min(cfg["pollSeconds"], left))


def _fmt(x):
    return "量不到" if x is None else f"{x:.1f} GB"


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="重型工作記憶體閘門與延後清單")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    w = sub.add_parser("wait")
    for p in (w, sub.add_parser("defer")):
        p.add_argument("--project", default=os.getcwd())
        p.add_argument("--desc", required=p is not w)
        p.add_argument("--rerun", default="")
        p.add_argument("--agent", default="")
    sub.add_parser("list").add_argument("--json", action="store_true")
    sub.add_parser("next")
    sub.add_parser("done").add_argument("id", type=int)
    a = ap.parse_args(argv)
    cfg = load_cfg(getattr(a, "project", None))
    if a.cmd == "check":
        ok, free, need = enough(cfg)
        print(f"可用記憶體 {_fmt(free)}，門檻 {need:g} GB → {'可以開跑' if ok else '不足'}")
        return 0 if ok else 1
    if a.cmd == "wait":
        ok, free, waited = wait(cfg)
        if ok:
            print(f"可用記憶體 {_fmt(free)} ≥ {cfg['minFreeMemGB']:g} GB，可以開跑（等了 {waited / 60:.0f} 分）")
            return 0
        msg = f"記憶體不足、沒有執行（可用 {_fmt(free)} < {cfg['minFreeMemGB']:g} GB，已等 {waited / 60:.0f} 分）"
        if a.desc:
            it = defer(a.project, a.desc, a.rerun, free, cfg["minFreeMemGB"], a.agent)
            msg += f"；已登記延後清單 #{it['id']}（{deferred_path()}）"
        print(msg)
        return 1
    if a.cmd == "defer":
        it = defer(a.project, a.desc, a.rerun, free_gb(), cfg["minFreeMemGB"], a.agent)
        print(f"已登記延後清單 #{it['id']}：{it['desc']}")
        return 0
    if a.cmd == "list":
        items = load_jobs()["items"]
        if a.json:
            print(json.dumps(items, ensure_ascii=False, indent=1))
        elif not items:
            print("延後清單是空的")
        else:
            for x in items:
                print(f"#{x['id']} {x['registeredAt']} {x['project']}：{x['desc']}｜重跑：{x.get('rerun') or '（未寫）'}")
        return 0
    if a.cmd == "next":
        items = load_jobs()["items"]
        if not items:
            print("延後清單是空的")
            return 1
        ok, free, need = enough(load_cfg(items[0].get("project") or None))
        if not ok:
            print(f"延後清單 {len(items)} 項，但可用記憶體 {_fmt(free)} < {need:g} GB，先不跑")
            return 1
        x = items[0]
        print(f"可用記憶體 {_fmt(free)} ≥ {need:g} GB → 開跑 #{x['id']}（{x['project']}）：{x['desc']}｜重跑：{x.get('rerun') or '（未寫）'}"
              f"｜開跑後 `resgate.py done {x['id']}`，跑一個再查一次")
        return 0
    if a.cmd == "done":
        print("已移除" if done(a.id) else f"清單裡沒有 #{a.id}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
