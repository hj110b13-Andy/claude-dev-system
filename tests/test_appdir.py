"""appdir（執行檔模式的可更新資料夾）測試：有效 repo 選擇、檢查更新、下載換掉 app/（假 HTTP，不上網）。"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))

from cds import appdir  # noqa: E402
from cds.paths import Layout  # noqa: E402


def fake_zip(version: str, extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        top = "claude-dev-system-master/"
        z.writestr(top + "config/VERSION", version + "\n")
        z.writestr(top + "rules/core.md", "# core " + version)
        z.writestr(top + "installer/install.py", "print(1)")
        z.writestr(top + "installer/cds/paths.py", "x=1")
        z.writestr(top + "README.md", "readme")
        z.writestr(top + "tests/test_x.py", "should not be copied")
        z.writestr(top + "../evil.txt", "nope")
        for k, v in (extra or {}).items():
            z.writestr(top + k, v)
    return buf.getvalue()


class AppDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-app-"))
        self.lay = Layout(self.tmp)
        self.bundled = self.tmp / "bundled"
        (self.bundled / "config").mkdir(parents=True)
        (self.bundled / "rules").mkdir()
        (self.bundled / "installer").mkdir()
        (self.bundled / "config" / "VERSION").write_text("1.2.0\n", encoding="utf-8")
        (self.bundled / "rules" / "core.md").write_text("b", encoding="utf-8")
        (self.bundled / "installer" / "install.py").write_text("print(0)", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_effective_repo_prefers_newer_app_dir(self):
        self.assertEqual(appdir.effective_repo(self.lay, self.bundled), self.bundled, "沒有 app/ 用內建")
        logs = []
        appdir.download_update(self.lay, logs.append, http=lambda url, t=60: fake_zip("1.3.0"))
        a = appdir.app_dir(self.lay)
        self.assertEqual(appdir.effective_repo(self.lay, self.bundled), a)
        self.assertEqual((a / "config" / "VERSION").read_text(encoding="utf-8").strip(), "1.3.0")
        self.assertFalse((a / "tests").exists(), "只取需要的資料夾")
        self.assertFalse((self.tmp / "evil.txt").exists() and True, "路徑穿越不可落地")
        self.assertFalse(list(self.tmp.rglob("evil.txt")))
        self.assertTrue((a / "README.md").exists())
        self.assertTrue(any("1.3.0" in x for x in logs))
        # app/ 比內建舊 → 用內建
        (a / "config" / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        self.assertEqual(appdir.effective_repo(self.lay, self.bundled), self.bundled)

    def test_check_update(self):
        info = appdir.check_update(self.lay, self.bundled, http=lambda url, t=20: b"1.2.1\n")
        self.assertTrue(info["newer"] and info["remote"] == "1.2.1" and info["local"] == "1.2.0")
        info = appdir.check_update(self.lay, self.bundled, http=lambda url, t=20: b"1.2.0\n")
        self.assertFalse(info["newer"])

        def boom(url, t=20):
            raise OSError("offline")
        info = appdir.check_update(self.lay, self.bundled, http=boom)
        self.assertFalse(info["newer"])
        self.assertIn("連不上", info["error"])
        info = appdir.check_update(self.lay, self.bundled, http=lambda url, t=20: b"<html>not a version</html>")
        self.assertIsNotNone(info["error"])

    def test_bad_download_keeps_old_app(self):
        appdir.download_update(self.lay, lambda s: None, http=lambda url, t=60: fake_zip("1.3.0"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("claude-dev-system-master/README.md", "no version")
        with self.assertRaises(RuntimeError):
            appdir.download_update(self.lay, lambda s: None, http=lambda url, t=60: buf.getvalue())
        self.assertEqual((appdir.app_dir(self.lay) / "config" / "VERSION").read_text(encoding="utf-8").strip(), "1.3.0", "壞下載不動舊 app/")

    def test_code_changed_detection(self):
        appdir.download_update(self.lay, lambda s: None, http=lambda url, t=60: fake_zip("1.3.0"))
        self.assertTrue(appdir.code_changed_since(self.bundled, appdir.app_dir(self.lay)))
        self.assertFalse(appdir.code_changed_since(self.bundled, self.bundled))

    def test_exe_update_check_download_swap(self):
        import json
        exe_bytes = b"MZ" + bytes(1_200_000)
        import hashlib
        sha = hashlib.sha256(exe_bytes).hexdigest()
        rel = {"tag_name": "v1.3.0", "assets": [
            {"name": appdir.EXE_NAME, "browser_download_url": "https://x/exe", "size": len(exe_bytes)},
            {"name": appdir.EXE_NAME + ".sha256", "browser_download_url": "https://x/sha"}]}

        def http(url, t=20):
            if url == appdir.LATEST_API:
                return json.dumps(rel).encode()
            if url == "https://x/exe":
                return exe_bytes
            if url == "https://x/sha":
                return (sha + "  " + appdir.EXE_NAME).encode()
            raise AssertionError(url)
        info = appdir.check_exe_update("1.2.0", http=http)
        self.assertTrue(info["newer"] and info["sha_url"], info)
        self.assertFalse(appdir.check_exe_update("1.3.0", http=http)["newer"], "同版不換")
        self.assertIn("查不到", appdir.check_exe_update("1.0", http=lambda u, t=20: (_ for _ in ()).throw(OSError("x")))["error"])
        self.assertIn("沒有附 exe", appdir.check_exe_update("1.0", http=lambda u, t=20: b'{"tag_name":"v9","assets":[]}')["error"])
        exe = self.tmp / "cds.exe"
        exe.write_bytes(b"MZ-old")
        logs = []
        new = appdir.download_exe(info, exe, logs.append, http=http)
        self.assertEqual(new.name, "cds.new.exe")
        with self.assertRaises(ValueError):
            appdir.download_exe({**info, "size": 5}, exe, logs.append, http=http)
        bad = dict(http=lambda u, t=20: b"deadbeef  x" if u == "https://x/sha" else http(u, t))
        with self.assertRaises(ValueError):
            appdir.download_exe(info, exe, logs.append, **bad)
        old = appdir.swap_exe(exe, new)
        self.assertEqual(exe.read_bytes(), exe_bytes, "新的改成原名")
        self.assertEqual(old.read_bytes(), b"MZ-old")
        self.assertFalse(new.exists())
        self.assertEqual(appdir.cleanup_old_exe(exe), 1)
        self.assertFalse(old.exists())
        # 換不成要還原
        exe2 = self.tmp / "b.exe"
        exe2.write_bytes(b"MZ-b")
        with self.assertRaises(FileNotFoundError):
            appdir.swap_exe(exe2, self.tmp / "nope.new.exe")
        self.assertEqual(exe2.read_bytes(), b"MZ-b")


if __name__ == "__main__":
    unittest.main()
