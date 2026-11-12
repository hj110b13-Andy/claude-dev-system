#!/usr/bin/env python3
"""專案盤點掃描（claude-dev-system 通用版，只用標準庫）。

目的：讓 Claude 開工時不用一個檔一個檔讀就掌握專案骨架；產出兩份東西：
  1. docs/PROJECT-INVENTORY.md  人看的盤點：檔案分類統計、入口、最大的檔、循環依賴、被引用最多的模組、設定檔、無法判定的檔。
  2. .claude/project-scan.json  機器用的索引：每個檔的 sha256、行數、類別；--check 時比對哪些檔變了（索引過期就重驗，不無條件信舊結果）。
用法：
  python project-scan.py <root> [--out docs/PROJECT-INVENTORY.md] [--json .claude/project-scan.json] [--max-lines 800] [--min-files 10]
  python project-scan.py <root> --check          # 只比對：列出新增／刪除／改過的檔，有變動 exit 1；索引不存在或內容不合法 exit 2
  python project-scan.py <root> --summary        # 只印一行摘要（規則用來判定「算不算專案」；只數檔案，不雜湊、不建依賴圖）
  python project-scan.py <root> --max-cycles N   # 測試閘門：循環「組數」超過 N exit 1（不寫檔、不受其他檔變動影響）
支援：Python（import 解析）與 JS／TS（借同目錄 depgraph.py）。其他語言只做分類與大小統計。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import re
import subprocess
import sys
import time
from pathlib import Path

EXCLUDE_DIRS = {"node_modules", ".git", "dist", "build", ".venv", "venv", "__pycache__", ".next", "out", "coverage", ".pytest_cache",
                ".mypy_cache", ".idea", ".vscode", "vendor", "third_party", ".cache", "worktrees"}
SOURCE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".cs", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".rb", ".php"}
SCRIPT_EXT = {".ps1", ".cmd", ".bat", ".sh"}
CONFIG_EXT = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".properties"}
DOC_EXT = {".md", ".txt", ".rst"}
ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".mp3", ".mp4", ".wav", ".pdf", ".woff", ".woff2", ".ttf"}
TEST_HINT = re.compile(r"(^|[/_.-])(tests?|__tests__|spec)([/_.-]|$)", re.I)


def classify(rel: str) -> str:
    p = Path(rel)
    ext = p.suffix.lower()
    if TEST_HINT.search(rel) and (ext in SOURCE_EXT or ext in SCRIPT_EXT):
        return "test"
    if rel.startswith(("scripts/", "tools/", "bin/")) and (ext in SOURCE_EXT or ext in SCRIPT_EXT):
        return "script"
    if ext in SOURCE_EXT:
        return "source"
    if ext in SCRIPT_EXT:
        return "script"
    if ext in CONFIG_EXT or p.name in ("Makefile", "Dockerfile", ".gitignore", ".gitattributes", ".editorconfig") or p.name.startswith(".env"):
        return "config"
    if ext in DOC_EXT:
        return "doc"
    if ext in ASSET_EXT:
        return "asset"
    return "other"


def git_ignored(root: Path) -> tuple[set[str], set[str]]:
    """
    專案 .gitignore 排除的檔案與資料夾（暫存、金鑰檔），不算專案內容；不是 git 專案或 git 不能用就回空集合。
    用 git 判斷才吃得到巢狀 .gitignore、全域排除與否定規則，不自己解析。--directory 讓整個被忽略的資料夾只回一筆，大專案也快。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return set(), set()
    if out.returncode != 0:
        return set(), set()
    entries = [e for e in out.stdout.decode("utf-8", "replace").split("\0") if e]
    return {e for e in entries if not e.endswith("/")}, {e.rstrip("/") for e in entries if e.endswith("/")}


JUNCTION_TAG = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)  # Windows junction 的重解析點標記


