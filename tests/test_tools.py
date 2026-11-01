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
        (tmp / "tests").mkdir()
        (tmp / "tests" / "test_a.py").write_text("def test(): pass" + chr(10), encoding="utf-8")
        (tmp / "package.json").write_text('{"scripts": {"dev": "next dev"}}', encoding="utf-8")
        (tmp / "node_modules").mkdir()
        (tmp / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
        tool = str(REPO / "tools" / "project-scan.py")
        r = subprocess.run([sys.executable, tool, str(tmp), "--max-lines", "800"], capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        md = (tmp / "docs" / "PROJECT-INVENTORY.md").read_text(encoding="utf-8")
        idx = json.loads((tmp / ".claude" / "project-scan.json").read_text(encoding="utf-8"))
        self.assertEqual(idx["counts"]["source"], 4, idx["counts"])
        self.assertEqual(idx["counts"]["test"], 1)
        self.assertNotIn("node_modules/junk.js", idx["files"])
        self.assertEqual(len(idx["cycles"]), 1)
        self.assertIn("pkg/big.py", md)
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

