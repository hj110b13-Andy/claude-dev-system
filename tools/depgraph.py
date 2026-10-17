"""模組依賴圖與循環依賴檢查（claude-dev-system 通用版；來源 Stock-web scripts/audit/depgraph.py）。

適用 JS／TS 專案（.ts .tsx .js .jsx .mjs）。不寫死路徑，全部用參數：
  python depgraph.py <root>                          # 掃 <root>，印摘要
  python depgraph.py <root> --alias @/=<root>        # 路徑別名（可多次；預設 @/ 指向 root）
  python depgraph.py <root> --json out.json          # 另存完整圖
  python depgraph.py <root> --max-cycle-files 59     # 循環內檔數超過門檻就 exit 1（當推送前閘門）
  python depgraph.py <root> --forbid lib:app,components  # 分層規則：路徑含 /lib/ 的檔不可引用含 /app/ 或 /components/ 的檔
只看靜態 import／export from／動態 import()；外部套件只統計名稱；--exclude-dir（預設 __tests__,node_modules）不計入。
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

IMPORT_RE = re.compile(
    r'^\s*(?:import|export)\b[^;]*?\bfrom\s*["\']([^"\']+)["\']'
    r'|^\s*import\s*["\']([^"\']+)["\']'
    r'|\bimport\(\s*["\']([^"\']+)["\']\s*\)',
    re.M,
)


EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs")
EXCLUDE = ("__tests__", "node_modules")
ALIASES: dict = {}


def collect_files(root: str, exclude=None) -> list:
    exclude = tuple(exclude or EXCLUDE)
    out = []
    for d, _, fs in os.walk(root):
        parts = d.replace(os.sep, "/").split("/")
        if any(x in parts for x in exclude):
            continue
        for f in fs:
            if f.endswith(EXTS):
                out.append(os.path.join(d, f).replace(os.sep, "/"))
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
    return None


def build_graph(root: str, exclude=None, aliases=None):
    root = root.replace(os.sep, "/").rstrip("/")
    files = collect_files(root, exclude)
    fset = set(files)
    g: dict[str, set] = defaultdict(set)
    ext: dict[str, set] = defaultdict(set)
    unreadable = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
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
    sys.setrecursionlimit(20000)
    index: dict = {}
    low: dict = {}
    stack: list = []
    on_stack: set = set()
    sccs: list[list] = []
    counter = [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in g[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                sccs.append(sorted(comp))

    for v in files:
        if v not in index:
            visit(v)
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
    aliases = dict(x.split("=", 1) for x in a.alias) if a.alias else {"@/": a.root}
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
