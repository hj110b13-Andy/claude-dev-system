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
        # （Bash 工具前景跑要 timeout 600000；最後一次檢查在 waitMinutes 前 15 秒——這只保證 wait 本身不會被 10 分鐘上限砍掉）
  python resgate.py run --desc "<工作>" [--project <路徑>] [--rerun "<怎麼重跑>"] -- <指令> [參數…]
        # 優先用這個：先做與 wait 相同的等待；夠了就執行 -- 後面的指令並以它的 exit code 結束；不足就不執行、登記延後清單、exit 1
        # （wait 仍可用，但後面不可接管線：管線的 exit code 是最後一個指令的，閘門 exit 1 會被蓋掉）
        # 注意：run 可能先等最多 waitMinutes 分鐘（預設 10）才開跑，等待時間與工作本身共用呼叫端的時限；
        #       長工作或有前景時限的環境（例如 Bash 工具前景 10 分鐘）請用背景執行，否則等完才開跑的工作會被砍。
        # 指令不經 shell：-- 後面的參數原樣交給作業系統；要用 &&、管線、重導就包一層殼：Windows 寫 `-- pwsh -c "…"`（PATH 裡的 `bash` 可能是 WSL 的，不是 Git Bash；要用 Git Bash 就寫完整路徑），其他平台寫 `-- bash -c "…"`。
        # Windows 的 npm／npx／tsc 等是 .cmd，開跑前用 shutil.which 照 PATHEXT 找到完整路徑（不改成 shell=True）。
  python resgate.py list                                    # 延後清單（依登記順序）
  python resgate.py next                                    # 記憶體夠且清單有項目：印最早一筆 exit 0；否則 exit 1
  python resgate.py done <編號>                              # 開始重跑後從清單移除（清單裡沒有這個編號 exit 1）

--project 給的不是現存路徑（例如只寫專案名稱）時，登記成目前資料夾所在的專案根（git 根目錄）。
延後清單的讀改寫包在作業系統層級的檔案鎖裡（deferred-jobs.json.lock；Windows msvcrt.locking、其他平台 fcntl.flock，
程序結束自動釋放，做法參考 tox-dev/filelock），多場對話同時登記不會丟筆、不會寫壞檔；讀到壞檔先改名
deferred-jobs.json.bad-<時間> 保留再接續，不會無聲清空。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
    except Exception:  # noqa: BLE001
        return None
    try:  # Linux：/proc/meminfo 單獨包起來，讀不到（macOS 沒有這個檔）才走得到下面的 sysconf 後備（稽核 TA-04）
        with open("/proc/meminfo", encoding="utf-8") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) * 1024 / GB
    except Exception:  # noqa: BLE001
        pass
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
# 拿鎖最多等 LOCK_TIMEOUT 秒（派工單 2026-11-12 指定「約 5 秒」）；每 LOCK_POLL 秒試一次（與 tox-dev/filelock
# src/filelock/_api.py acquire 的預設 poll_interval 0.05 相同）。os.replace 遇 PermissionError（Windows 上別的程序
# 正在讀目標檔，例如 hook 直接讀 deferred-jobs.json）短暫重試 REPLACE_TRIES 次（自己加的：20 × 0.05 秒 ≈ 1 秒）。
LOCK_TIMEOUT = 5.0
LOCK_POLL = 0.05
REPLACE_TRIES = 20


class JobsLockError(OSError):
    """拿不到延後清單的檔案鎖（別的程序一直佔著）。"""


def _empty_jobs(next_id=1):
    return {"version": 1, "nextId": next_id, "items": []}


