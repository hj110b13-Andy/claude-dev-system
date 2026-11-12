"""獨立審查（2026-11-12，健檢第二階段修正合併後）找到的回歸與邊界問題 RV-01～05 的回歸測試。

起因：五個 agent 分模組修完 100 多條問題後，另派一個沒參與修正的 agent 審查整批 diff，找到 7 條「修正引入的新問題」——
人工字幕被自動字幕蓋過、視窗對沒動過的欄位也驗證、解除安裝未完成的紀錄被當成已安裝、Next.js worktree 永遠清不掉、
depgraph 單獨複製走時用 exit 1 崩潰。RV-02（視窗層）沒辦法在不開視窗的情況下寫成單元測試，只有手動腳本驗證。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))
sys.path.insert(0, str(REPO / "tools"))

import cleanup  # noqa: E402
import video  # noqa: E402
from cds import commands, manifest as mf  # noqa: E402
from cds.paths import Layout  # noqa: E402

PREFER = ["zh-TW", "zh-Hant", "zh", "en"]


class RV01_ManualCaptionsOfSameLanguageWin(unittest.TestCase):
    def test_manual_variant_not_in_prefer_list_beats_auto(self):
        for manual in ("zh-CN", "zh-HK"):
            choice, _ = video.choose_caption([manual], ["zh"], PREFER, "zh")
            self.assertEqual(choice, (manual, "manual"), "與影片同語系的人工字幕要優先於自動字幕")
        choice, _ = video.choose_caption(["en-GB"], ["en"], PREFER, "en")
        self.assertEqual(choice, ("en-GB", "manual"))
        choice, _ = video.choose_caption(["ko"], ["ko"], PREFER, "ko")
        self.assertEqual(choice, ("ko", "manual"))

    def test_original_ta14_case_still_picks_native_auto(self):
        choice, _ = video.choose_caption(["es"], ["en"], PREFER, "en")
        self.assertEqual(choice, ("en", "auto"), "英文影片只有西班牙文人工字幕：仍要拿英文自動字幕，不是翻譯稿")

    def test_common_cases_unchanged(self):
        self.assertEqual(video.choose_caption([], ["zh"], PREFER, "zh")[0], ("zh", "auto"))
        self.assertEqual(video.choose_caption(["zh-TW"], ["zh"], PREFER, "zh")[0], ("zh-TW", "manual"))
        self.assertEqual(video.choose_caption(["en", "ja"], ["ja"], PREFER, "ja")[0], ("en", "manual"), "偏好語言有人工字幕就用它")


class RV03_IncompleteUninstallRecord(unittest.TestCase):
    """uninstall 的 MCP 移除失敗後，安裝紀錄只剩「還沒移掉的 MCP 名稱」、沒有版本。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-rv03-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lay = Layout(self.tmp)
        rest = mf.empty()
        rest["web"]["mcpAdded"] = ["exa", "parallel"]
        mf.save(self.lay.manifest, rest)

    def test_helper(self):
        self.assertTrue(commands.incomplete_uninstall(mf.load(self.lay.manifest)))
        self.assertFalse(commands.incomplete_uninstall(None))
        self.assertFalse(commands.incomplete_uninstall({**mf.empty(), "version": "0.27.0"}))

    def test_status_says_incomplete_not_installed_vNone(self):
        code, out = commands.status(self.lay, repo=REPO)
        text = chr(10).join(out)
        self.assertEqual(code, 0)
        self.assertIn("上次解除安裝沒有完成", text)
        self.assertIn("exa", text)
        self.assertNotIn("vNone", text)

    def test_verify_is_one_clear_line(self):
        code, out = commands.verify(self.lay, repo=REPO, check_claude=False)
        self.assertEqual(code, 1)
        self.assertEqual(len(out), 1, out)
        self.assertIn("上次解除安裝沒有完成", out[0])

    def test_web_and_video_refuse_without_traceback(self):
        for call in (lambda: commands.web_config(self.lay, show=True),
                     lambda: commands.web_config(self.lay, keys=["youtube=x"]),
                     lambda: commands.video_config(self.lay, sys.executable, show=True)):
            code, out = call()
            self.assertEqual(code, 2)
            self.assertIn("上次解除安裝沒有完成", chr(10).join(out))
        self.assertFalse((self.lay.payload / "config" / "local.json").exists(), "被拒絕時不寫任何檔")


