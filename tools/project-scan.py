#!/usr/bin/env python3
"""專案盤點掃描（claude-dev-system 通用版，只用標準庫）。

目的：讓 Claude 開工時不用一個檔一個檔讀就掌握專案骨架；產出兩份東西：
  1. docs/PROJECT-INVENTORY.md  人看的盤點：檔案分類統計、入口、最大的檔、循環依賴、被引用最多的模組、設定檔、無法判定的檔。
  2. .claude/project-scan.json  機器用的索引：每個檔的 sha256、行數、類別；--check 時比對哪些檔變了（索引過期就重驗，不無條件信舊結果）。
用法：
  python project-scan.py <root> [--out docs/PROJECT-INVENTORY.md] [--json .claude/project-scan.json] [--max-lines 800] [--min-files 10]
  python project-scan.py <root> --check          # 只比對：列出新增／刪除／改過的檔，有變動 exit 1
  python project-scan.py <root> --summary        # 只印一行摘要（規則用來判定「算不算專案」）
支援：Python（import 解析）與 JS／TS（借同目錄 depgraph.py）。其他語言只做分類與大小統計。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def is_link_dir(path) -> bool:
    """目錄連結（symlink 或 Windows junction）＝不跟隨。唯一來源：project-scan、depgraph、cleanup、usage_guard hook 都用這個判斷。
    0.16.0：Windows 的 os.walk 會走進 junction（os.path.islink 對 junction 回 False，Python 3.14 實測），
    Stock-web worktree 裡 12 個 .cache 子目錄是 junction 指回主目錄資料；只靠資料夾名稱排除擋不住改名的連結。讀不到就當連結（不進去）。"""
    try:
        if os.path.islink(path):
            return True
        isj = getattr(os.path, "isjunction", None)  # Python 3.12+
        return bool(isj and isj(path))
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
        dns[:] = [d for d in dns if d not in EXCLUDE_DIRS and not d.startswith(".git") and prefix + d not in ignored_dirs
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


def _count_lines_bytes(data: bytes) -> int:
    """與 count_lines 同一個算法（逐行讀的行數）：換行數，最後一行沒換行也算一行。"""
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def count_lines(p: Path) -> int | None:
    try:
        with p.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return None


# ---------- Python import 圖 ----------
PY_IMPORT = re.compile(r"^\s*(?:from\s+([.\w]+)\s+import\s+([^\n#]+)|import\s+([\w.]+))", re.M)


def py_graph(root: Path, files: list[str], texts: dict | None = None) -> dict[str, set[str]]:
    mods = {}
    for rel in files:
        if rel.endswith(".py"):
            m = rel[:-3].replace("/", ".")
            if m.endswith(".__init__"):
                m = m[:-9]
            mods[m] = rel
    g: dict[str, set[str]] = {rel: set() for rel in mods.values()}
    for mod, rel in mods.items():
        text = (texts or {}).get(rel)
        if text is None:
            try:
                text = (root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        pkg = mod.rsplit(".", 1)[0] if "." in mod else ""
        for m in PY_IMPORT.finditer(text):
            name = m.group(1) or m.group(3)
            if not name:
                continue
            if name.startswith("."):
                dots = len(name) - len(name.lstrip("."))
                base = pkg.split(".") if pkg else []
                base = base[: max(0, len(base) - (dots - 1))]
                rest = name.lstrip(".")
                cand = ".".join([*base, rest]) if rest else ".".join(base)
            else:
                cand = name
            # `from X import a, b`：a、b 可能是子模組（X.a），先試子模組再試 X 本身
            subs = [t.strip().split(" as ")[0].strip(" ()") for t in (m.group(2) or "").split(",") if t.strip()] if m.group(1) else []
            for s_ in subs:  # 子模組：每個都算一條邊
                c = f"{cand}.{s_}"
                if s_ and s_ != "*" and c in mods and mods[c] != rel:
                    g[rel].add(mods[c])
            for c in (cand, cand.rsplit(".", 1)[0] if "." in cand else ""):  # 模組本身（或其上層套件）
                if c and c in mods and mods[c] != rel:
                    g[rel].add(mods[c])
                    break

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
def entry_points(root: Path) -> list[str]:
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
    return out


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
            texts[rel] = data.decode("utf-8", "replace")
        files[rel] = {"sha256": h, "size": size, "mtime": st.st_mtime_ns, "lines": lines, "kind": kind, "ext": p.suffix.lower()}
    src = [r for r, f in files.items() if f["kind"] in ("source", "test", "script")]
    g = py_graph(root, src, texts)
    g.update(ts_graph(root, src, texts))
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
            "languages": _lang_counts(files), "entryPoints": entry_points(root), "files": files, "graphEdges": sum(len(v) for v in g.values()),
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
        return sha256(p) != old["sha256"]
    except OSError:
        return True


def check(root: Path, json_path: Path, ignore: set | None = None) -> int:
    try:
        old = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print(f"沒有索引 {json_path}，先跑一次完整盤點")
        return 2
    now = {p.relative_to(root).as_posix(): p for p in walk(root)
           if not (ignore and p.relative_to(root).as_posix() in ignore) and classify(p.relative_to(root).as_posix()) != "asset"}
    old["files"] = {r: f for r, f in old["files"].items() if f.get("kind") != "asset"}  # 舊版索引可能還存著資源檔，忽略
    added = sorted(set(now) - set(old["files"]))
    removed = sorted(set(old["files"]) - set(now))
    changed = sorted(r for r in set(now) & set(old["files"]) if _changed(now[r], old["files"][r]))
    print(f"索引 {old['generatedAt']}：新增 {len(added)}、刪除 {len(removed)}、改過 {len(changed)}")
    for label, items in (("新增", added), ("刪除", removed), ("改過", changed)):
        for r in items[:50]:
            print(f"  {label} {r}")
    return 1 if (added or removed or changed) else 0


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
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    if not root.is_dir():
        print(f"不是資料夾：{root}")
        return 2
    json_path = root / a.json
    ignore = {Path(a.json).as_posix(), Path(a.out).as_posix()}
    if a.check:
        return check(root, json_path, ignore)
    d = scan(root, a.max_lines, ignore)
    if a.summary:
        n = d["counts"]["source"] + d["counts"]["test"]
        is_git = (root / ".git").exists()
        print(f"原始碼檔 {n}（門檻 {a.min_files}）、git {'有' if is_git else '無'}、專案 CLAUDE.md {'有' if (root / 'CLAUDE.md').exists() else '無'}、"
              f"索引 {'有' if json_path.exists() else '無'}、問題 {len(d['problems'])} → {'算專案' if (n >= a.min_files or is_git) else '不算專案（小腳本資料夾）'}")
        return 0
    out = root / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_md(d), encoding="utf-8")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"盤點完成：{out}；索引 {json_path}；問題 {len(d['problems'])} 項、循環 {len(d['cycles'])} 組、原始碼 {d['counts']['source']} 檔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