def _read_jobs(path):
    """回 (清單, 原始文字或 None)。原始文字不是 None 表示檔案存在但讀不懂（壞檔）。檔案不存在回空清單。"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return _empty_jobs(), None
    except OSError:
        return _empty_jobs(), None  # 暫時讀不到（例如正被改名）：當成空的，但不算壞檔、不改名
    try:
        d = json.loads(raw)
        if isinstance(d, dict) and isinstance(d.get("items"), list):
            return d, None
    except ValueError:
        pass
    return _empty_jobs(), raw


def load_jobs(path=None):
    """只讀：壞檔時回空清單，不改檔（改名保留在下一次登記／移除時於鎖內進行）。"""
    return _read_jobs(path or deferred_path())[0]


def _salvage_next_id(raw):
    """壞檔裡還看得出的最大編號＋1，讓新編號不與舊編號重複（免得 `done <舊編號>` 刪到新登記的另一筆）。"""
    nums = [int(n) + 1 for n in re.findall(r'"id"\s*:\s*(\d+)', raw or "")]
    nums += [int(n) for n in re.findall(r'"nextId"\s*:\s*(\d+)', raw or "")]
    return max(nums, default=1)


def _quarantine(path, raw):
    """壞檔改名成 <檔名>.bad-<時間> 保留，印一行說明到 stderr；回新的空清單（編號接續）。"""
    bad = path + ".bad-" + time.strftime("%Y%m%d-%H%M%S")
    if os.path.exists(bad):
        bad += f"-{os.getpid()}"
    try:
        os.replace(path, bad)
        where = f"已改名保留為 {bad}"
    except OSError as e:
        where = f"改名保留失敗（{e}），原檔會被新清單覆蓋"
    nid = _salvage_next_id(raw)
    print(f"延後清單檔讀不懂（可能寫到一半被中斷），{where}；從空清單接續，下一個編號 #{nid}", file=sys.stderr, flush=True)
    return _empty_jobs(nid)


@contextlib.contextmanager
def _locked(path):
    """作業系統層級的獨佔鎖（鎖 <path>.lock 的第 1 個位元組；程序結束系統自動釋放，不會留下死鎖）。
    Windows msvcrt.locking(LK_NBLCK)、其他平台 fcntl.flock(LOCK_EX | LOCK_NB)；拿不到就每 LOCK_POLL 秒重試，
    最多 LOCK_TIMEOUT 秒，仍拿不到丟 JobsLockError。鎖檔與資料檔分開：資料檔要被 os.replace，不能被鎖住。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT
    try:
        fd = os.open(path + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        raise JobsLockError(f"開不了鎖檔 {path}.lock：{e}") from e
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)  # msvcrt.locking 從目前位置起算：固定鎖第 0 個位元組
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if time.monotonic() >= deadline:
                    raise JobsLockError(f"{LOCK_TIMEOUT:g} 秒內拿不到延後清單的鎖（{path}.lock）：{e}") from e
                time.sleep(LOCK_POLL)
        try:
            yield
        finally:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass  # 關檔時系統也會釋放
    finally:
        os.close(fd)


def save_jobs(d, path=None):
    """原子寫入：同資料夾唯一的暫存檔（mkstemp）寫好再 os.replace；PermissionError 短暫重試。呼叫端應已持有鎖。"""
    path = path or deferred_path()
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        for i in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == REPLACE_TRIES - 1:
                    raise
                time.sleep(LOCK_POLL)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _update(fn, path=None):
    """在鎖內讀 → fn(清單) → 有改才寫回；fn 回 (結果, 有沒有改)。壞檔先改名保留。"""
    path = path or deferred_path()
    with _locked(path):
        d, raw = _read_jobs(path)
        if raw is not None:
            d = _quarantine(path, raw)
            changed_by_quarantine = True
        else:
            changed_by_quarantine = False
        result, changed = fn(d)
        if changed or changed_by_quarantine:
            save_jobs(d, path)
        return result


def _git_root(path):
    """往上找到 git 根目錄（含 worktree 的 .git 檔）；找不到就用原路徑。回絕對路徑（保留大小寫）。"""
    p = os.path.normpath(os.path.abspath(path or os.getcwd()))
    d = p
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return p
        d = up


def project_root(path):
    """往上找到 git 根目錄（含 worktree 的 .git 檔）；找不到就用原路徑。回正規化、小寫的絕對路徑。"""
    return os.path.normcase(_git_root(path))


