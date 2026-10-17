"""自動產生模組盤點清單（claude-dev-system 通用版；來源 Stock-web scripts/audit/moduleInventory.py）。

每檔一列：路徑、行數、被依賴數（in）、依賴數（out）、是否在循環內、匯出名稱、檔頭第一句註解。
資料來源：同資料夾 depgraph.py 的圖。重跑即更新；人工補充的職責說明請寫在另一份手寫檔（--notes 指名），不要改本腳本產出的檔。
用法：python moduleInventory.py <root> --out <輸出 md> [--alias @/=<root>] [--notes 手寫職責檔名]
"""
import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from depgraph import build_graph, tarjan_sccs  # noqa: E402

EXPORT_RE = re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:function|const|let|class|type|interface|enum)\s+([A-Za-z0-9_$]+)", re.M)
HEAD_RE = re.compile(r"^\s*(?:/\*\*?|//)\s*([^\n*/][^\n]*)", re.M)


def head_comment(text: str) -> str:
    m = HEAD_RE.search(text[:1500])
    if not m:
        return ""
    s = m.group(1).strip().rstrip("*/").strip()
    return s[:70]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="src")
    ap.add_argument("--out", default="module-inventory.md")
    ap.add_argument("--alias", action="append", default=[])
    ap.add_argument("--notes", default="module-responsibilities.md")
    a = ap.parse_args()
    a.root = a.root.replace(os.sep, "/").rstrip("/")
    aliases = dict(x.split("=", 1) for x in a.alias) if a.alias else {"@/": a.root}
    files, g, ext, unreadable = build_graph(a.root, None, aliases)
    sccs = tarjan_sccs(files, g)
    in_cycle = {f: i + 1 for i, s in enumerate(sccs) for f in s}
    indeg = defaultdict(int)
    for f in files:
        for w in g[f]:
            indeg[w] += 1
    rows = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        rows.append((f, text.count("\n") + 1, indeg[f], len(g[f]), in_cycle.get(f, 0),
                     ", ".join(EXPORT_RE.findall(text)[:6]), head_comment(text)))
    bydir = defaultdict(list)
    for r in rows:
        d = os.path.dirname(r[0])
        bydir[d].append(r)
    out = ["# 模組盤點清單（自動產生，勿手改）", "",
           f"產生方式：`python moduleInventory.py {a.root} --out {a.out}`；不含 __tests__／node_modules。",
           f"共 {len(files)} 檔、{sum(len(v) for v in g.values())} 條 import 邊、{len(sccs)} 組循環（共 {len(in_cycle)} 檔）。",
           "欄位：in＝被幾個模組 import（越大越核心，改動影響越廣）；out＝import 幾個模組（越大職責越雜）；循環＝所屬循環組編號（0＝不在循環）。",
           f"職責說明（人工）：見 `{a.notes}`。", ""]
    for d in sorted(bydir):
        rs = bydir[d]
        out.append(f"## {d}（{len(rs)} 檔，共 {sum(r[1] for r in rs):,} 行）")
        out.append("")
        out.append("| 檔案 | 行 | in | out | 循環 | 匯出（前 6） | 檔頭註解 |")
        out.append("|---|--:|--:|--:|--:|---|---|")
        for f, n, i, o, c, ex, hc in sorted(rs, key=lambda r: -r[2]):
            out.append(f"| {os.path.basename(f)} | {n} | {i} | {o} | {c or ''} | {ex} | {hc.replace('|', '／')} |")
        out.append("")
    if unreadable:
        out.append("## 無法讀取")
        out.extend(f"- {f}：{e}" for f, e in unreadable)
    open(a.out, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"已寫 {a.out}：{len(files)} 檔、{len(bydir)} 個目錄")


if __name__ == "__main__":
    main()
