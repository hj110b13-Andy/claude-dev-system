"""通用工具測試：depgraph（循環偵測、別名、分層規則）、progress-diff（遺漏句偵測）。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import depgraph  # noqa: E402

ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


class DepGraph(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-dg-"))
        r = self.tmp / "src"
        (r / "lib").mkdir(parents=True)
        (r / "app").mkdir()
        (r / "__tests__").mkdir()
        (r / "lib" / "a.ts").write_text('import { b } from "./b";\n', encoding="utf-8")
        (r / "lib" / "b.ts").write_text('import { a } from "@/lib/a";\nimport x from "react";\n', encoding="utf-8")
        (r / "lib" / "c.ts").write_text('import { p } from "@/app/page";\n', encoding="utf-8")
        (r / "app" / "page.tsx").write_text('export const p = 1;\n', encoding="utf-8")
        (r / "__tests__" / "t.ts").write_text('import "../lib/a";\n', encoding="utf-8")
        self.root = r.as_posix()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cycle_and_alias(self):
        files, g, ext, _ = depgraph.build_graph(self.root, None, {"@/": self.root})
        self.assertEqual(len(files), 4, "__tests__ 不應計入")
        sccs = depgraph.tarjan_sccs(files, g)
        self.assertEqual(len(sccs), 1)
        self.assertEqual(len(sccs[0]), 2)
        self.assertIn("react", ext)

    def test_gate_and_forbid(self):
        cmd = [sys.executable, str(REPO / "tools" / "depgraph.py"), self.root, "--forbid", "lib:app"]
        r = subprocess.run(cmd + ["--max-cycle-files", "1"], capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 1)
        out = r.stdout.decode("utf-8")
        self.assertIn("分層違規 lib -> app：1", out)
        r = subprocess.run(cmd + ["--max-cycle-files", "2"], capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 0)


class ProgressDiff(unittest.TestCase):
    def test_detects_missing_sentence(self):
        tmp = Path(tempfile.mkdtemp(prefix="cds-pd-"))
        try:
            (tmp / "old.md").write_text("第一句保留下來的內容。第二句會被刪掉的內容。\n", encoding="utf-8")
            (tmp / "new.md").write_text("第一句保留下來的內容。\n", encoding="utf-8")
            (tmp / "arc.md").write_text("", encoding="utf-8")
            cmd = [sys.executable, str(REPO / "tools" / "progress-diff.py"), "--old-file", str(tmp / "old.md"),
                   "--new", str(tmp / "new.md"), "--new", str(tmp / "arc.md")]
            r = subprocess.run(cmd, capture_output=True, env=ENV)
            self.assertEqual(r.returncode, 1)
            self.assertIn("第二句會被刪掉的內容", r.stdout.decode("utf-8"))
            (tmp / "arc.md").write_text("第二句會被刪掉的內容\n", encoding="utf-8")
            self.assertEqual(subprocess.run(cmd, capture_output=True, env=ENV).returncode, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_usage_without_args(self):
        r = subprocess.run([sys.executable, str(REPO / "tools" / "progress-diff.py")], capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 2)


class UsageGuardConfig(unittest.TestCase):
    """門檻讀取順序：專案 .claude/dispatch-config.json → 全域設定檔 → 內建預設。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("usage_guard_t", REPO / "hooks" / "usage_guard.py")
        cls.ug = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ug)

    def _cfg(self, five, seven, **plan):
        return {"plan": {"current": "x", **plan}, "usageThresholdPct": {"x": {"fiveHour": five, "sevenDay": seven}, "p": {"fiveHour": 80, "sevenDay": 97}}}

    def test_order_project_global_default(self):
        import json
        ug = self.ug
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            proj = td / "proj" / "sub"
            (td / "proj" / ".claude").mkdir(parents=True)
            proj.mkdir()
            (td / "proj" / ".claude" / "dispatch-config.json").write_text(json.dumps(self._cfg(95, 99)), encoding="utf-8")
            glob = td / "g.json"
            glob.write_text(json.dumps(self._cfg(70, 90)), encoding="utf-8")
            old = ug.CONFIG
            try:
                ug.CONFIG = str(glob)
                lim, src = ug.load_limits(str(proj))
                self.assertEqual((lim["fiveHourLimit"], lim["sevenDayLimit"]), (95.0, 99.0))
                self.assertIn("專案", src)
                lim, src = ug.load_limits(str(td))  # 專案外 -> 全域
                self.assertEqual((lim["fiveHourLimit"], lim["sevenDayLimit"]), (70.0, 90.0))
                self.assertIn("全域", src)
                ug.CONFIG = str(td / "missing.json")
                lim, src = ug.load_limits(str(td))
                self.assertEqual((lim["fiveHourLimit"], lim["sevenDayLimit"]), (85.0, 97.0))
                self.assertEqual(src, "內建預設")
            finally:
                ug.CONFIG = old

    def test_fetch_failure_is_throttled(self):
        import io, json, sys, time
        ug = self.ug
        with tempfile.TemporaryDirectory() as td:
            old = (ug.STATE_DIR, ug.USAGE, ug.CONFIG, ug.fetch, sys.stdin)
            try:
                ug.STATE_DIR, ug.USAGE, ug.CONFIG = td, str(Path(td) / "usage.json"), str(Path(td) / "none.json")
                calls = []

                def boom():
                    calls.append(1)
                    raise RuntimeError("offline")
                ug.fetch = boom
                for _ in range(3):
                    sys.stdin = io.StringIO(json.dumps({"hook_event_name": "PostToolUse", "cwd": td}))
                    ug.main()
                self.assertEqual(len(calls), 1, "抓失敗後 TTL 內不可再打")
                st = json.loads(Path(ug.USAGE).read_text(encoding="utf-8"))
                self.assertLess(time.time() - st["fetched_at"], 60)
                self.assertIn("fetch_failed_at", st)
            finally:
                ug.STATE_DIR, ug.USAGE, ug.CONFIG, ug.fetch, sys.stdin = old

    def test_project_root_resolves_from_subfolder_of_git_repo(self):
        # 0.22.0：cd 到 git 專案的子資料夾不可被當成另一個新專案；上層只有 CLAUDE.md（工作區共用）不算專案根
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            repo = ws / "repo"
            sub = repo / "pkg" / "inner"
            sub.mkdir(parents=True)
            (repo / ".git").mkdir()
            (ws / "CLAUDE.md").write_text("# 工作區共用", encoding="utf-8")
            self.assertEqual(os.path.normcase(self.ug._pa_skip(str(sub))), os.path.normcase(str(repo)))
            self.assertEqual(os.path.normcase(self.ug._pa_skip(str(repo))), os.path.normcase(str(repo)))
            plain = ws / "newproj" / "src"
            plain.mkdir(parents=True)
            self.assertEqual(os.path.normcase(self.ug._pa_skip(str(plain))), os.path.normcase(str(plain)), "上層只有 CLAUDE.md 不往上併")
            self.assertIsNone(self.ug._pa_skip(str(REPO / "installer")), "claude-dev-system 的子資料夾也不做")

    def test_project_auto_msg_decides_init_audit_none_and_dedupes(self):
        import json
        ug = self.ug
        with tempfile.TemporaryDirectory() as td:
            old = (ug.STATE_DIR, ug.PA_STATE, ug.CONFIG)
            try:
                ug.STATE_DIR, ug.PA_STATE, ug.CONFIG = td, str(Path(td) / "pa.json"), str(Path(td) / "none.json")
                proj = Path(td) / "proj"
                (proj / "src").mkdir(parents=True)
                for i in range(12):
                    (proj / "src" / f"m{i}.py").write_text("x=1", encoding="utf-8")
                (proj / "node_modules").mkdir()
                for i in range(50):
                    (proj / "node_modules" / f"j{i}.js").write_text("x", encoding="utf-8")
                msg = ug.project_auto_msg(str(proj), "s1")
                self.assertIn("cds-project-init", msg)
                self.assertIn("12 檔", msg)
                self.assertIsNone(ug.project_auto_msg(str(proj), "s1"), "同一場對話不重複")
                self.assertIn("cds-project-init", ug.project_auto_msg(str(proj), "s2"), "新對話再提醒")
                (proj / "CLAUDE.md").write_text("# p", encoding="utf-8")
                self.assertIn("cds-project-audit", ug.project_auto_msg(str(proj), "s3"))
                (proj / ".claude").mkdir()
                (proj / ".claude" / "project-scan.json").write_text("{}", encoding="utf-8")
                self.assertIsNone(ug.project_auto_msg(str(proj), "s4"), "有索引就不提醒")
                small = Path(td) / "small"
                small.mkdir()
                (small / "a.py").write_text("x", encoding="utf-8")
                self.assertIsNone(ug.project_auto_msg(str(small), "s5"), "小腳本資料夾不做")
                (proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"projectAutomation": {"autoAudit": False}}), encoding="utf-8")
                (proj / ".claude" / "project-scan.json").unlink()
                self.assertIsNone(ug.project_auto_msg(str(proj), "s6"), "專案設定關掉 autoAudit")
            finally:
                ug.STATE_DIR, ug.PA_STATE, ug.CONFIG = old

    def test_flat_thresholds_format(self):
        self.assertEqual(self.ug.pick_thresholds({"usageThresholdPct": {"fiveHour": 95, "sevenDay": 99}}), (95.0, 99.0))
        self.assertIsNone(self.ug.pick_thresholds({"usageThresholdPct": {"fiveHour": "x"}}))

    def test_plan_until_switches_to_after(self):
        cfg = self._cfg(95, 99, until="2026-11-13", after="p")
        cfg["plan"]["x"] = {"until": "2026-11-13"}
        self.assertEqual(self.ug.pick_thresholds(cfg, "2026-11-12"), (95.0, 99.0))
        self.assertEqual(self.ug.pick_thresholds(cfg, "2026-11-13"), (80.0, 97.0))


