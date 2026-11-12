"""tools/project-scan.py、depgraph.py、moduleInventory.py 的回歸測試（健檢 fix-tools-b：TB-01～TB-12）。
每個測試對應稽核報告的一條，全部用暫存資料夾裡的假專案；不寫真實的 ~/.claude，不碰這個 repo 的索引檔。"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
NL = chr(10)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def write(root: Path, rel: str, text: str = "x = 1", binary: bytes | None = None) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if binary is not None:
        p.write_bytes(binary)
    else:
        p.write_text(text + NL, encoding="utf-8")
    return p


def run_tool(tool: str, *args, cwd=None):
    r = subprocess.run([sys.executable, str(TOOLS / tool), *map(str, args)], capture_output=True, env=ENV, cwd=cwd)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps = load("ps_scan_tests", TOOLS / "project-scan.py")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-scan2-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "proj"
        self.root.mkdir()

    def scan_main(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.ps.main([str(self.root), *args])
        return rc, buf.getvalue()


class IndexKeepsHumanKeys(Base):
    """TB-01：重跑盤點不可把 refactorDecision 清掉（「要不要分階段重整只問一次」靠它）。"""

    def test_refactor_decision_and_unknown_keys_survive_rescan(self):
        write(self.root, "a.py")
        self.assertEqual(self.scan_main()[0], 0)
        idx = self.root / ".claude" / "project-scan.json"
        d = json.loads(idx.read_text(encoding="utf-8"))
        self.assertIsNone(d["refactorDecision"])
        d["refactorDecision"] = "declined 2026-11-11"
        d["notesByHand"] = {"x": 1}
        idx.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        write(self.root, "b.py")
        self.assertEqual(self.scan_main()[0], 0)
        d2 = json.loads(idx.read_text(encoding="utf-8"))
        self.assertEqual(d2["refactorDecision"], "declined 2026-11-11")
        self.assertEqual(d2["notesByHand"], {"x": 1}, "不是掃描算出來的未知鍵也要帶過去")
        self.assertIn("b.py", d2["files"], "掃描算出來的鍵照常更新")

    def test_broken_old_index_does_not_block_rescan(self):
        write(self.root, "a.py")
        write(self.root, ".claude/project-scan.json", "{壞掉")
        self.assertEqual(self.scan_main()[0], 0)
        self.assertIn("a.py", json.loads((self.root / ".claude" / "project-scan.json").read_text(encoding="utf-8"))["files"])


class PythonImports(Base):
    """TB-04：Python 匯入解析。"""

    def graph(self, rels):
        texts = {r: (self.root / r).read_text(encoding="utf-8") for r in rels}
        return self.ps.py_graph(self.root, rels, texts)

    def test_src_layout_script_dir_multiline_and_comma(self):
        write(self.root, "src/pkg/__init__.py", "")
        write(self.root, "src/pkg/a.py", "from pkg import b" + NL + "import pkg.c")
        write(self.root, "src/pkg/b.py", "from pkg.a import x")
        write(self.root, "src/pkg/c.py")
        write(self.root, "installer/cds/__init__.py", "")
        write(self.root, "installer/cds/paths.py")
        write(self.root, "installer/cds/commands.py")
        write(self.root, "installer/install.py", "from cds import commands" + NL + "from cds.paths import R")
        write(self.root, "m.py", "from pkg import (" + NL + "    a,  # 註解" + NL + "    b," + NL + ")" + NL + "import os, pkg.c as cc, json")
        rels = ["src/pkg/__init__.py", "src/pkg/a.py", "src/pkg/b.py", "src/pkg/c.py", "installer/cds/__init__.py",
                "installer/cds/paths.py", "installer/cds/commands.py", "installer/install.py", "m.py"]
        g = self.graph(rels)
        self.assertEqual(g["src/pkg/a.py"], {"src/pkg/b.py", "src/pkg/c.py"}, "src/ 版面：pkg 對到 src/pkg")
        self.assertEqual(g["installer/install.py"], {"installer/cds/commands.py", "installer/cds/paths.py"},
                         "腳本所在資料夾在 sys.path：from cds import commands 對到 installer/cds/commands.py")
        self.assertEqual(g["m.py"], {"src/pkg/a.py", "src/pkg/b.py", "src/pkg/c.py"}, "括號多行＋import a, b")

    def test_package_dir_is_not_a_script_dir(self):
        # 套件裡的模組不會把自己的資料夾放進 sys.path：pkg/a.py 的 `import c` 不能連到 pkg/c.py
        write(self.root, "pkg/__init__.py", "")
        write(self.root, "pkg/a.py", "import c")
        write(self.root, "pkg/c.py")
        self.assertEqual(self.graph(["pkg/__init__.py", "pkg/a.py", "pkg/c.py"])["pkg/a.py"], set())

    def test_init_relative_import_uses_own_folder_and_no_fake_cycle(self):
        write(self.root, "pkg/__init__.py", "")
        write(self.root, "pkg/x.py", "WRONG = 1")
        write(self.root, "pkg/sub/__init__.py", "from .x import y")
        write(self.root, "pkg/sub/x.py", "y = 1")
        rels = ["pkg/__init__.py", "pkg/x.py", "pkg/sub/__init__.py", "pkg/sub/x.py"]
        self.assertEqual(self.graph(rels)["pkg/sub/__init__.py"], {"pkg/sub/x.py"}, "__init__.py 的 . 是自己所在的資料夾")
        # 慣用寫法：__init__ 匯入子模組、子模組 from . import 兄弟 → 不是循環
        write(self.root, "p3/__init__.py", "from .a import f")
        write(self.root, "p3/a.py", "from . import b" + NL + "def f(): pass")
        write(self.root, "p3/b.py")
        rels = ["p3/__init__.py", "p3/a.py", "p3/b.py"]
        g = self.graph(rels)
        self.assertEqual(g["p3/__init__.py"], {"p3/a.py"})
        self.assertEqual(g["p3/a.py"], {"p3/b.py"})
        self.assertEqual(self.ps.tarjan(g), [])
        # 名稱不是子模組（定義在 __init__ 裡）才連到 __init__.py
        write(self.root, "p3/c.py", "from . import VALUE")
        self.assertEqual(self.graph(rels + ["p3/c.py"])["p3/c.py"], {"p3/__init__.py"})

    def test_prose_import_line_is_not_resolved(self):
        write(self.root, "a.py", '"""說明' + NL + "import the thing and more words" + NL + '"""')
        write(self.root, "the.py")
        self.assertEqual(self.graph(["a.py", "the.py"])["a.py"], set())

    def test_installer_edges_in_this_repo(self):
        # 真實專案的唯讀驗證：installer/install.py 的 `from cds import …` 要有邊（改前整個 repo 只有 37 條邊，這幾個檔 0 條）
        rels = [p.relative_to(REPO).as_posix() for p in (REPO / "installer").rglob("*.py")]
        texts = {r: (REPO / r).read_text(encoding="utf-8-sig", errors="replace") for r in rels}
        g = self.ps.py_graph(REPO, rels, texts)
        self.assertIn("installer/cds/commands.py", g["installer/install.py"])
        self.assertTrue(g["installer/gui.py"])


class EntryPointsAndWalk(Base):
    def test_main_guard_entries_capped_and_tests_excluded(self):
        for i in range(25):
            write(self.root, f"tools/t{i:02d}.py", "def f(): pass" + NL + 'if __name__ == "__main__":' + NL + "    f()")
        write(self.root, "tests/test_x.py", "import unittest" + NL + "if __name__ == '__main__':" + NL + "    unittest.main()")
        write(self.root, "lib.py", "def g(): pass")
        d = self.ps.scan(self.root, 800)
        mains = [e for e in d["entryPoints"] if "__main__" in e]
        self.assertEqual(len(mains), 20, "最多列 20 個")
        self.assertTrue(mains[0].startswith("tools/t00.py"))
        self.assertFalse(any("test_x" in e for e in mains), "測試檔的 unittest.main() 不是專案入口")
        self.assertFalse(any("lib.py" in e for e in mains))

    def test_github_folder_is_scanned_but_git_is_not(self):
        write(self.root, ".github/workflows/ci.yml", "on: push")
        write(self.root, ".gitlab-ci.yml", "x: 1")
        write(self.root, ".git/config", "x")
        rels = {p.relative_to(self.root).as_posix() for p in self.ps.walk(self.root)}
        self.assertIn(".github/workflows/ci.yml", rels)
        self.assertIn(".gitlab-ci.yml", rels)
        self.assertFalse(any(r.startswith(".git/") for r in rels))

    def test_count_lines_dead_code_removed(self):
        self.assertFalse(hasattr(self.ps, "count_lines"), "全 repo 沒有呼叫端的死碼已刪（TB-17）")
        self.assertNotIn("count_lines", (TOOLS / "project-scan.py").read_text(encoding="utf-8").replace("_count_lines_bytes", ""))


class CountCodeFiles(Base):
    """TB-07／TB-12：「算不算專案」的唯一判定；規則照 hooks/usage_guard.py 的 _pa_count_sources。"""

    def test_rules(self):
        for i in range(12):
            write(self.root, f"tools/t{i}.py")
        self.assertEqual(self.ps.count_code_files(self.root), (12, False), "tools/ 底下的 .py 要算（改前 --summary 判 0）")
        dot = self.tmp / "dot"
        for i in range(12):
            write(dot, f".config/m{i}.py")
        self.assertEqual(self.ps.count_code_files(dot), (0, False), "點開頭的資料夾不進去（改前 --summary 判 12）")
        other = self.tmp / "other"
        for rel in ("a.PY", "b.sh", "c.ps1", "d.md", "e.json", "node_modules/x.js", "worktrees/y.py", "build/z.py", "src/m.ts"):
            write(other, rel)
        self.assertEqual(self.ps.count_code_files(other), (4, False), "副檔名不分大小寫、含 .sh/.ps1 腳本；排除資料夾不算")

    def test_limit_and_budget_truncate(self):
        for i in range(10):
            write(self.root, f"f{i}.py")
        self.assertEqual(self.ps.count_code_files(self.root, limit=4), (4, True))
        self.assertEqual(self.ps.count_code_files(self.root, limit=3000, budget_sec=-1)[1], True)

    def test_same_as_hook_implementation(self):
        # 同一棵樹兩邊數出來一樣（hook 改成呼叫 count_code_files 之前，這條證明規則沒有漂移）
        hook = load("ug_for_scan_tests", REPO / "hooks" / "usage_guard.py")
        trees = []
        for name, rels in (("t1", [f"tools/t{i}.py" for i in range(12)]), ("t2", [f".config/m{i}.py" for i in range(12)]),
                           ("t3", ["a.py", "b.SH", "node_modules/j.js", "src/x.ts", ".hid/y.py", "docs/r.md"])):
            t = self.tmp / name
            for rel in rels:
                write(t, rel)
            trees.append(t)
        for t in trees:
            self.assertEqual(self.ps.count_code_files(t), hook._pa_count_sources(str(t)), t.name)
        self.assertEqual(hook.PA_EXCLUDE, self.ps.EXCLUDE_DIRS)
        self.assertEqual(hook.PA_SOURCE_EXT, self.ps.COUNT_SOURCE_EXT)

    def test_summary_uses_it_and_writes_nothing(self):
        for i in range(12):
            write(self.root, f"tools/t{i}.py")
        rc, out = self.scan_main("--summary")
        self.assertEqual(rc, 0)
        self.assertIn("原始碼檔 12", out)
        self.assertIn("算專案", out)
        self.assertNotIn("不算專案", out)
        self.assertFalse((self.root / ".claude").exists() or (self.root / "docs").exists(), "--summary 不寫檔")
        dot = self.tmp / "dotproj"
        for i in range(12):
            write(dot, f".config/m{i}.py")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.ps.main([str(dot), "--summary"])
        self.assertIn("不算專案", buf.getvalue())

    def test_summary_does_not_hash_or_build_graph(self):
        write(self.root, "a.py")
        calls = []
        orig = (self.ps.scan, self.ps.py_graph)
        self.ps.scan = lambda *a, **k: calls.append("scan")
        self.ps.py_graph = lambda *a, **k: calls.append("py_graph")
        try:
            self.scan_main("--summary")
        finally:
            self.ps.scan, self.ps.py_graph = orig
        self.assertEqual(calls, [], "--summary 只數檔案（TB-12）")


class MaxCyclesGate(Base):
    """TB-08：只看循環的閘門，不受其他檔變動影響，不寫檔。"""

    def setUp(self):
        super().setUp()
        write(self.root, "pkg/__init__.py", "")
        write(self.root, "pkg/a.py", "from pkg import b")
        write(self.root, "pkg/b.py", "from pkg import a")

    def test_threshold(self):
        rc, out = self.scan_main("--max-cycles", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("循環 1 組", out)
        rc, out = self.scan_main("--max-cycles", "0")
        self.assertEqual(rc, 1, out)
        self.assertFalse((self.root / ".claude").exists(), "不寫檔")

    def test_unaffected_by_other_changes_unlike_check(self):
        self.assertEqual(self.scan_main()[0], 0)
        write(self.root, "new_file.py", "y = 2")
        self.assertEqual(self.scan_main("--check")[0], 1, "--check 有任何新檔就回 1")
        self.assertEqual(self.scan_main("--max-cycles", "1")[0], 0, "--max-cycles 只看循環")

    def test_skills_tell_to_use_max_cycles_not_check(self):
        """skills 的閘門寫法：Python 用 --max-cycles（組數）、JS／TS 用 depgraph --max-cycle-files（檔數），不叫人拿 --check 當測試閘門。"""
        init = (REPO / "skills" / "cds-project-init" / "SKILL.md").read_text(encoding="utf-8")
        audit = (REPO / "skills" / "cds-project-audit" / "SKILL.md").read_text(encoding="utf-8")
        for text in (init, audit):
            self.assertIn("--max-cycles", text)
            self.assertIn("--max-cycle-files", text)
            self.assertNotIn("把 `--check` 與", text)
        self.assertNotIn("`project-scan.py --check` 與循環數檢查加進測試", init)
        self.assertIn("Meeting-Assistant 2026-11-01", init, "既有的日期與專案名不可刪")

    def test_not_combined_with_check_or_summary(self):
        self.assertEqual(self.scan_main("--max-cycles", "1", "--check")[0], 2)
        self.assertEqual(self.scan_main("--max-cycles", "1", "--summary")[0], 2)


class JsImports(Base):
    """TB-09：BOM、ESM 的 ./b.js 對到 b.ts、require()。"""

    def test_bom_esm_and_require_in_scan(self):
        write(self.root, "a.py", binary=b"\xef\xbb\xbfimport b" + NL.encode())
        write(self.root, "b.py")
        write(self.root, "c.ts", binary=b"\xef\xbb\xbf" + 'import { x } from "./d";'.encode() + NL.encode())
        write(self.root, "d.ts", "export const x = 1;")
        write(self.root, "src/e.ts", 'import { f } from "./f.js";')
        write(self.root, "src/f.ts", "export const f = 1;")
        write(self.root, "src/g.js", 'const h = require("./h");')
        write(self.root, "src/h.js", "module.exports = 1;")
        d = self.ps.scan(self.root, 800)
        self.assertEqual(d["graphEdges"], 4, d["mostDepended"])
        hot = dict(d["mostDepended"])
        for want in ("b.py", "d.ts", "src/f.ts", "src/h.js"):
            self.assertEqual(hot.get(want), 1, (want, hot))

    def test_depgraph_resolve_prefers_real_js(self):
        dg = load("dg_resolve", TOOLS / "depgraph.py")
        fset = {"s/a.ts", "s/a.js"}
        self.assertEqual(dg.resolve("s/x.ts", "./a.js", fset, "s", {}), "s/a.js", "真的有 a.js 就對 a.js")
        self.assertEqual(dg.resolve("s/x.ts", "./a.js", {"s/a.ts"}, "s", {}), "s/a.ts")


class CheckAndAtomicWrite(Base):
    """TB-10：索引內容不合法回 2（不與「有變動」同碼）；寫入是原子的。"""

    def test_invalid_index_exits_2(self):
        write(self.root, "a.py")
        idx = self.root / ".claude" / "project-scan.json"
        for bad in ("{}", '{"files": []}', '{"files": {"a.py": 1}}', "[1]", '{"files": {}, "generatedAt": "x"'):
            write(self.root, ".claude/project-scan.json", bad)
            rc, out = self.scan_main("--check")
            self.assertEqual(rc, 2, (bad, out))
            self.assertIn("索引", out)
        idx.unlink()
        self.assertEqual(self.scan_main("--check")[0], 2, "沒有索引也是 2（既有行為）")

    def test_old_index_without_optional_keys_still_readable(self):
        write(self.root, "a.py")
        self.assertEqual(self.scan_main()[0], 0)
        idx = self.root / ".claude" / "project-scan.json"
        d = json.loads(idx.read_text(encoding="utf-8"))
        for f in d["files"].values():
            f.pop("mtime", None)
            f.pop("size", None)
        del d["generatedAt"]
        idx.write_text(json.dumps(d), encoding="utf-8")
        self.assertEqual(self.scan_main("--check")[0], 0, "舊索引沒有 mtime／generatedAt 也要能比對")

    def test_atomic_write_leaves_no_tmp_and_keeps_old_on_failure(self):
        target = self.root / "out" / "x.json"
        self.ps._atomic_write(target, "one")
        self.ps._atomic_write(target, "two")
        self.assertEqual(target.read_text(encoding="utf-8"), "two")
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["x.json"], "不留 .tmp")
        orig = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
        try:
            with self.assertRaises(OSError):
                self.ps._atomic_write(target, "three")
        finally:
            os.replace = orig
        self.assertEqual(target.read_text(encoding="utf-8"), "two", "寫失敗舊檔不變")
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["x.json"], "失敗也清掉 .tmp")


class DepgraphSharesScan(Base):
    """TB-03：depgraph 當閘門用時與 project-scan 走同一份走訪、別名、Tarjan。"""

    def setUp(self):
        super().setUp()
        r = self.root
        write(r, "tsconfig.json", '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}')
        write(r, "src/lib/a.ts", 'import { b } from "@/lib/b";')
        write(r, "src/lib/b.ts", 'import { a } from "@/lib/a";')
        wt = r / ".claude" / "worktrees" / "agent-1"
        write(wt, ".git", "gitdir: x")
        write(wt, "src/lib/a.ts", 'import { b } from "./b";')
        write(wt, "src/lib/b.ts", 'import { a } from "./a";')
        write(r, ".next/server/x.js", 'import "./y";')
        write(r, ".next/server/y.js", 'import "./x";')
        self.dg = load("dg_scan_tests", TOOLS / "depgraph.py")

    def test_cli_on_project_root_matches_project_scan(self):
        scan_cycles = self.ps.scan(self.root, 800)["cycles"]
        self.assertEqual(scan_cycles, [["src/lib/a.ts", "src/lib/b.ts"]])
        root = self.root.as_posix()
        rc, out, err = run_tool("depgraph.py", root, "--max-cycle-files", "2")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("循環 1 組共 2 檔", out, "沒給 --alias 也讀 tsconfig；worktree、.next 不算")
        self.assertNotIn("worktrees", out)
        self.assertNotIn(".next", out)
        rc, out, _ = run_tool("depgraph.py", root, "--max-cycle-files", "1")
        self.assertEqual(rc, 1)

    def test_explicit_alias_still_wins(self):
        root = self.root.as_posix()
        rc, out, _ = run_tool("depgraph.py", root, "--alias", "@/=" + root + "/nowhere", "--max-cycle-files", "0")
        self.assertEqual(rc, 0, "--alias 明確給了就只用給的（@/lib/* 解析不到 → 沒有循環）")

    def test_collect_files_is_project_scan_walk(self):
        got = {p[len(self.root.as_posix()) + 1:] for p in self.dg.collect_files(self.root.as_posix())}
        want = {p.relative_to(self.root).as_posix() for p in self.ps.walk(self.root) if p.suffix in self.dg.EXTS}
        self.assertEqual(got, want)
        self.assertEqual(got, {"src/lib/a.ts", "src/lib/b.ts"})

    def test_tarjan_is_single_implementation(self):
        g = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"e"}, "e": {"d"}, "f": {"f2"}, "f2": set()}
        files = sorted(g)
        self.assertEqual(sorted(self.dg.tarjan_sccs(files, g)), sorted(self.ps.tarjan(g)))
        self.assertEqual([len(s) for s in self.dg.tarjan_sccs(files, g)], [3, 2], "依檔數由大到小")
        import inspect
        self.assertNotIn("def visit", inspect.getsource(self.dg), "depgraph 不再有自己的 Tarjan 實作")
        self.assertEqual(Path(self.dg.scan_mod().__file__).name, "project-scan.py")

    def test_missing_root_exits_2(self):
        rc, out, _ = run_tool("depgraph.py", self.tmp / "不存在", "--max-cycle-files", "0")
        self.assertEqual(rc, 2, "root 打錯時原本 exit 0，閘門永遠通過")
        self.assertIn("不是資料夾", out)

    def test_existing_default_still_excludes_tests_dir_and_alias_default(self):
        # 沒有 tsconfig 時 @/ 仍指向 root（原行為）；__tests__ 照樣不算
        r = self.tmp / "plain" / "src"
        write(r, "lib/a.ts", 'import { b } from "./b";')
        write(r, "lib/b.ts", 'import { a } from "@/lib/a";')
        write(r, "__tests__/t.ts", 'import "../lib/a";')
        files, g, _ext, _ = self.dg.build_graph(r.as_posix(), None, self.dg.aliases_for(r.as_posix()))
        self.assertEqual(len(files), 2)
        self.assertEqual(len(self.dg.tarjan_sccs(files, g)), 1)


class ModuleInventory(unittest.TestCase):
    """TB-11：moduleInventory 遇到非 UTF-8 檔不崩潰、root 不存在 exit 2。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-inv-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_non_utf8_file_is_listed_not_crash(self):
        src = self.tmp / "src"
        write(src, "a.ts", binary="// 中文註解".encode("cp950") + b"\nexport const a = 1;\n")
        write(src, "b.ts", 'import { a } from "./a";')
        out = self.tmp / "inv.md"
        rc, so, se = run_tool("moduleInventory.py", src.as_posix(), "--out", out)
        self.assertEqual(rc, 0, se)
        md = out.read_text(encoding="utf-8")
        self.assertIn("a.ts", md)
        self.assertIn("b.ts", md)
        self.assertIn("共 2 檔、1 條 import 邊", md)

    def test_unreadable_file_is_skipped_and_counted(self):
        dg_path = TOOLS
        sys.path.insert(0, str(dg_path))
        try:
            mi = load("mi_tests", TOOLS / "moduleInventory.py")
        finally:
            sys.path.remove(str(dg_path))
        src = self.tmp / "src"
        write(src, "a.ts", "export const a = 1;")
        write(src, "b.ts", "export const b = 1;")
        real_open = open
        locked = (src / "b.ts").as_posix()

        def fake_open(f, *a, **k):
            if str(f).replace(os.sep, "/") == locked:
                raise PermissionError("locked")
            return real_open(f, *a, **k)

        out = self.tmp / "inv2.md"
        import builtins
        old_argv, old_open = sys.argv, builtins.open
        sys.argv = ["moduleInventory.py", src.as_posix(), "--out", str(out)]
        builtins.open = fake_open
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                mi.main()
        finally:
            builtins.open, sys.argv = old_open, old_argv
        self.assertIn("略過讀不到的檔 1 個", buf.getvalue())
        md = out.read_text(encoding="utf-8")
        self.assertIn("## 無法讀取", md)
        self.assertIn("b.ts", md)

    def test_missing_root_exits_2_and_writes_nothing(self):
        out = self.tmp / "inv3.md"
        rc, so, _ = run_tool("moduleInventory.py", self.tmp / "nope", "--out", out)
        self.assertEqual(rc, 2)
        self.assertIn("不是資料夾", so)
        self.assertFalse(out.exists())
        rc, so, _ = run_tool("moduleInventory.py", "--out", out, cwd=str(self.tmp))  # 預設 root=src 不存在
        self.assertEqual(rc, 2)