class RV04_RebuildableIgnoredFiles(unittest.TestCase):
    def test_generated_files_are_not_precious_but_data_is(self):
        lines = ["!! next-env.d.ts", "!! tsconfig.tsbuildinfo", "!! apps/web/tsconfig.tsbuildinfo", "!! node_modules/",
                 "!! node_modules/.cache/x", "!! .next/", "!! .cache/prices.json", "!! .env", "!! out/result.csv", " M src/a.ts"]
        self.assertEqual(cleanup.ignored_precious(lines), [".cache/prices.json", ".env", "out/result.csv"])

    def test_dot_cache_outside_node_modules_is_precious(self):
        self.assertNotIn(".cache", cleanup.REBUILDABLE, "worktree 根目錄的 .cache 常放資料，不可當成可重建")
        self.assertIn("node_modules", cleanup.REBUILDABLE)


class RV05_DepgraphAlone(unittest.TestCase):
    def test_missing_project_scan_is_exit_2_with_one_line(self):
        tmp = Path(tempfile.mkdtemp(prefix="cds-rv05-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(REPO / "tools" / "depgraph.py", tmp / "depgraph.py")
        (tmp / "proj").mkdir()
        (tmp / "proj" / "a.py").write_text("x = 1" + chr(10), encoding="utf-8")
        r = subprocess.run([sys.executable, str(tmp / "depgraph.py"), str(tmp / "proj")], capture_output=True, timeout=60)
        err = r.stderr.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 2, err)
        self.assertIn("project-scan.py", err)
        self.assertNotIn("Traceback", err)


class CI_FirstRunOnOtherVersionsAndPlatforms(unittest.TestCase):
    """2026-11-12 第一次讓 CI 在 Python 3.10 與 ubuntu／macos 跑測試才發現的問題。"""

    def _scan(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cds_scan_rvtest", REPO / "tools" / "project-scan.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @unittest.skipUnless(os.name == "nt", "junction 是 Windows 才有的")
    def test_junction_detected_without_os_path_isjunction(self):
        """Python 3.10／3.11 沒有 os.path.isjunction：原本直接當成「不是連結」，cleanup 會跟著 junction 刪到外面的資料。"""
        tmp = Path(tempfile.mkdtemp(prefix="cds-junc-"))
        target, link, plain = tmp / "target", tmp / "link", tmp / "plain"
        target.mkdir()
        plain.mkdir()
        (target / "precious.txt").write_text("x", encoding="utf-8")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        self.addCleanup(shutil.rmtree, tmp, True)
        self.addCleanup(lambda: os.path.lexists(link) and os.rmdir(link))  # 先拆連結，rmtree 才不會碰到目標
        if r.returncode != 0:
            self.skipTest("建不了 junction")
        scan = self._scan()
        with mock.patch.object(os.path, "isjunction", None, create=True):  # 模擬 3.10／3.11
            self.assertTrue(scan.is_link_dir(str(link)), "沒有 isjunction 時也要認得 junction")
            self.assertFalse(scan.is_link_dir(str(plain)), "一般資料夾不是連結")
            self.assertTrue(cleanup._is_link_dir_fallback(str(link)))
            self.assertFalse(cleanup._is_link_dir_fallback(str(plain)))
        self.assertTrue(scan.is_link_dir(str(link)))

    def test_ps_etime_parsing(self):
        import procs
        self.assertEqual(procs._etime_seconds("00:05"), 5)
        self.assertEqual(procs._etime_seconds("12:34"), 12 * 60 + 34)
        self.assertEqual(procs._etime_seconds("01:02:03"), 3723)
        self.assertEqual(procs._etime_seconds("2-03:04:05"), 2 * 86400 + 3 * 3600 + 4 * 60 + 5)


if __name__ == "__main__":
    unittest.main()