def project_path(project, cwd=None):
    """要登記的專案路徑：現存路徑 → 絕對路徑；不存在的相對寫法（例如 `--project claude-dev-system` 只寫名稱）→
    目前資料夾的專案根（原本記成「cwd＼名稱」這種不存在的路徑，list 與 hook 印出來是錯的，稽核 TA-06）；
    不存在的絕對路徑照原樣（使用者明確給的）。空值回空字串。"""
    if not project:
        return ""
    if os.path.exists(project) or os.path.isabs(project):
        return os.path.abspath(project)
    return _git_root(cwd or os.getcwd())


def _under_worktrees(x, y):
    """x 是否在 y 的 .claude/worktrees/ 底下（兩者都已是 project_root 的正規化路徑）。"""
    return x.startswith(os.path.join(y, ".claude", "worktrees") + os.sep)


def same_project(item_project, cwd):
    """延後清單的一筆是不是「這個專案」的：兩邊的專案根（git 根目錄）相同，或其中一邊在另一邊的 .claude/worktrees/ 底下
    （worktree）。沒記專案的當成是。舊紀錄 `--project 名稱` 被記成「cwd＼名稱」（不存在的路徑）→ 用它上一層的專案根比。
    0.26.1：清單是所有專案共用一份，原本提醒與 `next` 不分專案——2026-11-11 claude-dev-system 的對話被叫去跑
    Stock-web 登記的 #15「11f/11g 腳本 tsc」。0.27.0 稽核 TA-05：原本「一個在另一個底下」也算，家目錄登記的工作
    在每個專案都被叫去跑、Stock-web 的工作從上層 Documents\\Claude 也算同專案 → 改成只認同一個專案根或 worktree。
    hook（usage_guard.py）也用這個函式（簽名不可變）。"""
    if not item_project:
        return True
    b = project_root(cwd)
    if os.path.exists(item_project):
        a = project_root(item_project)
    else:
        a = os.path.normcase(os.path.normpath(os.path.abspath(item_project)))
        if project_root(os.path.dirname(a)) == b:  # 舊紀錄「cwd＼名稱」
            return True
    return a == b or _under_worktrees(a, b) or _under_worktrees(b, a)


