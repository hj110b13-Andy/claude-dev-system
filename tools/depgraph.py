"""模組依賴圖與循環依賴檢查（claude-dev-system 通用版；來源 Stock-web scripts/audit/depgraph.py）。

適用 JS／TS 專案（.ts .tsx .js .jsx .mjs）。不寫死路徑，全部用參數：
  python depgraph.py <root>                          # 掃 <root>，印摘要
  python depgraph.py <root> --alias @/=<root>        # 路徑別名（可多次；沒給就讀 root 的 tsconfig／jsconfig，再沒有才 @/ 指向 root）
  python depgraph.py <root> --json out.json          # 另存完整圖
  python depgraph.py <root> --max-cycle-files 59     # 循環內檔數超過門檻就 exit 1（當推送前閘門）
  python depgraph.py <root> --forbid lib:app,components  # 分層規則：路徑含 /lib/ 的檔不可引用含 /app/ 或 /components/ 的檔
只看靜態 import／export from／動態 import()／require()；外部套件只統計名稱；--exclude-dir（預設 __tests__,node_modules）不計入。
檔案走訪、忽略清單（EXCLUDE_DIRS、.gitignore、worktree 與巢狀 checkout、目錄連結）、別名解析、Tarjan 都用同資料夾 project-scan.py 的同一份實作
（唯一來源，與盤點的循環結果一致）。root 不存在 exit 2。
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

IMPORT_RE = re.compile(
    r'^\s*(?:import|export)\b[^;]*?\bfrom\s*["\']([^"\']+)["\']'
    r'|^\s*import\s*["\']([^"\']+)["\']'
    r'|\bimport\(\s*["\']([^"\']+)["\']\s*\)'
    r'|\brequire\(\s*["\']([^"\']+)["\']\s*\)',
    re.M,
)


EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs")
EXCLUDE = ("__tests__", "node_modules")
ALIASES: dict = {}


_SCAN = None


def scan_mod():
    """唯一來源：同資料夾 project-scan.py（walk、is_link_dir、ts_aliases、tarjan）。載入一次後重用；
    載入失敗就讓錯誤浮出來（不放第二份備案實作——兩份實作漂移就是 TB-03 的根因）。"""
    global _SCAN
    if _SCAN is None:
        spec = importlib.util.spec_from_file_location("cds_project_scan_dep", Path(__file__).resolve().parent / "project-scan.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _SCAN = mod
    return _SCAN


def aliases_for(root: str, alias_args=None) -> dict:
    """路徑別名：--alias 有給就只用給的；沒給就讀 root 的 tsconfig／jsconfig（project-scan.ts_aliases），再沒有才 @/ → root。"""
    if alias_args:
        return dict(x.split("=", 1) for x in alias_args)
    return scan_mod().ts_aliases(Path(root))


def collect_files(root: str, exclude=None) -> list:
    """root 底下的 JS／TS 檔：走訪交給 project-scan.walk（EXCLUDE_DIRS 如 node_modules／.next／worktrees、.gitignore、巢狀 checkout、
    目錄連結都不進去）；exclude（預設 __tests__、node_modules）再依 root 以下的資料夾名稱排除。"""
    exclude = tuple(exclude or EXCLUDE)
    rootp = root.replace(os.sep, "/").rstrip("/")
    out = []
    for p in scan_mod().walk(Path(root)):
        rel = p.relative_to(root).as_posix()
        if rel.endswith(EXTS) and not any(x in rel.split("/")[:-1] for x in exclude):
            out.append(f"{rootp}/{rel}")
    return sorted(out)


def resolve(src: str, spec: str, fset: set, root: str, aliases=None):
    aliases = aliases if aliases is not None else (ALIASES or {"@/": root})
    base = None
    for pre, target in aliases.items():
        if spec.startswith(pre):
            base = target.rstrip("/") + "/" + spec[len(pre):]
            break
    if base is None:
        if not spec.startswith("."):
            return None
        base = os.path.normpath(os.path.join(os.path.dirname(src), spec)).replace(os.sep, "/")
    for c in [base] + [base + e for e in EXTS] + [base + "/index" + e for e in EXTS]:
        if c in fset:
            return c
    # TS 的 ESM 寫法：原始碼裡寫 ./b.js，實際檔案是 b.ts／b.tsx（TB-09）
    if base.endswith((".js", ".jsx", ".mjs")):
        stem = base[: base.rindex(".")]
        for e in (".ts", ".tsx"):
            if stem + e in fset:
                return stem + e
    return None


def build_graph(root: str, exclude=None, aliases=None, files=None, texts=None):
    """files：呼叫端已過濾好的檔案清單（絕對路徑、/ 分隔），給了就不自己遍歷（project-scan 用它，worktree、.next 不會混進來）；
    texts：{路徑: 內容}，已讀過的不再開檔。"""
    root = root.replace(os.sep, "/").rstrip("/")
    files = sorted(files) if files is not None else collect_files(root, exclude)
    fset = set(files)
    g: dict[str, set] = defaultdict(set)
    ext: dict[str, set] = defaultdict(set)
    unreadable = []
    for f in files:
        text = (texts or {}).get(f)
        if text is None:
            try:
                # utf-8-sig：有 BOM 的檔第一行 import 才解析得到；replace：非 UTF-8 的檔（註解是 cp950 等）照樣讀 import，與 project-scan 一致
                with open(f, encoding="utf-8-sig", errors="replace") as fh:
                    text = fh.read()
            except Exception as e:  # noqa: BLE001
                unreadable.append((f, str(e)))
                continue
        for m in IMPORT_RE.finditer(text):
            spec = next(x for x in m.groups() if x)
            al = aliases if aliases is not None else (ALIASES or {"@/": root})
            r = resolve(f, spec, fset, root, al)
            if r:
                g[f].add(r)
            elif not spec.startswith(".") and not any(spec.startswith(p) for p in al):
                pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
                ext[pkg].add(f)
    return files, g, ext, unreadable


def tarjan_sccs(files, g):
    """循環（強連通分量，>1 個檔）：演算法用 project-scan.tarjan（唯一來源），這裡只依 files 的順序餵圖、結果依檔數由大到小排。"""
    sccs = scan_mod().tarjan({f: set(g.get(f, ())) for f in files})
    sccs.sort(key=len, reverse=True)
    return sccs


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="src")
    ap.add_argument("--alias", action="append", default=[], help="前綴=目錄，例如 @/=src")
    ap.add_argument("--exclude-dir", default=",".join(EXCLUDE))
    ap.add_argument("--forbid", action="append", default=[], help="分層規則 來源層:目標層1,目標層2")
    ap.add_argument("--json")
    ap.add_argument("--max-cycle-files", type=int)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    a.root = a.root.replace(os.sep, "/").rstrip("/")
    if not os.path.isdir(a.root):  # root 打錯時原本掃到 0 個檔、0 個循環、exit 0，閘門永遠通過
        print(f"不是資料夾：{a.root}")
        sys.exit(2)
    aliases = aliases_for(a.root, a.alias)
    files, g, ext, unreadable = build_graph(a.root, a.exclude_dir.split(","), aliases)
    sccs = tarjan_sccs(files, g)
    indeg: dict = defaultdict(int)
    for f in files:
        for w in g[f]:
            indeg[w] += 1
    strip = lambda p: p[len(a.root) + 1 :] if p.startswith(a.root + "/") else p  # noqa: E731
    cyc_files = sum(len(s) for s in sccs)
    print(f"檔案 {len(files)}、邊 {sum(len(v) for v in g.values())}、循環 {len(sccs)} 組共 {cyc_files} 檔")
    for s in sccs[:10]:
        print(f"  循環 {len(s)} 檔：", ", ".join(strip(x) for x in s[:12]), "..." if len(s) > 12 else "")
    print(f"被最多模組依賴（in-degree）前 {a.top}：")
    for f, n in sorted(indeg.items(), key=lambda x: -x[1])[: a.top]:
        print(f"  {n:4d} {strip(f)}")
    print(f"依賴最多模組（out-degree）前 {a.top}：")
    for f in sorted(files, key=lambda x: -len(g[x]))[: a.top]:
        print(f"  {len(g[f]):4d} {strip(f)}")
    for rule in a.forbid:
        src_layer, targets = rule.split(":", 1)
        tl = [x for x in targets.split(",") if x]
        viol = [(f, w) for f in files if f"/{src_layer}/" in f for w in g[f] if any(f"/{x}/" in w for x in tl)]
        print(f"分層違規 {src_layer} -> {'／'.join(tl)}：{len(viol)}")
        for s, d in viol[:10]:
            print("   ", strip(s), "->", strip(d))
    print("外部套件：", ", ".join(sorted(ext, key=lambda k: -len(ext[k]))))
    if unreadable:
        print("無法讀取：", unreadable)
    if a.json:
        json.dump(
            {"root": a.root, "files": files, "edges": {k: sorted(v) for k, v in g.items()}, "cycles": sccs,
             "external": {k: sorted(v) for k, v in ext.items()}},
            open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=0,
        )
        print("已存", a.json)
    if a.max_cycle_files is not None and cyc_files > a.max_cycle_files:
        print(f"❌ 循環內檔數 {cyc_files} 超過門檻 {a.max_cycle_files}")
        sys.exit(1)


if __name__ == "__main__":
    main()
