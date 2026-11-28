"""0.32.2：Windows 專用規則 core-windows.md 只在 Windows 併進全域 CLAUDE.md。"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "installer"))
from cds import payload  # noqa: E402


class CoreWindows(unittest.TestCase):
    def test_windows_appends(self):
        t = payload.core_rules(REPO, "win32")
        self.assertIn("UTF-8 with BOM", t)
        self.assertIn("OutputEncoding", t)
        self.assertTrue(t.startswith((REPO / "rules" / "core.md").read_text(encoding="utf-8").rstrip("\n")))

    def test_other_platforms_skip(self):
        for p in ("darwin", "linux"):
            self.assertNotIn("UTF-8 with BOM", payload.core_rules(REPO, p))


if __name__ == "__main__":
    unittest.main()