class ProgressDiffRewrites(unittest.TestCase):
    """TB-02：progress-diff 用來證明「精簡文件沒有遺漏句子」，改過的句子不可判成找得到。"""

    @classmethod
    def setUpClass(cls):
        cls.pd = load("pd_tests", TOOLS / "progress-diff.py")

    def kinds(self, old, new):
        r = self.pd.compare(old, [new] if isinstance(new, str) else new, 6, False)
        return len(r.missing), len(r.suspect), r.found

    def test_changed_sentences_are_flagged(self):
        # (說明, 舊, 新, 期望：找不到, 疑似改寫)——稽核報告 r4 的案例，改前這些幾乎全是「找不到 0」
        cases = [
            ("5→15", "- 5 個 agent 全部完成並回報。", "- 15 個 agent 全部完成並回報。", 0, 1),
            ("句尾 80→800", "- 單檔行數上限 80", "- 單檔行數上限 800 行", 0, 1),
            ("日期 11-1→11-11", "決策：2026-11-1｜改用 A", "決策：2026-11-11｜改用 A", 0, 1),
            ("句首加「不」", "可以直接刪除舊的封存檔。", "不可以直接刪除舊的封存檔。", 0, 1),
            ("要問→不要問", "這種情況要問使用者再做。", "這種情況不要問使用者再做。", 1, 0),
            ("刪了後半句", "門檻是 800 行，超過就拆檔並補測試。", "門檻是 800 行。", 1, 0),
            ("短句含數字被刪", "上限 3 次。共 5 組。", "（都刪掉了）", 2, 0),
            ("英文句刪一半", "Step one is done. Step two failed with code 3.", "Step one is done.", 1, 0),
            ("表格改一格", "| 門檻 | 800 行 | 2026-11-01 |", "| 門檻 | 600 行 | 2026-11-01 |", 1, 0),
            ("跨行拼接的假命中", "測試全部通過", "...測試全部\n通過率 50%", 1, 0),
            ("小數點 5→5.5", "版本號是 5", "版本號是 5.5 版", 0, 1),
            ("百分號 50→50%", "完成率達到 50", "完成率達到 50% 以上", 0, 1),
            ("負號 3→-3", "3 度以下才算正常", "-3 度以下才算正常", 0, 1),
            ("中間插字 80→800 是找不到", "上限是 80 行", "上限是 800 行", 1, 0),
            ("後面接否定字", "可以直接刪除舊檔不再保留", "可以直接刪除舊檔不再保留", 0, 0),  # 整句相同不報
            ("英文 not", "Always delete the old archive file", "Do not Always delete the old archive file", 0, 1),
            ("小數點 5.5 與 55 不同", "版本 5.5 已發布", "版本 55 已發布", 1, 0),
            ("逗號 1,5 與 15 不同", "共 1,5 項", "共 15 項", 1, 0),
        ]
        for name, old, new, want_missing, want_suspect in cases:
            m, s, _f = self.kinds(old, new)
            self.assertEqual((m, s), (want_missing, want_suspect), name)

    def test_unchanged_moves_and_merges_are_not_reported(self):
        cases = [
            ("原封不動搬到別段", "第一句保留的內容。第二句也保留。", "# 另一段\n\n- 第二句也保留。\n\n其他文字。第一句保留的內容。"),
            ("搬到另一個檔", "第一句保留的內容。第二句也保留。", ["第一句保留的內容。", "# 封存\n\n第二句也保留。"]),
            ("兩句合併成一句", "安裝前先備份。安裝後要驗證。", "安裝前先備份，安裝後要驗證。"),
            ("只改標點與空白", "結果：共 3 組，全部通過；請 看 報告。", "結果: 共 3 組 全部通過、請看報告"),
            ("全形半形", "結果（共 3 組）都通過了。", "結果(共 3 組)都通過了。"),
            ("清單符號換掉", "- 先備份資料夾\n- 再跑驗證腳本", "1. 先備份資料夾\n2. 再跑驗證腳本"),
            ("加粗與反引號", "必須先執行 install.py verify 才算完成。", "必須先執行 `install.py` **verify** 才算完成。"),
            ("併入更長句且前後是一般字", "記憶體不足就不要執行回測", "若遇到的情況是記憶體不足就不要執行回測，並回報使用者"),
            ("CRLF", "第一句保留的內容。" + chr(13) + NL + "第二句也保留。", "第一句保留的內容。" + NL + "第二句也保留。"),
        ]
        for name, old, new in cases:
            self.assertEqual(self.kinds(old, new)[:2], (0, 0), name)

    def test_clean_occurrence_elsewhere_wins_over_suspicious_one(self):
        # 同一句在新文出現兩處：一處前面緊鄰數字（疑似）、另一處乾淨 → 找得到（句子真的還在）
        self.assertEqual(self.kinds("單檔行數上限 80", "- 單檔行數上限 800 行\n- 單檔行數上限 80")[:2], (0, 0))

    def test_exact_vs_merged_counts(self):
        r = self.pd.compare("甲乙丙丁戊己庚。壬癸子丑寅卯辰。", ["甲乙丙丁戊己庚。\n再加一些字壬癸子丑寅卯辰完了"], 6, False)
        self.assertEqual((r.exact, r.merged, len(r.missing), len(r.suspect)), (1, 1, 0, 0))

    def test_duplicates_counted_once_and_short_without_digit_skipped(self):
        r = self.pd.compare("這是一句重複的內容。這是一句重複的內容。短句。", ["這是一句重複的內容。"], 6, False)
        self.assertEqual((r.total, r.skipped, r.problems), (1, 1, 0))

    def test_diff_compat_returns_problem_list(self):
        problems, text = self.pd.diff("單檔行數上限 80", ["單檔行數上限 800 行"], 6, False)
        self.assertEqual(len(problems), 1, "舊介面 diff() 的清單含疑似改寫")
        self.assertIn("疑似改寫 1", text)

    def _cli(self, tmp, old_bytes, new_bytes, *extra):
        old = Path(tmp) / "old.md"
        new = Path(tmp) / "new.md"
        old.write_bytes(old_bytes)
        new.write_bytes(new_bytes)
        return run_tool("progress-diff.py", "--old-file", old, "--new", new, *extra)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            same = "第一句保留下來的內容。".encode("utf-8")
            self.assertEqual(self._cli(tmp, same, same)[0], 0)
            rc, out, _ = self._cli(tmp, "單檔行數上限 80".encode("utf-8"), "單檔行數上限 800 行".encode("utf-8"))
            self.assertEqual(rc, 1, "疑似改寫也要 exit 1")
            self.assertIn("疑似改寫 1", out)
            rc, out, _ = self._cli(tmp, "第二句會被刪掉的內容".encode("utf-8"), "別的".encode("utf-8"))
            self.assertEqual(rc, 1)
            self.assertIn("找不到 1", out)
            rc, _o, err = self._cli(tmp, "舊版中文內容。".encode("cp950"), same)
            self.assertEqual(rc, 2, "舊檔不是 UTF-8 是讀檔失敗，不與「有遺漏」同碼")
            self.assertIn("讀檔失敗", err)
            rc, _o, err = self._cli(tmp, same, "新版".encode("cp950") + b"\xff")
            self.assertEqual(rc, 2)
            rc, _o, err = run_tool("progress-diff.py", "--old-file", Path(tmp) / "不存在.md", "--new", Path(tmp) / "old.md")
            self.assertEqual(rc, 2)
            rc, _o, _e = run_tool("progress-diff.py", "--old-ref", "no-such-ref-xyz", "--git-path", "a.md", "--new", Path(tmp) / "old.md", "--repo", tmp)
            self.assertEqual(rc, 2, "git 取不到舊版也是 2")
            self.assertEqual(run_tool("progress-diff.py")[0], 2, "沒給參數 2（既有行為）")

    def test_bom_in_files_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = "第一句保留下來的內容。".encode("utf-8")
            self.assertEqual(self._cli(tmp, b"\xef\xbb\xbf" + s, s)[0], 0)

    def test_real_core_md_slimming_0_26_0(self):
        """這個 repo 的真實情境：0.26.0 把 rules/core.md 瘦身（原文搬到 core-detail.md），commit 3fc934c；舊版工具報「103 句、找不到 0」。
        新工具逐句比對：103 句全部整句相同、疑似改寫 0、找不到 0。沒有這個 commit（淺層 clone）就略過。"""
        def show(spec):
            r = subprocess.run(["git", "-C", str(REPO), "show", spec], capture_output=True)
            return r.stdout.decode("utf-8") if r.returncode == 0 else None
        old, new1, new2 = show("3fc934c^:rules/core.md"), show("3fc934c:rules/core.md"), show("3fc934c:rules/core-detail.md")
        if not (old and new1 and new2):
            self.skipTest("沒有 commit 3fc934c")
        r = self.pd.compare(old, [new1, new2], 6, False)
        self.assertEqual((r.total, len(r.missing), len(r.suspect), r.found), (103, 0, 0, 103), r.text)
        # 對照：只拿瘦身後的 core.md（不含搬走的 core-detail.md）比，一定有遺漏——工具不是永遠回 0
        r2 = self.pd.compare(old, [new1], 6, False)
        self.assertGreater(len(r2.missing), 0)


class TestFileLayout(unittest.TestCase):
    def test_unittest_main_is_last_in_test_tools(self):
        """TB-18：tests/test_tools.py 的 unittest.main() 夾在檔案中間，直接執行只跑前 12 項。"""
        tree = ast.parse((REPO / "tests" / "test_tools.py").read_text(encoding="utf-8"))
        last = tree.body[-1]
        self.assertIsInstance(last, ast.If, "最後一個頂層敘述要是 if __name__ == '__main__'")
        self.assertIn("__main__", ast.dump(last.test))
        guards = [n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.dump(n.test)]
        self.assertEqual(len(guards), 1)


if __name__ == "__main__":
    unittest.main()
