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


if __name__ == "__main__":
    unittest.main()
