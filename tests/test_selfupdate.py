"""selfupdate_exe.py（exe 更新備援）：假 appdir 函式，不上網。"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))

import selfupdate_exe as su  # noqa: E402
from cds import appdir  # noqa: E402


class SelfUpdate(unittest.TestCase):
    def setUp(self):
        self.saved = (appdir.check_exe_update, appdir.download_exe, appdir.swap_exe)

    def tearDown(self):
        appdir.check_exe_update, appdir.download_exe, appdir.swap_exe = self.saved

    def test_swap_check_only_and_errors(self):
        swapped = []
        appdir.check_exe_update = lambda cur: {"tag": "9.9.9", "newer": True, "error": None, "url": "u", "size": 1, "sha_url": None}
        appdir.download_exe = lambda info, exe, log: exe.with_name("x.new.exe")
        appdir.swap_exe = lambda exe, new: swapped.append((exe, new))
        r = su.run(Path("C:/a/x.exe"), "1.0.0", check_only=True)
        self.assertEqual((r["newer"], r["swapped"], swapped), (True, False, []), "check-only 不換")
        r = su.run(Path("C:/a/x.exe"), "1.0.0")
        self.assertTrue(r["swapped"] and len(swapped) == 1)
        appdir.check_exe_update = lambda cur: {"tag": None, "newer": False, "error": "查不到 Releases"}
        self.assertEqual(su.run(Path("C:/a/x.exe"), "1.0.0")["error"], "查不到 Releases")
        appdir.check_exe_update = lambda cur: (_ for _ in ()).throw(OSError("boom"))
        self.assertIn("boom", su.run(Path("C:/a/x.exe"), "1.0.0")["error"])

    def test_cli_prints_json_last_line(self):
        r = subprocess.run([sys.executable, str(REPO / "installer" / "selfupdate_exe.py"), "--exe", "C:/nope/x.exe", "--current", "99.0.0", "--check-only"],
                           capture_output=True, timeout=120)
        import json
        last = (r.stdout or b"").decode().strip().splitlines()[-1]
        d = json.loads(last)
        self.assertIn("newer", d)
        self.assertFalse(d["swapped"])


if __name__ == "__main__":
    unittest.main()