def is_link_dir(path) -> bool:
    """目錄連結（symlink 或 Windows junction）＝不跟隨。唯一來源：project-scan、depgraph、cleanup、usage_guard hook 都用這個判斷。
    0.16.0：Windows 的 os.walk 會走進 junction（os.path.islink 對 junction 回 False，Python 3.14 實測），
    Stock-web worktree 裡 12 個 .cache 子目錄是 junction 指回主目錄資料；只靠資料夾名稱排除擋不住改名的連結。讀不到就當連結（不進去）。"""
    try:
        if os.path.islink(path):
            return True
        isj = getattr(os.path, "isjunction", None)  # Python 3.12+
        if isj:
            return bool(isj(path))
        # Python 3.10／3.11 沒有 os.path.isjunction：看重解析點的種類（junction 是 MOUNT_POINT）。
        # 2026-11-12 健檢第一次在 CI 用 3.10 跑測試才發現：原本這裡直接回 False，3.10／3.11 上 junction 完全認不出來，
        # cleanup 會跟著 junction 刪到 worktree 外面的資料（4 個連結相關測試在 3.10 失敗；以前 CI 只跑 3.12）。
        # 只認 MOUNT_POINT，不認所有重解析點：OneDrive 等雲端資料夾也是重解析點，不可當成連結跳過。
        return getattr(os.lstat(path), "st_reparse_tag", 0) == JUNCTION_TAG
    except OSError:
        return True


def walk(root: Path):
    """專案自己的檔案（唯一的遍歷：盤點、依賴圖、--check 都吃這份清單）。
    不算：EXCLUDE_DIRS、.gitignore 排除的、目錄連結（junction／symlink，不跟隨），以及巢狀 git checkout——
    子資料夾裡有 .git（worktree 的 .git 是檔、巢狀 repo／submodule 是資料夾）就是另一份 checkout，整個跳過
    （0.16.0：Stock-web 11/8 盤點「被引用最多」出現 .claude/worktrees/agent-xxx/scripts/eval/types.ts 被 104 個檔引用）。"""
    ignored_files, ignored_dirs = git_ignored(root)
    first = True
    for dp, dns, fns in os.walk(root):
        if not first and (".git" in dns or ".git" in fns):
            dns[:] = []
            continue
        first = False
        rel_dir = Path(dp).relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        # 只排除 .git 本身：原本 startswith(".git") 連 .github（CI 工作流程）、.gitlab-ci 之類資料夾都排掉（TB-06）
        dns[:] = [d for d in dns if d not in EXCLUDE_DIRS and d != ".git" and prefix + d not in ignored_dirs
                  and not is_link_dir(os.path.join(dp, d))]
        for fn in fns:
            if prefix + fn in ignored_files:
                continue
            p = Path(dp) / fn
            try:
                if p.is_symlink():
                    continue
            except OSError:
                continue
            yield p


COUNT_SOURCE_EXT = SOURCE_EXT | SCRIPT_EXT  # 「算不算專案」數的副檔名：程式碼加腳本（與 hooks/usage_guard.py 的 PA_SOURCE_EXT 相同）


def count_code_files(root, limit: int = 3000, budget_sec: float = 0.5) -> tuple[int, bool]:
    """快速數原始碼檔（「算不算專案」的唯一判定來源）：回 (原始碼檔數, 是否被截斷)。
    規則照 hooks/usage_guard.py 的 _pa_count_sources：os.walk(root)；資料夾名在 EXCLUDE_DIRS 或以「.」開頭的不進去；
    每個檔都算一次「看過」，副檔名（不分大小寫）在 COUNT_SOURCE_EXT 才算原始碼；看過 limit 個檔或超過 budget_sec 秒就停並回 True
    （夠判定「算不算專案」了，大專案不必數完）。不判斷 .gitignore、不跳過連結（hook 現況）。
    注意與 scan() 的 counts 不同：那邊用 classify() 分類，且遵守 walk() 的全部排除規則，數字不拿來判定專案。"""
    n = seen = 0
    t0 = time.time()
    for _dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for fn in fns:
            seen += 1
            if os.path.splitext(fn)[1].lower() in COUNT_SOURCE_EXT:
                n += 1
            if seen >= limit or time.time() - t0 > budget_sec:
                return n, True
    return n, False