class ProjectScanGitignore(unittest.TestCase):
    """project-scan 不把 .gitignore 排除的暫存與金鑰檔算成專案內容。"""

    def _load(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("project_scan_mod", Path(__file__).resolve().parent.parent / "tools" / "project-scan.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _rels(self, mod, root):
        return {p.relative_to(root).as_posix() for p in mod.walk(root)}

    def test_git_project_skips_ignored(self):
        import subprocess

        mod = self._load()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".gitignore").write_text(".wrangler/\n.dev.vars\n*.log\n!keep.log\n", encoding="utf-8")
            (root / ".wrangler" / "state").mkdir(parents=True)
            (root / ".wrangler" / "state" / "x.sqlite").write_text("x", encoding="utf-8")
            (root / ".dev.vars").write_text("K=1", encoding="utf-8")
            (root / "a.log").write_text("x", encoding="utf-8")
            (root / "keep.log").write_text("x", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "m.py").write_text("x=1", encoding="utf-8")
            rels = self._rels(mod, root)
            self.assertIn("src/m.py", rels)
            self.assertIn("keep.log", rels, "否定規則要照算")
            self.assertIn(".gitignore", rels)
            for gone in (".wrangler/state/x.sqlite", ".dev.vars", "a.log"):
                self.assertNotIn(gone, rels)

    def test_non_git_folder_unchanged(self):
        mod = self._load()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".gitignore").write_text("a.log\n", encoding="utf-8")
            (root / "a.log").write_text("x", encoding="utf-8")
            self.assertIn("a.log", self._rels(mod, root), "不是 git 專案就不判斷")


