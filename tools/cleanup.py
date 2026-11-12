#!/usr/bin/env python3
"""安全清理（只用標準庫）：預設只列清單與可省空間（dry-run），加 --apply 才刪。

起因（2026-11-08 Stock-web）：一次清出約 14 GB（已收工的 worktree、Claude 對話暫存 3.8 GB、npm cache、.next）。
刪 worktree 前發現裡面有 12 個 .cache 子目錄是 junction 指回主目錄的資料——直接遞迴刪會把主資料一起刪掉。

項目（--only 可選，逗號分隔）：
  worktrees  已收工的 git worktree：沒有未提交變更、而且分支內容已在主分支才刪。0.27.0 起寧可少刪，這些情況一律保留：
             有被 git 忽略的檔（輸出、.env 等；可重建的快取如 node_modules、.next 不算）｜分支沒有自己的 commit、與主分支同一個 SHA
             （剛建好或還在進行中）｜--keep-hours 小時內有檔案變動（可能還在用）。判斷「已在主分支」依序：
             ①SHA 是主分支的祖先 ②把分支合併進主分支不會改變任何檔（git merge-tree，內容比對；`git pull --rebase` 改寫 merge 後 SHA 不同也認得）
             ③git 太舊沒有 merge-tree 時才用 `git cherry`（patch-id）全部已在。判不出就保留。
             刪除時先拆掉資料夾裡的目錄連結（junction／symlink，只拆連結、不跟隨），再 `git worktree remove`（不加 --force）。分支預設保留（--delete-branch 才刪）。
             .claude/worktrees/ 底下沒登記的資料夾只列出、不刪。
  temp       Claude 對話暫存（<TEMP>/claude）底下非目前對話、超過 --keep-hours 小時沒動過的資料夾
             （只排除「目前這場」；別場還開著但閒置超過門檻的對話也會被列出，刪之前確認）。
  npm        npm cache（`npm cache clean --force`；npx 套件不動）。
  cache      --project 的可重建快取：.next、.turbo、node_modules/.cache、.pytest_cache、.mypy_cache、.ruff_cache、coverage（不含 .cache：很多專案把資料放那）。
被系統鎖住、刪不掉的檔照實列出，不重試、不硬刪。
用法：
  python cleanup.py --project <專案路徑>                 # 只列清單
  python cleanup.py --project <專案路徑> --apply         # 真的刪
  python cleanup.py --only temp,npm --apply
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CACHE_DIRS = (".next", ".turbo", "node_modules/.cache", ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage")
ALL = ("worktrees", "temp", "npm", "cache")
HASH_DIR = re.compile(r"^[0-9a-f]{16}$")
# worktree 裡被 git 忽略、但「可重建」不算珍貴的資料夾名稱：CACHE_DIRS 的最後一段＋node_modules、__pycache__（後兩個是 0.27.0 自己加的，
# 不然所有裝過套件的 worktree 都因 node_modules 永遠不能清，失去這支工具的原意）。其餘被忽略的檔（輸出、.env）一律保留。
# 審查 RV-04：原本取 CACHE_DIRS 每項的最後一段，`node_modules/.cache` 會變成 `.cache`——worktree 裡真的放資料的 `.cache` 就不受保護了
# （本檔 cache 類的說明寫「不含 .cache：很多專案把資料放那」）；node_modules 底下的 .cache 已由 node_modules 涵蓋，所以只收不含斜線的項。
REBUILDABLE = {c for c in CACHE_DIRS if "/" not in c} | {"node_modules", "__pycache__"}
# 被忽略但由 build／tsc 自動重產的檔（Next.js 的 next-env.d.ts、tsc 增量編譯的 *.tsbuildinfo）：有它們不算「有珍貴資料」，
# 否則跑過 build 的 Next.js／TS worktree 永遠清不掉（實測 Stock-web 的 worktree 就是只剩這兩個）。
REBUILDABLE_FILES = ("*.tsbuildinfo", "next-env.d.ts")


def _is_link_dir_fallback(path) -> bool:
    try:
        return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda _p: False)(path))
    except OSError:
        return True


def _load_is_link_dir():
    """唯一來源：同資料夾 project-scan.py 的 is_link_dir；載入失敗才用同樣判斷的備案。"""
    try:
        spec = importlib.util.spec_from_file_location("cds_project_scan_cleanup", Path(__file__).resolve().parent / "project-scan.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod.is_link_dir
    except Exception:  # noqa: BLE001
        return _is_link_dir_fallback


is_link_dir = _load_is_link_dir()


def is_link(path) -> bool:
    return os.path.islink(path) or is_link_dir(path)


# ---------- 不跟隨連結的走訪、大小、刪除 ----------
def scan_tree(path):
    """(位元組數, 最新修改時間, 連結清單)；連結本身不進去、不算大小。"""
    total, newest, links = 0, 0.0, []
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            newest = max(newest, os.lstat(d).st_mtime)
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            if is_link(e.path):
                links.append(e.path)
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                else:
                    st = e.stat(follow_symlinks=False)
                    total += st.st_size
                    newest = max(newest, st.st_mtime)
            except OSError:
                continue
    return total, newest, links


def remove_link(path, errors) -> bool:
    """只拆連結本身（junction／目錄 symlink 用 rmdir，檔案 symlink 用 unlink），絕不碰連結指向的內容。"""
    for fn in (os.rmdir, os.unlink) if os.path.isdir(path) else (os.unlink, os.rmdir):
        try:
            fn(path)
            return True
        except OSError:
            continue
    errors.append(f"拆不掉連結 {path}")
    return False


def safe_rmtree(path, errors) -> None:
    """遞迴刪除但不跟隨任何連結；鎖住的檔記進 errors、不重試。唯讀屬性（git 物件常見）先取消唯讀再刪一次，那不算重試。"""
    if is_link(path):
        remove_link(path, errors)
        return
    try:
        entries = list(os.scandir(path))
    except OSError as e:
        errors.append(f"{path}：{e.strerror or e}")
        return
    for e in entries:
        if is_link(e.path):
            remove_link(e.path, errors)
            continue
        try:
            is_dir = e.is_dir(follow_symlinks=False)
        except OSError:
            is_dir = False
        if is_dir:
            safe_rmtree(e.path, errors)
            continue
        try:
            os.unlink(e.path)
        except PermissionError as ex:
            try:
                if not (os.lstat(e.path).st_mode & stat.S_IWRITE):
                    os.chmod(e.path, stat.S_IWRITE)
                    os.unlink(e.path)
                    continue
            except OSError:
                pass
            errors.append(f"{e.path}：{ex.strerror or ex}（可能被程式鎖住）")
        except OSError as ex:
            errors.append(f"{e.path}：{ex.strerror or ex}")
    try:
        os.rmdir(path)
    except OSError as ex:
        if os.path.exists(path):
            errors.append(f"{path}：{ex.strerror or ex}")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


# ---------- git ----------
def git(repo, *args, timeout=60):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout)
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError) as e:
        return 99, "", str(e)


def worktrees(repo):
    rc, out, _ = git(repo, "worktree", "list", "--porcelain")
    if rc != 0:
        return []
    items, cur = [], {}
    for ln in out.splitlines() + [""]:
        if not ln.strip():
            if cur:
                items.append(cur)
            cur = {}
            continue
        k, _, v = ln.partition(" ")
        cur[k] = v if v else True
    return items


def ignored_precious(status_lines):
    """git status --porcelain --ignored 的輸出裡，被忽略（!!）且不是可重建快取的路徑（輸出、.env 之類，刪掉就沒了）。"""
    out = []
    for ln in status_lines:
        if not ln.startswith("!! "):
            continue
        rel = ln[3:].strip().strip(chr(34)).rstrip("/")
        parts = [x for x in rel.replace(chr(92), "/").split("/") if x]
        if parts and any(fnmatch.fnmatch(parts[-1], pat) for pat in REBUILDABLE_FILES):
            continue
        if not any(x in REBUILDABLE for x in parts):
            out.append(rel)
    return out


def _has_real_files(path) -> bool:
    """path 底下（不跟隨連結）有沒有真的檔。path 本身是連結、不存在、或只含連結與空資料夾 → False。"""
    if is_link(path) or not os.path.lexists(path):
        return False
    if not os.path.isdir(path):
        return True
    try:
        entries = list(os.scandir(path))
    except OSError:
        return True  # 讀不到就當有（寧可保留）
    return any(_has_real_files(e.path) for e in entries)


def has_own_commits(repo, branch):
    """分支有沒有自己 commit 過：看 reflog 有沒有 `commit` 開頭的紀錄（剛 worktree add 的分支只有「branch: Created from」）。
    讀不到回 False（當作沒有 → 呼叫端保留，寧可少刪）。"""
    if not branch:
        return False
    rc, out, _ = git(repo, "reflog", "show", "--format=%gs", f"refs/heads/{branch}")
    return rc == 0 and any(ln.startswith("commit") for ln in out.splitlines())


def merged_reason(repo, main, head):
    """分支內容已在主分支 → 回理由字串；判不出或沒合併回 None（保留）。"""
    if git(repo, "merge-base", "--is-ancestor", head, main)[0] == 0:
        return "SHA 已在主分支"
    rc, out, err = git(repo, "merge-tree", "--write-tree", main, head)
    if rc in (0, 1) and out.strip():
        if rc == 0:
            tree = out.split()[0]
            rc2, mt, _ = git(repo, "rev-parse", f"{main}^{{tree}}")
            if rc2 == 0 and mt.strip() == tree:
                return "合併進主分支不會改變任何檔（內容已在主分支；rebase 改寫過 SHA 也認得）"
        return None  # merge-tree 可用：內容不同或有衝突 → 沒合併
    rc, out, _ = git(repo, "cherry", main, head)  # 舊版 git 沒有 merge-tree --write-tree
    if rc == 0 and all(ln.startswith("-") for ln in out.splitlines() if ln.strip()):
        return "每個 commit 的 patch-id 都已在主分支（git cherry）"
    return None


def _same_path_key(p) -> str:
    """同一個資料夾的比對鍵：git 回 C:/Users/runneradmin/…（長檔名、正斜線），暫存路徑可能是 RUNNER~1 這種 8.3 短檔名、反斜線；
    realpath 換成實際長路徑再 normcase（0.16.1：GitHub Actions 上已登記的 worktree 被當成「沒登記」）。"""
    try:
        return os.path.normcase(os.path.realpath(str(p)))
    except OSError:
        return os.path.normcase(os.path.abspath(str(p)))


def plan_worktrees(repo: Path, main=None, keep_hours=None, now=None):
    """keep_hours 給了才加「最近這麼多小時內有檔案變動就保留」（命令列一律給；沿用 --keep-hours，不另立數字）。"""
    now = now or time.time()
    items = []
    wts = worktrees(repo)
    if not wts:
        return items
    main_wt = wts[0]
    main = main or (str(main_wt.get("branch", "")).replace("refs/heads/", "") or "HEAD")
    registered = set()
    for w in wts[1:]:
        path = Path(str(w.get("worktree")))
        registered.add(_same_path_key(path))
        br = str(w.get("branch", "")).replace("refs/heads/", "")
        head = br or str(w.get("HEAD", ""))
        it = {"kind": "worktrees", "path": str(path), "branch": br, "size": 0, "action": "keep", "why": ""}
        if w.get("prunable") or not path.exists():
            it.update(action="prune", why="資料夾已不在，只清 git 的登記（git worktree prune）")
        elif w.get("locked"):
            it["why"] = "已鎖定（git worktree lock）"
        else:
            rc, st, _ = git(path, "status", "--porcelain", "--ignored")
            size, newest, links = scan_tree(str(path))
            it["size"], it["links"] = size, links
            lines = [ln for ln in st.splitlines() if ln.strip()]
            dirty = [ln for ln in lines if not ln.startswith("!! ")]
            # 被忽略的路徑如果是連結、或裡面只有連結沒有真的檔（例如 worktree 的 .cache/backtest 是指向主目錄資料的 junction），不算珍貴：
            # 刪 worktree 前只拆連結、不動目標，沒有東西會消失
            precious = [r for r in ignored_precious(lines) if _has_real_files(os.path.join(str(path), r))]
            age_h = (now - newest) / 3600 if newest else 1e9
            same_sha = git(repo, "rev-parse", head)[1].strip() == git(repo, "rev-parse", main)[1].strip() != ""
            if rc != 0:
                it["why"] = "讀不到狀態，保留"
            elif dirty:
                it["why"] = f"有未提交變更 {len(dirty)} 個檔"
            elif precious:
                shown = "、".join(precious[:3]) + ("…" if len(precious) > 3 else "")
                it["why"] = f"有被 git 忽略的檔（{shown}；刪掉就沒了），保留"
            elif same_sha and not has_own_commits(repo, br):
                it["why"] = "分支與主分支同一個 SHA、沒有自己的 commit（未開始或進行中），保留"
            elif keep_hours is not None and age_h < keep_hours:
                it["why"] = f"{age_h:.0f} 小時內有檔案變動（可能還在用），保留"
            else:
                why = merged_reason(repo, main, head)
                if why:
                    it.update(action="delete", why=why + (f"；先拆 {len(links)} 個目錄連結" if links else ""))
                else:
                    it["why"] = f"分支 {head} 有內容不在 {main}（或判斷不出），保留"
        items.append(it)
    wt_root = repo / ".claude" / "worktrees"
    if wt_root.is_dir():
        for d in sorted(wt_root.iterdir()):
            if d.is_dir() and _same_path_key(d) not in registered:
                size, _n, links = scan_tree(str(d))
                items.append({"kind": "worktrees", "path": str(d), "branch": "", "size": size, "action": "keep",
                              "why": "沒登記成 git worktree 的資料夾，保留（請人工確認內容再刪）"})
    return items


def apply_worktree(repo: Path, it, delete_branch=False):
    errors = []
    if it["action"] == "prune":
        rc, _, err = git(repo, "worktree", "prune")
        return [] if rc == 0 else [err.strip()]
    for ln in it.get("links") or []:
        remove_link(ln, errors)
    if errors:
        return errors  # 連結拆不掉就不往下刪，避免刪到連結指向的資料
    rc, _, err = git(repo, "worktree", "remove", it["path"])
    if rc != 0:
        errors.append(f"git worktree remove 失敗：{err.strip()}（被鎖住的檔請關掉相關程式後再跑）")
        return errors
    git(repo, "worktree", "prune")
    if delete_branch and it.get("branch"):
        rc, _, err = git(repo, "branch", "-D", it["branch"])
        if rc != 0:
            errors.append(f"刪分支 {it['branch']} 失敗：{err.strip()}")
    return errors


# ---------- 對話暫存 ----------
def claude_temp_root():
    return Path(tempfile.gettempdir()) / "claude"


def plan_temp(root: Path, keep_hours=24.0, current=None, now=None):
    now = now or time.time()
    current = current or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    items = []
    if not root.is_dir():
        return items
    cands = []
    for d1 in sorted(root.iterdir()):
        if not d1.is_dir() or is_link(str(d1)):
            continue
        if HASH_DIR.match(d1.name):
            cands.extend(d for d in sorted(d1.iterdir()) if d.is_dir())
        else:
            cands.append(d1)
    for d in cands:
        size, newest, _links = scan_tree(str(d))
        age_h = (now - newest) / 3600 if newest else 1e9
        it = {"kind": "temp", "path": str(d), "size": size, "action": "keep", "why": ""}
        if current and d.name == current:
            it["why"] = "目前這場對話"
        elif age_h < keep_hours:
            it["why"] = f"{age_h:.0f} 小時內動過（可能還在用）"
        else:
            it.update(action="delete", why=f"{age_h / 24:.0f} 天沒動過（可能屬於別場還開著的對話，確認不是「下次繼續」那場再刪）")
        items.append(it)
    return items


# ---------- npm、可重建快取 ----------
def npm_cache_dir():
    npm = shutil.which("npm")
    if npm:
        try:
            r = subprocess.run([npm, "config", "get", "cache"], capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                return Path(r.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "npm-cache" if base else Path.home() / ".npm"


def plan_npm():
    d = npm_cache_dir() / "_cacache"
    if not d.is_dir():
        return []
    size, _n, _l = scan_tree(str(d))
    return [{"kind": "npm", "path": str(d), "size": size, "action": "delete" if shutil.which("npm") else "keep",
             "why": "npm cache clean --force（npx 套件不動）" if shutil.which("npm") else "找不到 npm，保留"}]


def apply_npm(it):
    npm = shutil.which("npm")
    try:
        r = subprocess.run([npm, "cache", "clean", "--force"], capture_output=True, text=True, timeout=600)
        return [] if r.returncode == 0 else [(r.stderr or r.stdout).strip()[-300:]]
    except (OSError, subprocess.SubprocessError, TypeError) as e:
        return [str(e)]


def plan_cache(project: Path):
    items = []
    for rel in CACHE_DIRS:
        p = project / rel
        if p.exists() and not is_link(str(p)) and p.is_dir():
            size, _n, links = scan_tree(str(p))
            items.append({"kind": "cache", "path": str(p), "size": size, "action": "delete",
                          "why": "可重建快取" + (f"（裡面 {len(links)} 個連結只拆不跟隨）" if links else "")})
    return items


# ---------- 主程式 ----------
def build_plan(only, project: Path | None, keep_hours, temp_root=None, main=None):
    items = []
    if "worktrees" in only and project:
        items += plan_worktrees(project, main, keep_hours)
    if "temp" in only:
        items += plan_temp(Path(temp_root) if temp_root else claude_temp_root(), keep_hours)
    if "npm" in only:
        items += plan_npm()
    if "cache" in only and project:
        items += plan_cache(project)
    return items


def apply_plan(items, project: Path | None, delete_branch=False):
    freed, errors = 0, []
    for it in items:
        if it["action"] not in ("delete", "prune"):
            continue
        if it["kind"] == "worktrees":
            errs = apply_worktree(project, it, delete_branch)
        elif it["kind"] == "npm":
            errs = apply_npm(it)
        else:
            errs = []
            safe_rmtree(it["path"], errs)
        it["errors"] = errs
        if not errs:
            freed += it["size"]
        errors += errs
    return freed, errors


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="安全清理：預設只列清單，--apply 才刪")
    ap.add_argument("--project", help="專案路徑（worktrees、cache 兩項需要）")
    ap.add_argument("--only", default=",".join(ALL), help="逗號分隔：" + ",".join(ALL))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--delete-branch", action="store_true", help="worktree 刪掉後也刪它的分支（預設保留）")
    ap.add_argument("--keep-hours", type=float, default=24.0, help="對話暫存與 worktree 幾小時內有檔案變動的不刪（預設 24）")
    ap.add_argument("--claude-temp", help="對話暫存根目錄（預設 <TEMP>/claude）")
    ap.add_argument("--main", help="主分支名稱（預設＝主工作目錄目前的分支）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    bad = only - set(ALL)
    if bad:
        print(f"沒有這些項目：{', '.join(sorted(bad))}（可用 {','.join(ALL)}）")
        return 2
    project = Path(a.project).resolve() if a.project else None
    items = build_plan(only, project, a.keep_hours, a.claude_temp, a.main)
    freed, errors = 0, []
    if a.apply:
        freed, errors = apply_plan(items, project, a.delete_branch)
    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return 1 if a.apply and errors else 0  # 與不加 --json 一致：有刪不掉的回 1（稽核 TA-09）
    total = sum(it["size"] for it in items if it["action"] == "delete")
    empty = [it for it in items if it["kind"] == "temp" and it["size"] == 0 and not it.get("errors")]
    if empty:
        n_del = sum(1 for it in empty if it["action"] == "delete")
        print(f"[temp] 空的對話暫存資料夾 {len(empty)} 個（{'已刪' if a.apply else '會刪'} {n_del} 個，其餘保留）")
    for it in items:
        if any(it is e for e in empty):
            continue
        mark = {"delete": "刪", "prune": "清登記", "keep": "保留"}[it["action"]]
        print(f"[{it['kind']}] {mark} {human(it['size']):>9}  {it['path']}  — {it['why']}")
        for e in it.get("errors") or []:
            print(f"      ✗ {e}")
    if not items:
        print("沒有可清的項目")
    if a.apply:
        print(f"已清出 {human(freed)}；刪不掉 {len(errors)} 項" + ("（照實列在上面，沒有重試硬刪）" if errors else ""))
    else:
        print(f"可省約 {human(total)}（只列清單；確認後加 --apply 才刪）")
    return 1 if a.apply and errors else 0


if __name__ == "__main__":
    sys.exit(main())