def _count_lines_bytes(data: bytes) -> int:
    """行數（唯一的算法）：換行數，最後一行沒換行也算一行。"""
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------- Python import 圖 ----------
# 0.27.0（TB-04）：改成「路徑解析」——匯入名稱換成檔案路徑再比對檔案清單，才分得出 src/ 版面、腳本資料夾（sys.path[0]）、
# __init__.py 的相對匯入層數，以及括號多行、逗號並列的匯入。
PY_FROM = re.compile(r"^[ \t]*from[ \t]+([.\w]+)[ \t]+import[ \t]+(\([^)]*\)|[^\n]+)", re.M)
PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([^\n]+)", re.M)
PY_DOTTED = re.compile(r"^[\w.]+$")


def _import_names(raw: str) -> list[str]:
    """`from x import` 後面的名稱清單：'a, b as c' 或 '(' 換行 'a,  # 註解' 換行 'b,' 換行 ')' → ['a', 'b']；去掉註解與 as 別名。"""
    raw = re.sub(r"#[^\n]*", "", raw).split(";")[0].replace("(", " ").replace(")", " ").replace(chr(92), " ")
    out = []
    for part in raw.split(","):
        t = part.split()
        if t:
            out.append(t[0])
    return out


def _plain_import_names(raw: str) -> list[str]:
    """`import a, b as c, d.e` → ['a', 'b', 'd.e']。任何一段不像模組名（句子、docstring 裡的 import 字樣）就停，不猜。"""
    out = []
    for part in re.sub(r"#[^\n]*", "", raw).split(";")[0].split(","):
        t = part.split()
        if not t or not PY_DOTTED.match(t[0]) or len(t) not in (1, 3) or (len(t) == 3 and t[1] != "as"):
            break
        out.append(t[0])
    return out


def _py_paths(base: str, dotted: str) -> list[str]:
    """base 資料夾底下的 dotted 模組可能對到的檔案（模組檔、套件的 __init__.py）；dotted 空＝base 這個套件本身。"""
    if not dotted:
        return [f"{base}/__init__.py" if base else "__init__.py"]
    p = "/".join(x for x in (base, dotted.replace(".", "/")) if x)
    return [p + ".py", p + "/__init__.py"]


def _py_find(bases: list[str], dotted: str, fset: set[str], prefix_ok: bool) -> str | None:
    """在 bases 之下找 dotted 對到的檔；prefix_ok 時 a.b.c 找不到會退而找 a.b、a（import a.b.c 一定先載入上層套件）。"""
    parts = dotted.split(".") if dotted else []
    for k in range(len(parts), (1 if prefix_ok else len(parts)) - 1, -1):
        for b in bases:
            for c in _py_paths(b, ".".join(parts[:k])):
                if c in fset:
                    return c
    return None