if __name__ == "__main__":
    unittest.main()


class VideoDownloadDir(unittest.TestCase):
    """download 預設資料夾：--out ＞ local.json video.downloadDir ＞ ~/Downloads（使用者要求下載預設存 D 槽）。"""

    def run_dir(self, home: Path, out: str | None = None) -> str:
        code = f"import video; print(video.download_dir({out!r}))"
        r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO / "tools"), capture_output=True, text=True,
                           encoding="utf-8", env={**ENV, "CLAUDE_CONFIG_DIR": str(home)})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_order(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.assertEqual(self.run_dir(home), str(Path.home() / "Downloads"))
        cfg = home / "claude-dev-system" / "config"
        cfg.mkdir(parents=True)
        (cfg / "local.json").write_text('{"keys": {}, "video": {"downloadDir": "' + (home / "dl").as_posix() + '"}}', encoding="utf-8")
        self.assertEqual(Path(self.run_dir(home)), home / "dl")
        self.assertEqual(Path(self.run_dir(home, str(home / "x"))), home / "x")


class ProjectScan(unittest.TestCase):
    def test_scan_inventory_cycles_bigfile_and_check(self):
        tmp = Path(tempfile.mkdtemp(prefix="cds-scan-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "pkg").mkdir()
        (tmp / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (tmp / "pkg" / "a.py").write_text("from pkg import b" + chr(10), encoding="utf-8")
        (tmp / "pkg" / "b.py").write_text("from pkg import a" + chr(10), encoding="utf-8")
        (tmp / "pkg" / "big.py").write_text(("x = 1" + chr(10)) * 900, encoding="utf-8")
        (tmp / "scripts" / "backtest").mkdir(parents=True)  # Stock-web exitStrategy.ts 6,588 行被漏掉
        (tmp / "scripts" / "backtest" / "exitStrategy.ts").write_text(("const x = 1;" + chr(10)) * 1000, encoding="utf-8")
        (tmp / "tests").mkdir()
        (tmp / "tests" / "test_a.py").write_text("def test(): pass" + chr(10), encoding="utf-8")
        (tmp / "package.json").write_text('{"scripts": {"dev": "next dev"}}', encoding="utf-8")
        (tmp / "node_modules").mkdir()
        (tmp / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
        (tmp / "frames").mkdir()
        for i in range(30):
            (tmp / "frames" / f"f{i}.png").write_bytes(b"png")
        tool = str(REPO / "tools" / "project-scan.py")
        r = subprocess.run([sys.executable, tool, str(tmp), "--max-lines", "800"], capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        md = (tmp / "docs" / "PROJECT-INVENTORY.md").read_text(encoding="utf-8")
        idx = json.loads((tmp / ".claude" / "project-scan.json").read_text(encoding="utf-8"))
        self.assertEqual(idx["counts"]["source"], 4, idx["counts"])
        self.assertEqual(idx["counts"]["test"], 1)
        self.assertNotIn("node_modules/junk.js", idx["files"])
        self.assertFalse(any(r.startswith("frames/") for r in idx["files"]), "資源檔不進索引")
        self.assertEqual(idx["counts"]["asset"], 30, "但要計數")
        self.assertEqual(len(idx["cycles"]), 1)
        self.assertIn("pkg/big.py", md)
        self.assertIn("scripts/backtest/exitStrategy.ts", md, "腳本大檔也要列")
        self.assertTrue(any(p.get("file") == "scripts/backtest/exitStrategy.ts" and "（腳本）" in p["detail"] for p in idx["problems"]))
        kinds = {p["kind"] for p in idx["problems"]}
        self.assertEqual(kinds, {"cycle", "big-file"})
        self.assertTrue(any("npm run dev" in e for e in idx["entryPoints"]))
        r = subprocess.run([sys.executable, tool, str(tmp), "--check"], capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 0, "沒改檔 --check 要回 0")
        (tmp / "pkg" / "a.py").write_text("from pkg import b  # changed" + chr(10), encoding="utf-8")
        r = subprocess.run([sys.executable, tool, str(tmp), "--check"], capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 1)
        self.assertIn("pkg/a.py", r.stdout.decode("utf-8", "replace"))
        r = subprocess.run([sys.executable, tool, str(tmp), "--summary"], capture_output=True, env=ENV)
        self.assertIn("不算專案", r.stdout.decode("utf-8", "replace"), "4 個原始碼檔、沒 git → 小腳本資料夾")


class WebQuickConsistency(unittest.TestCase):
    """rules/web-quick.md（小檔）與 web-sources.md（完整版）要一致：小檔每個網址必須逐字存在於完整版；小檔要小（讀一次省 token 的意義才在）。"""

    def test_urls_exist_in_full_file_and_size(self):
        import re
        quick = (REPO / "rules" / "web-quick.md").read_text(encoding="utf-8")
        full = (REPO / "rules" / "web-sources.md").read_text(encoding="utf-8")
        urls = re.findall(r"https://[^\s`|）)]+", quick)
        self.assertGreater(len(urls), 10)
        for u in urls:
            self.assertIn(u, full, f"小檔的網址在完整版找不到：{u}")
        self.assertLess(len(quick), 12000, f"小檔 {len(quick)} 字，超過 12,000 就失去意義（完整版 34,000）")
        core = (REPO / "rules" / "core.md").read_text(encoding="utf-8")
        self.assertIn("web-quick.md", core, "core.md 要指到小檔")



def _load_scan():
    import importlib.util

    spec = importlib.util.spec_from_file_location("project_scan_wt", REPO / "tools" / "project-scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_dir_link(link: Path, target: Path) -> bool:
    """建目錄連結：Windows 用 junction（mklink /J，不需系統管理員），其他系統用 symlink。建不了回 False（測試略過）。"""
    try:
        if os.name == "nt":
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            return r.returncode == 0 and link.exists()
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


class ProjectScanWorktrees(unittest.TestCase):
    """0.16.0：Stock-web 11/8 盤點「被引用最多」出現 .claude/worktrees/agent-xxx/scripts/eval/types.ts 被 104 個檔引用。
    根因：depgraph 自己 os.walk 整個 root（不吃 project-scan 的排除），Windows 的 os.walk 還會走進 junction。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-wt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "proj"
        r = self.root
        (r / "src" / "lib").mkdir(parents=True)
        (r / "tsconfig.json").write_text('{\n // 註解\n "compilerOptions": {"paths": {"@/*": ["./src/*"]},},\n "include": ["**/*.ts"]\n}\n', encoding="utf-8")
        (r / "src" / "lib" / "types.ts").write_text("export type A = 1;\n", encoding="utf-8")
        for i in range(3):
            (r / "src" / f"u{i}.ts").write_text('import type { A } from "@/lib/types";\n', encoding="utf-8")
        # 巢狀 worktree（.git 是檔），名字刻意不叫 worktrees，靠 .git 判斷
        for wt in ("wt/agent-1", ".claude/worktrees/agent-2"):
            w = r / wt
            (w / "src" / "lib").mkdir(parents=True)
            (w / ".git").write_text("gitdir: x\n", encoding="utf-8")
            (w / "src" / "lib" / "types.ts").write_text("export type A = 1;\n", encoding="utf-8")
            for i in range(5):
                (w / "src" / f"u{i}.ts").write_text('import type { A } from "../src/lib/types";\nimport "./lib/types";\n', encoding="utf-8")
        # 目錄連結指向專案外的資料
        self.outside = self.tmp / "outside"
        (self.outside / "deep").mkdir(parents=True)
        (self.outside / "deep" / "x.ts").write_text('import "../y";\n', encoding="utf-8")
        self.linked = make_dir_link(r / "src" / "linkeddata", self.outside)

    def test_worktrees_and_links_not_counted(self):
        mod = _load_scan()
        d = mod.scan(self.root, 800)
        rels = set(d["files"])
        self.assertFalse(any(x.startswith(("wt/", ".claude/")) for x in rels), rels)
        hot = dict(d["mostDepended"])
        self.assertEqual(hot.get("src/lib/types.ts"), 3, "tsconfig 的 @/* → ./src/* 要解析到")
        self.assertFalse(any("agent-" in k for k in hot), hot)
        if self.linked:
            self.assertFalse(any("linkeddata" in x for x in rels), "junction／symlink 不跟隨")
        self.assertTrue((self.outside / "deep" / "x.ts").exists())

    def test_depgraph_collect_skips_links(self):
        if not self.linked:
            self.skipTest("建不了目錄連結")
        files = depgraph.collect_files((self.root / "src").as_posix())
        self.assertFalse(any("linkeddata" in f for f in files), files)

    def test_check_uses_mtime_shortcut(self):
        mod = _load_scan()
        d = mod.scan(self.root, 800)
        e = d["files"]["src/u0.ts"]
        self.assertIn("mtime", e)
        p = self.root / "src" / "u0.ts"
        self.assertFalse(mod._changed(p, e))
        self.assertFalse(mod._changed(p, {**e, "mtime": e["mtime"] - 5}), "時間不同但內容相同仍算沒改")
        self.assertTrue(mod._changed(p, {**e, "mtime": None, "sha256": "0"}), "舊索引沒有 mtime 就比雜湊")

    def test_jsonc_strip(self):
        mod = _load_scan()
        txt = '{"a": "http://x//y", /* c */ "b": [1, 2,], // z\n}'
        self.assertEqual(json.loads(mod._strip_jsonc(txt)), {"a": "http://x//y", "b": [1, 2]})


GIT_ENV = {**ENV, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=GIT_ENV)
    assert r.returncode == 0, (args, r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8", "replace")


class Cleanup(unittest.TestCase):
    """0.16.0 F：Stock-web 11/8 刪 worktree 前有 12 個 .cache 子目錄 junction 指向主目錄資料，直接遞迴刪會刪到主資料。"""

    def setUp(self):
        import importlib.util

        self.tmp = Path(tempfile.mkdtemp(prefix="cds-clean-longname-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        if os.name == "nt":  # 0.16.1：GitHub Actions 的暫存路徑是 RUNNER~1 短檔名，git 回長檔名 → 已登記的 worktree 被當成沒登記；這裡故意用短檔名重現
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(str(self.tmp), buf, 1024) and buf.value:
                self.tmp = Path(buf.value)
        spec = importlib.util.spec_from_file_location("cds_cleanup", REPO / "tools" / "cleanup.py")
        self.cl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cl)  # type: ignore[union-attr]

    def _repo(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".cache/\n", encoding="utf-8")
        _git(repo, "add", "a.txt", ".gitignore")
        _git(repo, "commit", "-qm", "init")
        return repo

    def _wt(self, repo, name, fname, merge=None):
        wt = repo / ".claude" / "worktrees" / name
        _git(repo, "worktree", "add", "-q", "-b", name, str(wt))
        (wt / fname).write_text(name + "\n", encoding="utf-8")
        _git(wt, "add", fname)
        _git(wt, "commit", "-qm", name)
        if merge == "merge":
            _git(repo, "merge", "-q", "--no-ff", "-m", "m", name)
        elif merge == "cherry":  # 等同 pull --rebase 改寫：內容在主分支、SHA 不同（主分支先前進一步，免得 cherry-pick 做出同一個 SHA）
            (repo / "main-only.txt").write_text("m" + chr(10), encoding="utf-8")
            _git(repo, "add", "main-only.txt")
            _git(repo, "commit", "-qm", "main moves")
            _git(repo, "cherry-pick", name)
        return wt

    def test_worktrees_merged_rebased_unmerged_dirty_and_junction(self):
        repo = self._repo()
        main_data = self.tmp / "maindata"
        main_data.mkdir()
        (main_data / "precious.json").write_text("{}", encoding="utf-8")
        a = self._wt(repo, "agent-a", "fa.txt", "merge")
        b = self._wt(repo, "agent-b", "fb.txt", "cherry")
        c = self._wt(repo, "agent-c", "fc.txt")
        d = self._wt(repo, "agent-d", "fd.txt", "merge")
        (d / "a.txt").write_text("dirty\n", encoding="utf-8")
        (a / ".cache").mkdir()
        linked = make_dir_link(a / ".cache" / "backtest", main_data)
        (repo / ".claude" / "worktrees" / "stray").mkdir()
        plan = {Path(it["path"]).name: it for it in self.cl.plan_worktrees(repo)}
        self.assertEqual(plan["agent-a"]["action"], "delete", plan["agent-a"])
        self.assertIn("SHA", plan["agent-a"]["why"])
        self.assertEqual(plan["agent-b"]["action"], "delete", "rebase／cherry-pick 後 SHA 不同但內容已在 → 可刪")
        self.assertIn("內容已在", plan["agent-b"]["why"])
        self.assertEqual(plan["agent-c"]["action"], "keep", "沒合併要保留")
        self.assertEqual(plan["agent-d"]["action"], "keep", "有未提交變更要保留")
        self.assertEqual(plan["stray"]["action"], "keep", "沒登記的資料夾只列不刪")
        if linked:
            self.assertEqual(len(plan["agent-a"]["links"]), 1)
        self.assertTrue(a.exists(), "預設只列清單，不刪")
        _freed, errors = self.cl.apply_plan(list(plan.values()), repo)
        self.assertEqual(errors, [])
        self.assertFalse(a.exists())
        self.assertFalse(b.exists())
        self.assertTrue(c.exists() and d.exists())
        self.assertTrue((main_data / "precious.json").exists(), "junction 指向的主資料不可被刪")
        self.assertIn("agent-a", _git(repo, "branch", "--list", "agent-a"), "分支預設保留")

    def test_safe_rmtree_does_not_follow_links_and_cache_plan(self):
        proj = self.tmp / "proj"
        (proj / ".next" / "server").mkdir(parents=True)
        (proj / ".next" / "server" / "x.js").write_text("x", encoding="utf-8")
        (proj / ".cache").mkdir()
        (proj / ".cache" / "data.json").write_text("{}", encoding="utf-8")
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("k", encoding="utf-8")
        linked = make_dir_link(proj / ".next" / "link", outside)
        items = self.cl.plan_cache(proj)
        self.assertEqual([Path(i["path"]).name for i in items], [".next"], ".cache 不算可重建快取")
        _freed, errors = self.cl.apply_plan(items, proj)
        self.assertEqual(errors, [])
        self.assertFalse((proj / ".next").exists())
        self.assertTrue((outside / "keep.txt").exists(), "連結指向的內容不可被刪")
        self.assertTrue((proj / ".cache" / "data.json").exists())
        if not linked:
            self.skipTest("建不了目錄連結，只驗了一般刪除")

    def test_temp_keeps_current_and_recent(self):
        import time as _t

        root = self.tmp / "claude"
        old = _t.time() - 5 * 86400
        for name in ("cur-session", "old-session", "new-session"):
            d = root / "f9e626e89eb6038f" / name / "scratchpad"
            d.mkdir(parents=True)
            (d / "x.md").write_text("x" * 100, encoding="utf-8")
            if name != "new-session":
                for p in (d / "x.md", d, d.parent):
                    os.utime(p, (old, old))
        plan = {Path(i["path"]).name: i for i in self.cl.plan_temp(root, 24, current="cur-session")}
        self.assertEqual(plan["cur-session"]["action"], "keep")
        self.assertEqual(plan["new-session"]["action"], "keep")
        self.assertEqual(plan["old-session"]["action"], "delete")
        r = subprocess.run([sys.executable, str(REPO / "tools" / "cleanup.py"), "--only", "temp", "--claude-temp", str(root)],
                           capture_output=True, env={**ENV, "CLAUDE_CODE_SESSION_ID": "cur-session"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("只列清單", r.stdout.decode("utf-8", "replace"))
        self.assertTrue((root / "f9e626e89eb6038f" / "old-session").exists(), "沒加 --apply 不刪")


class ResGate(unittest.TestCase):
    """0.16.0 E：使用者 2026-11-09「等 10 分鐘還不夠就不跑：直接回報「記憶體不足、沒有執行」」。"""

    def setUp(self):
        import importlib.util

        self.home = Path(tempfile.mkdtemp(prefix="cds-rg-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self._env = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.home)
        spec = importlib.util.spec_from_file_location("cds_resgate", REPO / "tools" / "resgate.py")
        self.rg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.rg)  # type: ignore[union-attr]

    def tearDown(self):
        if self._env is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self._env

    def test_config_single_source_and_project_override(self):
        cfgd = self.home / "claude-dev-system" / "config"
        cfgd.mkdir(parents=True)
        (cfgd / "dispatch-config.json").write_text(json.dumps({"resourceGate": {"minFreeMemGB": 5, "waitMinutes": 10, "pollSeconds": 60}}), encoding="utf-8")
        self.assertEqual(self.rg.load_cfg(str(self.home))["minFreeMemGB"], 5.0)
        proj = self.home / "p"
        (proj / ".claude").mkdir(parents=True)
        (proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"resourceGate": {"minFreeMemGB": 2}}), encoding="utf-8")
        self.assertEqual(self.rg.load_cfg(str(proj))["minFreeMemGB"], 2.0, "專案優先")
        self.assertEqual(json.loads((REPO / "config" / "dispatch-config.json").read_text(encoding="utf-8"))["resourceGate"]["minFreeMemGB"], 3,
                         "出廠值 3 GB（使用者：先設固定 3GB）")

    def test_wait_polls_then_gives_up_and_defers(self):
        cfg = {"minFreeMemGB": 3.0, "waitMinutes": 10.0, "pollSeconds": 60.0}
        clock = [0.0]
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            clock[0] += s
        ok, _free, waited = self.rg.wait(cfg, sleep=sleep, clock=lambda: clock[0], probe=lambda: 2.0)
        self.assertFalse(ok)
        self.assertLessEqual(waited, 600 - 15 + 0.01, "最後一次檢查在 10 分鐘前 15 秒，不被 Bash 10 分鐘上限砍掉")
        self.assertEqual(sleeps[0], 60.0, "每分鐘看一次")
        seq = iter([1.0, 1.5, 4.0])
        clock[0] = 0.0
        ok, free, _ = self.rg.wait(cfg, sleep=sleep, clock=lambda: clock[0], probe=lambda: next(seq))
        self.assertTrue(ok)
        self.assertEqual(free, 4.0)
        it1 = self.rg.defer("C:/p1", "回測 s1", "npm run bt", 2.0, 3.0)
        it2 = self.rg.defer("C:/p2", "全套測試", "npm test", 2.1, 3.0)
        items = self.rg.load_jobs()["items"]
        self.assertEqual([x["id"] for x in items], [it1["id"], it2["id"]], "依登記順序")
        self.assertEqual(Path(self.rg.deferred_path()).parent.name, "state")
        self.assertTrue(self.rg.done(it1["id"]))
        self.assertEqual([x["id"] for x in self.rg.load_jobs()["items"]], [it2["id"]])
        self.assertFalse(self.rg.enough({"minFreeMemGB": 3.0}, free=2.9)[0])
        self.assertTrue(self.rg.enough({"minFreeMemGB": 3.0}, free=3.0)[0])

    def _run(self, enough, args, quiet=True):
        """替換 wait（不真的等、不讀真實記憶體）後呼叫 main(['run', …])；回 (exit code, 標記檔是否存在)。"""
        marker = self.home / "ran.txt"
        self.rg.wait = lambda cfg: (True, 8.0, 0.0) if enough else (False, 1.9, 585.0)
        code = "import sys; open(r'%s','w').write('x'); sys.exit(%s)" % (marker, "%d")
        return marker, code

    def test_run_executes_and_passes_exit_code(self):
        for want in (0, 7):
            marker, code = self._run(True, None)
            if marker.exists():
                marker.unlink()
            rc = self.rg.main(["run", "--desc", "t", "--project", str(self.home), "--", sys.executable, "-c", code % want])
            self.assertEqual(rc, want, "exit code 透傳")
            self.assertTrue(marker.exists(), "記憶體夠要執行")
        self.assertEqual(self.rg.load_jobs()["items"], [], "夠就不登記延後清單")

    def test_run_insufficient_does_not_execute_and_defers(self):
        marker, code = self._run(False, None)
        rc = self.rg.main(["run", "--desc", "全套測試", "--project", str(self.home), "--", sys.executable, "-c", code % 0])
        self.assertNotEqual(rc, 0)
        self.assertFalse(marker.exists(), "記憶體不足不可執行")
        items = self.rg.load_jobs()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["desc"], "全套測試")
        self.assertIn("-c", items[0]["rerun"], "沒給 --rerun 時用 -- 後面的指令當重跑方式")
        wait_rc = self.rg.main(["wait", "--desc", "w", "--project", str(self.home)])
        self.assertEqual(wait_rc, rc, "不足時 exit code 與 wait 相同")

    def test_run_without_command_fails(self):
        marker, _ = self._run(True, None)
        self.assertNotEqual(self.rg.main(["run", "--desc", "t", "--project", str(self.home), "--"]), 0)
        self.assertNotEqual(self.rg.main(["run", "--desc", "t", "--project", str(self.home)]), 0)
        self.assertEqual(self.rg.load_jobs()["items"], [])


class Procs(unittest.TestCase):
    """0.16.0 C：Stock-web 11/8 agent 留下 until … sleep 10 迴圈＋tail.exe，交報告後空轉到隔天，巡檢沒抓到。"""

    def test_leftovers_from_fake_table(self):
        import procs

        now = 1_000_000.0
        loop = "until [ $(grep -c FULL run-s1.log) -ge 13 ]; do sleep 10; done"
        rows = [
            {"pid": 1, "ppid": 0, "name": "claude.exe", "start": now - 99999},
            {"pid": 10, "ppid": 1, "name": "bash.exe", "start": now - 5 * 3600,
             "cmd": "bash.exe -c \"source /c/x/shell-snapshots/s.sh && eval '" + loop + "' < /dev/null && pwd -P\""},
            {"pid": 11, "ppid": 10, "name": "sleep.exe", "start": now - 5},
            {"pid": 20, "ppid": 1, "name": "bash.exe", "start": now - 3 * 3600, "cmd": "tail -f run-s1.log"},
            {"pid": 21, "ppid": 20, "name": "tail.exe", "start": now - 3 * 3600, "cmd": "tail -f run-s1.log"},
            {"pid": 30, "ppid": 1, "name": "bash.exe", "start": now - 60, "cmd": "npm test"},
            {"pid": 40, "ppid": 1, "name": "node.exe", "start": now - 9999, "cmd": "npx some-mcp"},
            {"pid": 50, "ppid": 1, "name": "bash.exe", "start": now - 9999, "cmd": "self"},
            {"pid": 60, "ppid": 777, "name": "bash.exe", "start": now - 7200,
             "cmd": "bash -c \"source /c/x/shell-snapshots/s.sh && cd C:/proj && eval 'sleep 9999' < /dev/null\""},
        ]
        g = procs.leftovers(rows, lambda r: None, 1, 60, now=now, exclude={50}, cwd_hint="C:/proj")
        self.assertEqual([x["pid"] for x in g], [10, 20, 60], "才 1 分鐘的、MCP 等非工具殼、自己這條都不列")
        self.assertEqual(g[0]["cmd"], loop, "只留真正的指令")
        self.assertEqual([c["name"] for c in g[1]["children"]], ["tail.exe"])
        self.assertTrue(g[2]["orphan"])
        self.assertIn("5 小時", procs.fmt(g))

    def test_real_snapshot_is_fast(self):
        import time as _t

        import procs

        t0 = _t.time()
        rows, _d = procs.snapshot()
        self.assertTrue(rows)
        self.assertLess(_t.time() - t0, 2.0)
        self.assertIsInstance(procs.session_leftovers(10_000), list)