def defer(project, desc, rerun, free=None, need=None, agent=None, path=None):
    proj = project_path(project)

    def add(d):
        ids = [int(x.get("id")) for x in d["items"] if isinstance(x, dict) and str(x.get("id", "")).isdigit()]
        n = max(int(d.get("nextId") or 1), max(ids, default=0) + 1)
        item = {"id": n, "project": proj, "desc": desc, "rerun": rerun or "",
                "agent": agent or "", "registeredAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "freeGB": round(free, 2) if isinstance(free, (int, float)) else None, "needGB": need}
        d["items"].append(item)
        d["nextId"] = n + 1
        return item, True

    return _update(add, path)


def done(job_id, path=None):
    def rm(d):
        before = len(d["items"])
        d["items"] = [x for x in d["items"] if not (isinstance(x, dict) and str(x.get("id", "")) == str(int(job_id)))]
        return len(d["items"]) < before, len(d["items"]) < before

    return _update(rm, path)


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


def gate(a, cfg, rerun=None):
    """wait 與 run 共用：等記憶體；夠回 0，不足印「記憶體不足、沒有執行」、登記延後清單並回 1。"""
    ok, free, waited = wait(cfg)
    if ok:
        print(f"可用記憶體 {_fmt(free)} ≥ {cfg['minFreeMemGB']:g} GB，可以開跑（等了 {waited / 60:.0f} 分）", flush=True)
        return 0
    msg = f"記憶體不足、沒有執行（可用 {_fmt(free)} < {cfg['minFreeMemGB']:g} GB，已等 {waited / 60:.0f} 分）"
    if a.desc:
        try:
            it = defer(a.project, a.desc, rerun if rerun is not None else a.rerun, free, cfg["minFreeMemGB"], a.agent)
            msg += f"；已登記延後清單 #{it['id']}（{deferred_path()}）"
        except OSError as e:  # 寫檔失敗（鎖逾時、磁碟、權限）也要照樣回報「記憶體不足、沒有執行」，不可變成 traceback（稽核 TA-01）
            msg += f"；登記延後清單失敗（{e}），請自行記下這項工作"
    print(msg, flush=True)
    return 1


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="重型工作記憶體閘門與延後清單")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    w = sub.add_parser("wait")
    r = sub.add_parser("run")
    for p in (w, r, sub.add_parser("defer")):
        p.add_argument("--project", default=os.getcwd())
        p.add_argument("--desc", required=p is not w)
        p.add_argument("--rerun", default="")
        p.add_argument("--agent", default="")
    sub.add_parser("list").add_argument("--json", action="store_true")
    nx = sub.add_parser("next")
    nx.add_argument("--project", help="看哪個專案的延後工作（預設：目前資料夾所在的專案）")
    nx.add_argument("--all", action="store_true", help="不分專案，照登記順序看整份清單")
    sub.add_parser("done").add_argument("id", type=int)
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = []
    if "run" in argv and "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    a = ap.parse_args(argv)
    cfg = load_cfg(getattr(a, "project", None))
    if a.cmd == "check":
        ok, free, need = enough(cfg)
        print(f"可用記憶體 {_fmt(free)}，門檻 {need:g} GB → {'可以開跑' if ok else '不足'}")
        return 0 if ok else 1
    if a.cmd == "wait":
        return gate(a, cfg)
    if a.cmd == "run":
        if not cmd:
            print("用法：resgate.py run --desc \"<工作>\" -- <指令> [參數…]（-- 後面沒有指令，沒有執行）", file=sys.stderr)
            return 2
        rc = gate(a, cfg, a.rerun or subprocess.list2cmdline(cmd))
        if rc:
            return rc
        exe = shutil.which(cmd[0])  # Windows 的 npm／npx／tsc 是 .cmd：CreateProcess 不照 PATHEXT 找，先換成完整路徑（稽核 TA-02；不改 shell=True）
        if exe:
            cmd = [exe] + cmd[1:]
        try:
            return subprocess.call(cmd)
        except OSError as e:
            print(f"指令無法啟動：{e}", file=sys.stderr)
            return 127
    if a.cmd == "defer":
        try:
            it = defer(a.project, a.desc, a.rerun, free_gb(), cfg["minFreeMemGB"], a.agent)
        except OSError as e:
            print(f"登記延後清單失敗：{e}", file=sys.stderr)
            return 1
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
        if not getattr(a, "all", False):
            here = getattr(a, "project", None) or os.getcwd()
            mine = [x for x in items if same_project(x.get("project"), here)]
            if not mine:
                print(f"這個專案沒有延後工作（另有 {len(items)} 項屬於其他專案，由那邊的對話處理；`resgate.py list` 可看）")
                return 1
            items = mine
        ok, free, need = enough(load_cfg(items[0].get("project") or None))
        if not ok:
            print(f"延後清單 {len(items)} 項，但可用記憶體 {_fmt(free)} < {need:g} GB，先不跑")
            return 1
        x = items[0]
        print(f"可用記憶體 {_fmt(free)} ≥ {need:g} GB → 開跑 #{x['id']}（{x['project']}）：{x['desc']}｜重跑：{x.get('rerun') or '（未寫）'}"
              f"｜開跑後 `resgate.py done {x['id']}`，跑一個再查一次")
        return 0
    if a.cmd == "done":
        try:
            removed = done(a.id)
        except OSError as e:
            print(f"移除失敗：{e}", file=sys.stderr)
            return 1
        if not removed:
            print(f"清單裡沒有 #{a.id}", file=sys.stderr)  # 稽核 TA-07：找不到編號回 exit 1
            return 1
        print("已移除")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