def py_graph(root: Path, files: list[str], texts: dict | None = None) -> dict[str, set[str]]:
    pyfiles = [rel for rel in files if rel.endswith(".py")]
    fset = set(pyfiles)
    has_src = any(rel.startswith("src/") for rel in pyfiles)
    g: dict[str, set[str]] = {rel: set() for rel in pyfiles}
    for rel in pyfiles:
        text = (texts or {}).get(rel)
        if text is None:
            try:
                text = (root / rel).read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
        here = rel.rsplit("/", 1)[0] if "/" in rel else ""  # 這個檔所在資料夾
        # 絕對匯入的搜尋根：專案根、src/ 版面、以及「腳本所在資料夾」（python 直接執行腳本時 sys.path[0]）——
        # 後者只給不是套件的資料夾（沒有 __init__.py）：套件內的模組不會把自己的資料夾放進 sys.path
        bases = [""] + (["src"] if has_src else [])
        if here not in bases and (f"{here}/__init__.py") not in fset:
            bases.append(here)

        def add(target: str | None) -> None:
            if target and target != rel:
                g[rel].add(target)

        for m in PY_FROM.finditer(text):
            name, names = m.group(1), _import_names(m.group(2))
            if name.startswith("."):
                dots = len(name) - len(name.lstrip("."))
                pkgdir = here
                for _ in range(dots - 1):  # 每多一個點往上一層資料夾（__init__.py 與一般模組同樣以「所在資料夾」當套件）
                    pkgdir = pkgdir.rsplit("/", 1)[0] if "/" in pkgdir else ""
                search, rest, prefix_ok = [pkgdir], name.lstrip("."), False
            else:
                search, rest, prefix_ok = bases, name, True
            main = _py_find(search, rest, fset, prefix_ok)
            subs = {n: _py_find(search, f"{rest}.{n}" if rest else n, fset, False) for n in names if n != "*"}
            for t in subs.values():  # 子模組：每個都算一條邊
                add(t)
            # 套件本身（__init__.py）只在「有名稱不是子模組」（定義在 __init__ 裡的東西）或 import * 時才算一條邊；
            # 否則 `from . import b` 會與 __init__.py 的 `from .a import f` 湊成假循環
            if main and (not names or "*" in names or any(t is None for t in subs.values())):
                add(main)
        for m in PY_IMPORT.finditer(text):
            for name in _plain_import_names(m.group(1)):
                add(_py_find(bases, name, fset, True))
    return g


def tarjan(g: dict[str, set[str]]) -> list[list[str]]:
    index, low, on, st, out = {}, {}, set(), [], []
    counter = [0]
    sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))

    def visit(v):
        index[v] = low[v] = counter[0]; counter[0] += 1
        st.append(v); on.add(v)
        for w in g.get(v, ()):
            if w not in index:
                visit(w); low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = st.pop(); on.discard(w); comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))
    for v in list(g):
        if v not in index:
            visit(v)
    return out


