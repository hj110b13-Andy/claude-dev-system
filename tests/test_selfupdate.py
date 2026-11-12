"""selfupdate_exe.py（exe 更新備援）：假 appdir 函式，不上網。"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))

import selfupdate_exe as su  # noqa: E402
from cds import appdir  # noqa: E402


class SelfUpdate(unittest.TestCase):
    def setUp(self):
        self.saved = (appdir.check_exe_update, appdir.download_exe, appdir.swap_exe)
        from unittest import mock  # 這個測試檔不可連網：萬一哪裡沒換成假的，真的連線會在這裡失敗而不是無聲通過
        for target in ("socket.socket.connect", "socket.create_connection"):
            p = mock.patch(target, side_effect=OSError("測試不可連網"))
            p.start()
            self.addCleanup(p.stop)

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
        """命令列入口：假的網路層，不連 api.github.com（原本這個測試會真的連網，離線也照樣通過，證明不了網路路徑能用）。"""
        import contextlib
        import io
        import json
        appdir.check_exe_update = lambda cur: {"tag": "99.0.1", "newer": True, "error": None, "url": "u", "size": 1, "sha_url": None}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = su.main(["--exe", "C:/nope/x.exe", "--current", "99.0.0", "--check-only"])
        self.assertEqual(rc, 0)
        last = buf.getvalue().strip().splitlines()[-1]
        d = json.loads(last)
        self.assertEqual((d["newer"], d["tag"], d["swapped"], d["error"]), (True, "99.0.1", False, None))

    def test_cli_script_runs_as_subprocess_without_network(self):
        """真的用 python 跑腳本（參數解析、sys.path 設定、輸出最後一行是 JSON），但網路在子程序裡被封掉：查不到 Releases 要回 error 而不是例外。"""
        import json
        code = ("import socket,sys,runpy;"
                "socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(OSError('no network in test'));"
                "socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(OSError('no network in test'));"
                "sys.argv=[sys.argv[1],'--exe','C:/nope/x.exe','--current','99.0.0','--check-only'];"
                "runpy.run_path(sys.argv[0],run_name='__main__')")
        r = subprocess.run([sys.executable, "-c", code, str(REPO / "installer" / "selfupdate_exe.py")], capture_output=True, timeout=120)
        d = json.loads((r.stdout or b"").decode().strip().splitlines()[-1])
        self.assertFalse(d["newer"] or d["swapped"])
        self.assertTrue(d["error"], "封網時要回 error 欄位（備援才會啟動）")

    def test_invalid_tag_gives_error_field_not_exception(self):
        """GU-03：Release tag 不是版本號（latest、vtest）時，run() 回 error 欄位——視窗才會改走備援，而不是整個丟例外。"""
        import json
        body = json.dumps({"tag_name": "vtest", "assets": [{"name": appdir.EXE_NAME, "browser_download_url": "https://x/e", "size": 1}]}).encode()
        appdir.check_exe_update = lambda cur, _orig=self.saved[0]: _orig(cur, http=lambda u, t=20: body)
        r = su.run(Path("C:/a/x.exe"), "1.0.0")
        self.assertTrue(r["error"])
        self.assertFalse(r["swapped"] or r["newer"])


if __name__ == "__main__":
    unittest.main()
