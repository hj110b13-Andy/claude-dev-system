"""install.py 命令列入口測試：子命令分派、結束碼（0／1／2）、--claude-home 優先於環境變數、金鑰不印出。

起因：2026-11-12 全方位健檢量覆蓋率，installer/install.py 是 0%——每個子命令的實作都有測，但「命令列怎麼接到實作、回什麼結束碼」沒有任何測試。
全部在暫存資料夾跑；不啟用聯網與影片來源（不會呼叫 claude、pip 或任何外部服務）。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))

import install  # noqa: E402
from cds import checks  # noqa: E402
from cds.paths import Layout, repo_version  # noqa: E402

SECRET = "tvly-SECRET-0123456789abcdef"


def run(*argv: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = install.main(list(argv))
        except SystemExit as e:  # argparse 的用法錯誤
            code = int(e.code or 0)
    return code, out.getvalue() + err.getvalue()


class CliBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-cli-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.lay = Layout(self.home)
        self.h = ("--claude-home", str(self.home))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ExitCodes(CliBase):
    def test_full_cycle_exit_codes(self):
        code, out = run(*self.h, "status")
        self.assertEqual(code, 0)
        self.assertIn("未安裝", out)
        code, out = run(*self.h, "update")
        self.assertEqual(code, 2, "還沒安裝就 update 是狀態錯誤")
        code, out = run(*self.h, "verify", "--no-claude")
        self.assertEqual(code, 1, "還沒安裝時 verify 要回 1")

        code, out = run(*self.h, "install")
        self.assertEqual(code, 0, out)
        self.assertTrue(self.lay.manifest.exists())
        code, out = run(*self.h, "install")
        self.assertEqual(code, 2, "重複 install 要擋")

        code, out = run(*self.h, "verify", "--no-claude")
        self.assertEqual(code, 0, out)
        self.assertIn("全部通過", out)
        code, out = run(*self.h, "status")
        self.assertEqual(code, 0)
        self.assertIn(f"已安裝 v{repo_version(REPO)}", out)

        code, out = run(*self.h, "update")
        self.assertEqual(code, 0, out)
        code, out = run(*self.h, "uninstall")
        self.assertEqual(code, 0, out)
        self.assertFalse(self.lay.manifest.exists())
        code, out = run(*self.h, "verify", "--no-claude")
        self.assertEqual(code, 1)

    def test_unknown_command_is_usage_error(self):
        code, out = run(*self.h, "frobnicate")
        self.assertEqual(code, 2)
        self.assertFalse(self.lay.payload.exists(), "用法錯誤不可以寫任何檔")

    def test_web_and_video_require_install(self):
        for cmd in (("web", "--show"), ("video", "--show")):
            code, out = run(*self.h, *cmd)
            self.assertEqual(code, 2, cmd)
            self.assertIn("尚未安裝", out)


class HomeResolution(CliBase):
    def test_flag_beats_env_and_env_beats_default(self):
        other = self.tmp / "env-home"
        other.mkdir()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(other)}):
            code, out = run(*self.h, "install")
            self.assertEqual(code, 0, out)
            self.assertTrue(self.lay.manifest.exists(), "--claude-home 要優先於 CLAUDE_CONFIG_DIR")
            self.assertFalse(Layout(other).manifest.exists())
            code, out = run("install")  # 沒給旗標：用環境變數
            self.assertEqual(code, 0, out)
            self.assertTrue(Layout(other).manifest.exists())


class LocalPrefs(CliBase):
    def setUp(self):
        super().setUp()
        code, out = run(*self.h, "install")
        self.assertEqual(code, 0, out)
        self.local = self.lay.payload / "config" / "local.json"

    def test_key_is_saved_but_never_printed(self):
        code, out = run(*self.h, "web", "--key", f"tavily={SECRET}", "--show")
        self.assertEqual(code, 0, out)
        self.assertNotIn(SECRET, out, "金鑰值不可出現在輸出")
        self.assertIn("tavily", out)
        self.assertEqual(json.loads(self.local.read_text(encoding="utf-8"))["keys"]["tavily"], SECRET)
        code, out = run(*self.h, "web", "--show")
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET, out)

    def test_bad_arguments_are_rejected_without_writing(self):
        for args in (("--key", "沒有等號"), ("--env", "lower=1"), ("--key-mode", "tavily=sometimes"), ("--enable", "no-such-mcp")):
            code, out = run(*self.h, "web", *args, "--show")
            self.assertEqual(code, 2, args)
            self.assertFalse(self.local.exists(), f"{args} 被拒絕時不該寫 local.json")

    def test_broken_local_json_gives_one_line_not_traceback(self):
        self.local.write_text("{壞掉", encoding="utf-8")
        for cmd in (("web", "--show"), ("video", "--show")):
            code, out = run(*self.h, *cmd)
            self.assertEqual(code, 2, cmd)
            self.assertIn("不是合法 JSON", out)
            self.assertNotIn("Traceback", out)
        self.assertEqual(self.local.read_text(encoding="utf-8"), "{壞掉", "壞檔不可被覆寫")

    def test_usage_guard_switch_roundtrip(self):
        code, out = run(*self.h, "web", "--usage-guard", "off", "--show")
        self.assertEqual(code, 0, out)
        self.assertIs(json.loads(self.local.read_text(encoding="utf-8"))["usageGuard"], False)
        code, out = run(*self.h, "update")
        self.assertEqual(code, 0, out)
        hooks = json.loads(self.lay.settings.read_text(encoding="utf-8")).get("hooks") if self.lay.settings.exists() else None
        self.assertFalse(hooks, "關掉用量守門後 update 要把 hook 條目清掉")
        code, out = run(*self.h, "verify", "--no-claude")
        self.assertEqual(code, 0, out)
        code, out = run(*self.h, "web", "--usage-guard", "on", "--show")
        self.assertEqual(code, 0, out)
        code, out = run(*self.h, "update")
        self.assertEqual(code, 0, out)
        self.assertIn("UserPromptSubmit", json.loads(self.lay.settings.read_text(encoding="utf-8"))["hooks"])


class CheckCommand(CliBase):
    """`check`：❌ 才回 1；⚠️（找不到 claude、資料夾還不存在）不擋。版本來源用假的，不真的呼叫 claude／node／git。"""

    def _versions(self, claude: str | None):
        table = {"claude": claude, "node": "v22.0.0", "git": "git version 2.47.0"}
        return mock.patch.object(checks, "run_version", lambda cmd: table.get(cmd[0]))

    def test_supported_version_passes(self):
        tested = checks.compat(REPO)["claudeCode"]["tested"][0]
        with self._versions(f"{tested} (Claude Code)"):
            code, out = run(*self.h, "check")
        self.assertEqual(code, 0, out)
        self.assertIn("已實測", out)

    def test_missing_claude_is_warning_not_failure(self):
        with self._versions(None):
            code, out = run(*self.h, "check")
        self.assertEqual(code, 0, out)
        self.assertIn("找不到 claude 指令", out)

    def test_out_of_range_version_fails(self):
        with self._versions("99.0.0 (Claude Code)"):
            code, out = run(*self.h, "check")
        self.assertEqual(code, 1, out)
        self.assertIn("超出範圍", out)

    def test_broken_settings_json_fails(self):
        (self.home / "settings.json").write_text("{not json", encoding="utf-8")
        with self._versions(None):
            code, out = run(*self.h, "check")
        self.assertEqual(code, 1, out)
        self.assertIn("不是合法 JSON", out)


class SelftestCommand(CliBase):
    def test_list_and_unknown_id(self):
        ids = [c["id"] for c in json.loads((REPO / "config" / "selftest.json").read_text(encoding="utf-8"))["cases"]]
        code, out = run("selftest", "--list")
        self.assertEqual(code, 0, out)
        for i in ids:
            self.assertIn(i, out)
        code, out = run("selftest", "--list", "--only", "沒有這題")
        self.assertEqual(code, 2)
        code, out = run("selftest", "--list", "--only", ",".join(ids[:2]))
        self.assertEqual(code, 0)
        self.assertEqual(len([ln for ln in out.splitlines() if ln.strip()]), 2, "--only 可以用逗號一次給多題")


if __name__ == "__main__":
    unittest.main()