def _strip_jsonc(text: str) -> str:
    """tsconfig／jsconfig 是 JSONC：去掉字串外的 // 與 /* */ 註解、物件與陣列結尾多餘的逗號。"""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def ts_aliases(root: Path) -> dict[str, str]:
    """路徑別名：讀 tsconfig.json／jsconfig.json 的 compilerOptions.paths（＋baseUrl），只收 `前綴/*` 型；沒有設定 @/ 才用舊預設 @/→root。
    0.16.0：原本寫死 @/→root，Next.js 慣例 `"@/*": ["./src/*"]` 解析不到，Stock-web src/ 底下所有 @/ 引用都沒算進依賴圖。"""
    rootp = root.as_posix().rstrip("/")
    al: dict[str, str] = {}
    for name in ("tsconfig.json", "jsconfig.json"):
        try:
            d = json.loads(_strip_jsonc((root / name).read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001  沒有或解析不了就換下一個
            continue
        co = d.get("compilerOptions") or {}
        base = os.path.normpath(os.path.join(rootp, co.get("baseUrl") or ".")).replace(os.sep, "/")
        for key, targets in (co.get("paths") or {}).items():
            if not key.endswith("/*") or not isinstance(targets, list) or not targets or not str(targets[0]).endswith("*"):
                continue
            tgt = os.path.normpath(os.path.join(base, str(targets[0])[:-1] or ".")).replace(os.sep, "/")
            al.setdefault(key[:-1], tgt)
        if al:
            break
    al.setdefault("@/", rootp)
    return dict(sorted(al.items(), key=lambda kv: -len(kv[0])))  # 長前綴先比


def ts_graph(root: Path, files: list[str] | None = None, texts: dict | None = None):
    """JS／TS 依賴圖。files＝walk 過濾後的相對路徑，不另外遍歷（0.16.0 以前 depgraph 自己 os.walk 整個 root，
    .claude/worktrees、.next 全算進去：Stock-web 多讀 2,600+ 檔，每條邊再做兩次 Path.resolve）。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import depgraph  # type: ignore
        rootp = root.as_posix().rstrip("/")
        abs_files = None if files is None else [f"{rootp}/{r}" for r in files if r.endswith(depgraph.EXTS)]
        abs_texts = {f"{rootp}/{r}": t for r, t in (texts or {}).items()}
        fs, g, _ext, _ = depgraph.build_graph(rootp, None, ts_aliases(root), files=abs_files, texts=abs_texts)
        n = len(rootp) + 1
        return {f[n:]: {x[n:] for x in g.get(f, ())} for f in fs if f.startswith(rootp + "/")}
    except Exception:  # noqa: BLE001
        return {}


# ---------- 入口 ----------
MAIN_GUARD = re.compile(r"^if[ \t]+__name__[ \t]*==[ \t]*[\"']__main__[\"'][ \t]*:", re.M)
MAX_MAIN_ENTRIES = 20


def entry_points(root: Path, texts: dict | None = None, files: dict | None = None) -> list[str]:
    """入口：package.json／固定檔名，加上有 `if __name__ == "__main__":` 守衛的檔（TB-05）。
    守衛只從呼叫端已讀進來的 texts 判斷（不重讀檔）；files 給了就排除測試檔（unittest.main() 不是專案入口）；最多列 MAX_MAIN_ENTRIES 個。"""
    out = []
    pj = root / "package.json"
    if pj.exists():
        try:
            d = json.loads(pj.read_text(encoding="utf-8"))
            for k in ("main", "module", "bin"):
                if d.get(k):
                    out.append(f"package.json {k}: {d[k]}")
            for k, v in (d.get("scripts") or {}).items():
                out.append(f"npm run {k}: {v}")
        except Exception:  # noqa: BLE001
            out.append("package.json 無法解析")
    for name in ("pyproject.toml", "setup.py", "Makefile", "manifest.json", "docker-compose.yml", "Dockerfile"):
        if (root / name).exists():
            out.append(name)
    for name in ("main.py", "app.py", "__main__.py", "src/main.py", "src/index.ts", "src/app/layout.tsx", "src/app/page.tsx", "index.html"):
        if (root / name).exists():
            out.append(name)
    mains = sorted(r for r, t in (texts or {}).items()
                   if r.endswith(".py") and not (files and files.get(r, {}).get("kind") == "test") and MAIN_GUARD.search(t))
    out.extend(f"{r}（有 __main__ 守衛）" for r in mains[:MAX_MAIN_ENTRIES])
    return out


def build_dep_graph(root: Path, src: list[str], texts: dict) -> dict[str, set[str]]:
    """依賴圖的唯一建法：Python 的 py_graph＋JS／TS 的 ts_graph（scan 與 --max-cycles 都走這裡）。"""
    g = py_graph(root, src, texts)
    g.update(ts_graph(root, src, texts))
    return g


def scan(root: Path, max_lines: int, ignore: set | None = None) -> dict:
    files = {}
    unreadable = []
    texts: dict[str, str] = {}
    assets = 0  # 資源檔（圖片、影片、PDF、字型）只計數：不雜湊、不進索引，否則一個有幾千張截圖的資料夾索引會變 700 KB、每次 --check 都重算
    for p in walk(root):
        rel = p.relative_to(root).as_posix()
        if ignore and rel in ignore:  # 自己產出的盤點與索引不計入，否則剛掃完 --check 就說「新增 2 個檔」
            continue
        kind = classify(rel)
        if kind == "asset":
            assets += 1
            continue
        # 0.16.0：每個檔只開一次（雜湊、行數、依賴解析共用同一份內容）。Stock-web 實測 open() 每次約 3 ms（防毒即時掃描），
        # 原本雜湊、數行、depgraph 各開一次，共 12,156 次 open 佔 48 秒裡的 36 秒。
        try:
            st = p.stat()
            size = st.st_size
            if size < 50_000_000:
                data = p.read_bytes()
                h = hashlib.sha256(data).hexdigest()
            else:
                data, h = None, sha256(p)
        except OSError:
            unreadable.append(rel)
            continue
        lines = _count_lines_bytes(data) if data is not None and kind in ("source", "test", "script", "config", "doc") and size < 5_000_000 else None
        if data is not None and kind in ("source", "test", "script") and size < 2_000_000:
            texts[rel] = data.decode("utf-8-sig", "replace")  # -sig：有 BOM 的檔第一行 import 才解析得到（TB-09）
        files[rel] = {"sha256": h, "size": size, "mtime": st.st_mtime_ns, "lines": lines, "kind": kind, "ext": p.suffix.lower()}
    src = [r for r, f in files.items() if f["kind"] in ("source", "test", "script")]
    g = build_dep_graph(root, src, texts)
    cycles = tarjan(g)
    dependents: dict[str, int] = {}
    for a, deps in g.items():
        for b in deps:
            dependents[b] = dependents.get(b, 0) + 1
    # 0.13.1：腳本（scripts/、tools/）也算——Stock-web 重整後盤點寫「超過 800 行 0 個」，scripts/backtest/exitStrategy.ts 卻有 6,588 行
    #（研究／回測腳本每天加分支，長得比產品碼快）。測試檔不算。
    big = sorted(((f["lines"], r) for r, f in files.items() if f["kind"] in ("source", "script") and f["lines"]), reverse=True)
    problems = []
    for n, r in big:
        if n > max_lines:
            tag = "（腳本）" if files[r]["kind"] == "script" else ""
            problems.append({"kind": "big-file", "file": r, "detail": f"{n} 行 > {max_lines}{tag}"})
    for cyc in cycles:
        problems.append({"kind": "cycle", "files": cyc, "detail": f"{len(cyc)} 個檔互相依賴"})
    hot = sorted(dependents.items(), key=lambda kv: -kv[1])[:10]
    n_src = sum(1 for f in files.values() if f["kind"] == "source")
    n_test = sum(1 for f in files.values() if f["kind"] == "test")
    if n_src >= 10 and n_test == 0:
        problems.append({"kind": "no-tests", "detail": f"{n_src} 個原始碼檔、0 個測試檔"})
    return {"version": 2, "root": str(root), "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "maxLines": max_lines,
            "counts": {**{k: sum(1 for f in files.values() if f["kind"] == k) for k in ("source", "test", "script", "config", "doc", "other")}, "asset": assets},
            "languages": _lang_counts(files), "entryPoints": entry_points(root, texts, files), "files": files, "graphEdges": sum(len(v) for v in g.values()),
            "cycles": cycles, "mostDepended": hot, "biggest": [(r, n) for n, r in big[:10]], "problems": problems, "unreadable": unreadable,
            "refactorDecision": None}


def _lang_counts(files: dict) -> dict:
    out: dict[str, int] = {}
    for f in files.values():
        if f["kind"] in ("source", "test"):
            out[f["ext"]] = out.get(f["ext"], 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def render_md(d: dict) -> str:
    c = d["counts"]
    L = [f"# 專案盤點（project-scan.py 產生，{d['generatedAt']}）", "",
         f"原始碼 {c['source']}、測試 {c['test']}、腳本 {c['script']}、設定 {c['config']}、文件 {c['doc']}、資源 {c['asset']}、其他 {c['other']}；"
         f"語言：{', '.join(f'{k} {v}' for k, v in d['languages'].items()) or '無'}；依賴邊 {d['graphEdges']}。", "",
         "## 入口與啟動方式", *([f"- {e}" for e in d["entryPoints"]] or ["- （沒找到 package.json／pyproject／main 類入口，請人工確認）"]), "",
         "## 最大的檔（行數）", *[f"- {r}：{n} 行" for r, n in d["biggest"]], "",
         "## 循環依賴", *([f"- {len(cyc)} 個檔：{', '.join(cyc)}" for cyc in d["cycles"]] or ["- 無"]), "",
         "## 被引用最多的模組（改到要走 cds-blast-radius）", *([f"- {r}：被 {n} 個檔引用" for r, n in d["mostDepended"]] or ["- 無依賴資訊"]), "",
         "## 問題清單（門檻：單檔 > %d 行、循環依賴、≥10 個原始碼檔卻沒有測試）" % d["maxLines"],
         *([f"- {p['kind']}：{p.get('file') or ', '.join(p.get('files', []))} — {p['detail']}" for p in d["problems"]] or ["- 無"]), "",
         "## 無法讀取的檔", *([f"- {u}" for u in d["unreadable"]] or ["- 無"]), "",
         "## 設定檔", *[f"- {r}" for r, f in sorted(d["files"].items()) if f["kind"] == "config"][:40], "",
         "每個檔的雜湊在 `.claude/project-scan.json`；`python project-scan.py <root> --check` 列出自上次盤點後改過的檔。"]
    return "\n".join(L) + "\n"


def _changed(p: Path, old: dict) -> bool:
    """大小與修改時間（奈秒）都和索引相同就當沒改（同 git 的做法），不重算雜湊；舊索引沒有 mtime 或有差異才比 sha256。"""
    try:
        st = p.stat()
        if old.get("mtime") is not None and st.st_mtime_ns == old["mtime"] and st.st_size == old.get("size"):
            return False
        return sha256(p) != old.get("sha256")
    except OSError:
        return True


def _atomic_write(path: Path, text: str) -> None:
    """先寫暫存檔再 os.replace：寫到一半被中斷（或兩個程序同時寫）不會留下半個索引，之後 --check 讀到壞 JSON（TB-10）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _load_index(json_path: Path):
    """讀索引；回 (dict, None)，讀不到或內容不是盤點索引回 (None, 訊息)。內容檢查：要有 files 且每筆是物件。"""
    try:
        old = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None, f"沒有索引 {json_path}，先跑一次完整盤點"
    if not isinstance(old, dict) or not isinstance(old.get("files"), dict) or not all(isinstance(f, dict) for f in old["files"].values()):
        return None, f"索引 {json_path} 內容不完整（缺 files 或格式不對），先重跑一次完整盤點"
    return old, None


def check(root: Path, json_path: Path, ignore: set | None = None) -> int:
    """比對索引：有新增／刪除／改過的檔回 1，沒變動 0，索引不存在或內容不合法回 2（不與「有變動」同碼）。"""
    old, err = _load_index(json_path)
    if old is None:
        print(err)
        return 2
    now = {p.relative_to(root).as_posix(): p for p in walk(root)
           if not (ignore and p.relative_to(root).as_posix() in ignore) and classify(p.relative_to(root).as_posix()) != "asset"}
    old["files"] = {r: f for r, f in old["files"].items() if f.get("kind") != "asset"}  # 舊版索引可能還存著資源檔，忽略
    added = sorted(set(now) - set(old["files"]))
    removed = sorted(set(old["files"]) - set(now))
    changed = sorted(r for r in set(now) & set(old["files"]) if _changed(now[r], old["files"][r]))
    print(f"索引 {old.get('generatedAt', '?')}：新增 {len(added)}、刪除 {len(removed)}、改過 {len(changed)}")
    for label, items in (("新增", added), ("刪除", removed), ("改過", changed)):
        for r in items[:50]:
            print(f"  {label} {r}")
    return 1 if (added or removed or changed) else 0


def cycle_groups(root: Path, ignore: set | None = None) -> list[list[str]]:
    """只算循環（不雜湊、不寫檔）：走訪、讀原始碼、建圖、Tarjan，與 scan 同一套（build_dep_graph、tarjan）。"""
    src, texts = [], {}
    for p in walk(root):
        rel = p.relative_to(root).as_posix()
        if (ignore and rel in ignore) or classify(rel) not in ("source", "test", "script"):
            continue
        src.append(rel)
        try:
            if p.stat().st_size < 2_000_000:
                texts[rel] = p.read_bytes().decode("utf-8-sig", "replace")
        except OSError:
            pass
    return tarjan(build_dep_graph(root, src, texts))


def check_cycles(root: Path, max_cycles: int, ignore: set | None = None) -> int:
    """測試閘門（--max-cycles N）：循環「組數」超過 N 回 1，否則 0；不寫檔、不受其他檔變動影響。
    單位注意：這裡數的是組數；depgraph.py --max-cycle-files 數的是循環內的「檔數」。"""
    cycles = cycle_groups(root, ignore)
    print(f"循環 {len(cycles)} 組（門檻 {max_cycles}）")
    for cyc in cycles[:10]:
        print(f"  {len(cyc)} 個檔：{', '.join(cyc[:12])}{'…' if len(cyc) > 12 else ''}")
    if len(cycles) > max_cycles:
        print(f"循環組數 {len(cycles)} 超過門檻 {max_cycles}")
        return 1
    return 0


def read_problem_count(json_path: Path):
    """--summary 用：從既有索引讀問題數（不重新掃描）；沒有或讀不了回 None。"""
    old, _err = _load_index(json_path)
    if old is None or not isinstance(old.get("problems"), list):
        return None
    return len(old["problems"])


def _carry_over(d: dict, json_path: Path) -> None:
    """重跑盤點前先讀舊索引，把不是掃描算出來的鍵原樣帶過去（TB-01）：
    refactorDecision 是 skill 在使用者回答「要不要分階段重整」後寫進去的（declined＋日期），被清掉就會再問一次；
    其他掃描沒有產生的未知鍵（人或其他工具加的）也一併保留。"""
    try:
        old = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    if not isinstance(old, dict):
        return
    for k, v in old.items():
        if k not in d:
            d[k] = v
    if d.get("refactorDecision") is None and old.get("refactorDecision") is not None:
        d["refactorDecision"] = old["refactorDecision"]


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="專案盤點掃描")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--out", default="docs/PROJECT-INVENTORY.md")
    ap.add_argument("--json", default=".claude/project-scan.json")
    ap.add_argument("--max-lines", type=int, default=800)
    ap.add_argument("--min-files", type=int, default=10, help="--summary 判定「算專案」的原始碼檔數門檻")
    ap.add_argument("--check", action="store_true", help="比對索引：有新增／刪除／改過的檔回 1，索引不存在或內容不合法回 2")
    ap.add_argument("--summary", action="store_true", help="只印一行摘要（只數檔案，不雜湊、不建依賴圖）")
    ap.add_argument("--max-cycles", type=int, metavar="N", help="只檢查循環：循環組數超過 N 回 1（測試閘門用，不寫檔、不受其他檔變動影響）")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    if not root.is_dir():
        print(f"不是資料夾：{root}")
        return 2
    json_path = root / a.json
    ignore = {Path(a.json).as_posix(), Path(a.out).as_posix()}
    if a.max_cycles is not None:
        if a.check or a.summary:
            print("--max-cycles 不能與 --check、--summary 一起用")
            return 2
        return check_cycles(root, a.max_cycles, ignore)
    if a.check:
        return check(root, json_path, ignore)
    if a.summary:
        n, truncated = count_code_files(root)
        is_git = (root / ".git").exists()
        probs = read_problem_count(json_path)
        print(f"原始碼檔 {n}{'+' if truncated else ''}（門檻 {a.min_files}）、git {'有' if is_git else '無'}、專案 CLAUDE.md {'有' if (root / 'CLAUDE.md').exists() else '無'}、"
              f"索引 {'有' if json_path.exists() else '無'}、問題 {'未盤點' if probs is None else probs} → {'算專案' if (n >= a.min_files or is_git) else '不算專案（小腳本資料夾）'}")
        return 0
    d = scan(root, a.max_lines, ignore)
    _carry_over(d, json_path)
    out = root / a.out
    _atomic_write(out, render_md(d))
    _atomic_write(json_path, json.dumps(d, ensure_ascii=False, indent=1))
    print(f"盤點完成：{out}；索引 {json_path}；問題 {len(d['problems'])} 項、循環 {len(d['cycles'])} 組、原始碼 {d['counts']['source']} 檔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
