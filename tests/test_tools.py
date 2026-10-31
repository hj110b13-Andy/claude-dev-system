"""通用工具測試：depgraph（循環偵測、別名、分層規則）、progress-diff（遺漏句偵測）。"""
from __future__ import annotations

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
                self.assertEqual((lim["fiveHourLimit"], lim["sevenDayLimit"]), (80.0, 97.0))
                self.assertEqual(src, "內建預設")
            finally:
                ug.CONFIG = old

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
