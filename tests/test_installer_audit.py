"""2026-11-12 全方位健檢第二階段（fix-installer）的回歸測試：每個類別對應稽核報告的一條（A、IN-01～IN-15、Q）。

全部在暫存資料夾跑；MCP 用 test_installer 的假 runner，不呼叫真的 claude、pip，不上網，不碰真實 ~/.claude。
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cds import claudemd, commands, fsio, manifest as mf, paths, settings_ops, web  # noqa: E402
from cds.paths import Layout  # noqa: E402
from test_installer import PY, USER_SETTINGS, Base, fake_mcp_runner  # noqa: E402

NL = chr(10)


def marked_count(s: dict) -> int:
    return sum(len(settings_ops.has_marked(s, e)) for e, _ in settings_ops.HOOK_SPECS)


class A_RestoreBackup(Base):
    """A：--restore-backup 只用安裝前那筆；update 超過 KEEP_BACKUPS 次、安裝前沒有 settings.json 都不可把指向已刪腳本的 hook 寫回。"""

    def test_many_updates_still_restore_pre_install(self):
        raw = json.dumps(USER_SETTINGS, ensure_ascii=False, indent=4)
        self.write_settings(None, raw)
        self.install()
        for _ in range(commands.KEEP_BACKUPS + 1):
            self.install(mode="update")
        m = mf.load(self.lay.manifest)
        self.assertEqual(len(m["backups"]), commands.KEEP_BACKUPS)
        self.assertTrue(m["backups"][0].get("preInstall"), "安裝前那筆要永遠留在第一個")
        self.assertEqual(len(list(self.lay.backups.glob("claude-dev-system-*.json"))), commands.KEEP_BACKUPS)
        code, log = commands.uninstall(self.lay, restore_backup=True)
        self.assertEqual(code, 0, NL.join(log))
        self.assertEqual(self.lay.settings.read_text(encoding="utf-8"), raw, "還原的是安裝前原檔（含排版）")
        self.assertEqual(marked_count(self.settings()), 0)

    def test_no_settings_before_install_is_not_restored(self):
        self.install()
        self.install(mode="update")
        m = mf.load(self.lay.manifest)
        self.assertTrue(m["backups"][0]["preInstall"])
        self.assertIsNone(m["backups"][0]["settings"], "安裝前沒有 settings.json 也要記一筆")
        code, log = commands.uninstall(self.lay, restore_backup=True)
        self.assertEqual(code, 0, NL.join(log))
        self.assertFalse(self.lay.settings.exists(), "安裝前沒有這個檔，就不可寫回安裝後的備份")
        self.assertTrue(any(x.startswith("⚠️") and "安裝前沒有 settings.json" in x for x in log))

    def test_pre_install_backup_with_marked_hooks_is_cleaned(self):
        self.write_settings(USER_SETTINGS)
        self.install()
        m = mf.load(self.lay.manifest)
        bk = Path(m["backups"][0]["settings"])
        dirty, _ = settings_ops.add_hooks(USER_SETTINGS, settings_ops.hook_command(PY, "x/usage_guard.py"))
        bk.write_text(json.dumps(dirty), encoding="utf-8")
        code, log = commands.uninstall(self.lay, restore_backup=True)
        self.assertEqual(marked_count(self.settings()), 0)
        self.assertEqual(self.settings()["model"], "opus")

    def test_legacy_manifest_without_flag(self):
        now = _dt.datetime(2026, 11, 1, 10, 0, 0)
        rec = lambda sec, s: {"settings": s, "claudeMd": None, "at": (now + _dt.timedelta(seconds=sec)).isoformat()}  # noqa: E731
        m = {"installedAt": now.isoformat(), "backups": [rec(1, "a.json"), rec(500, "b.json")]}
        self.assertEqual(commands.pre_install_backup(m)["settings"], "a.json", "舊紀錄第一筆在安裝後 120 秒內：當成安裝前那筆")
        m["backups"] = [rec(500, "b.json"), rec(900, "c.json")]
        self.assertIsNone(commands.pre_install_backup(m), "第一筆已被修剪（時間差很多）：找不到就回 None，不可亂挑")
        m["backups"] = [rec(500, "b.json"), {**rec(1, None), "preInstall": True}]
        self.assertIsNone(commands.pre_install_backup(m)["settings"], "有旗標的優先")

    def test_web_config_backups_are_pruned(self):
        runner = fake_mcp_runner(self.lay, [])
        code, log = commands.apply(self.lay, PY, repo=REPO, mode="install", with_web=True, runner=runner)
        self.assertEqual(code, 0, NL.join(log))
        for _ in range(commands.KEEP_BACKUPS + 2):
            commands.web_config(self.lay, runner=runner)
        m = mf.load(self.lay.manifest)
        self.assertEqual(len(m["backups"]), commands.KEEP_BACKUPS)
        self.assertTrue(m["backups"][0].get("preInstall"))


class IN01_WebPrefsOnly(Base):
    """IN-01：web 未啟用時只存偏好；--usage-guard 立刻同步 settings.json。"""

    def setUp(self):
        super().setUp()
        self.calls: list = []
        self.runner = fake_mcp_runner(self.lay, self.calls)
        self.install()

    def test_key_when_web_disabled_only_saves_local(self):
        code, log = commands.web_config(self.lay, keys=["youtube=AIzaFAKE"], runner=self.runner)
        self.assertEqual(code, 0, NL.join(log))
        self.assertFalse(mf.load(self.lay.manifest)["web"]["enabled"])
        self.assertEqual(self.calls, [], "不可呼叫 claude mcp")
        self.assertNotIn("env", self.settings())
        self.assertEqual(web.load_local(self.lay)["keys"]["youtube"], "AIzaFAKE")
        self.assertTrue(any("聯網來源未啟用" in x for x in log))
        self.assertFalse(any("AIzaFAKE" in x for x in log))

    def test_usage_guard_off_then_verify_is_clean(self):
        code, log = commands.web_config(self.lay, usage_guard="off", runner=self.runner)
        self.assertEqual(code, 0, NL.join(log))
        self.assertEqual(self.calls, [])
        self.assertFalse(mf.load(self.lay.manifest)["web"]["enabled"])
        code, out = self.verify()
        self.assertEqual(code, 0, NL.join(out))
        self.assertEqual(marked_count(self.settings() if self.lay.settings.exists() else {}), 0)
        code, log = commands.web_config(self.lay, usage_guard="on", runner=self.runner)
        self.assertEqual(code, 0, NL.join(log))
        self.assertEqual(marked_count(self.settings()), len(settings_ops.HOOK_SPECS))
        self.assertEqual(self.verify()[0], 0)

    def test_no_args_or_enable_still_turns_web_on(self):
        code, log = commands.web_config(self.lay, keys=[], runner=self.runner)  # gui_model「依 local.json 重新對齊」的呼叫法
        self.assertEqual(code, 0, NL.join(log))
        self.assertTrue(mf.load(self.lay.manifest)["web"]["enabled"])
        self.assertTrue(self.calls)

    def test_enable_flag_turns_web_on(self):
        code, log = commands.web_config(self.lay, enable=["tavily"], runner=self.runner)
        self.assertEqual(code, 0, NL.join(log))
        self.assertIn("tavily", mf.load(self.lay.manifest)["web"]["mcpAdded"])

    def test_show_is_unchanged(self):
        code, log = commands.web_config(self.lay, keys=["exa=K"], show=True, runner=self.runner)
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertTrue(any("目前未啟用" in x for x in log))


class IN02_UninstallMcpFailure(Base):
    """IN-02：uninstall 時 MCP 移除失敗要回 1、最後一行 ❌，紀錄留下失敗的名稱，重跑可接著移除。"""

    def test_failed_remove_keeps_record_and_rerun_finishes(self):
        runner = fake_mcp_runner(self.lay, [])
        code, log = commands.apply(self.lay, PY, repo=REPO, mode="install", with_web=True, runner=runner)
        self.assertEqual(code, 0, NL.join(log))
        names = sorted(web.installed_servers(self.lay))
        code, log = commands.uninstall(self.lay, runner=lambda args: (1, "boom"))
        self.assertEqual(code, 1, NL.join(log))
        self.assertTrue(log[-1].startswith("❌"))
        self.assertTrue(self.lay.manifest.exists(), "MCP 移不掉時不可刪紀錄")
        self.assertEqual(mf.load(self.lay.manifest)["web"]["mcpAdded"], names)
        self.assertEqual(sorted(web.installed_servers(self.lay)), names)
        self.assertFalse((self.lay.payload / "rules" / "core.md").exists(), "其餘照常移除")
        code, log = commands.uninstall(self.lay, runner=runner)
        self.assertEqual(code, 0, NL.join(log))
        self.assertEqual(web.installed_servers(self.lay), {})
        self.assertFalse(self.lay.manifest.exists())
        self.assertFalse(self.lay.payload.exists())


class IN03_SyncMcpRemoveFailure(Base):
    """IN-03：sync_mcp 移除失敗時名稱留在 mcpAdded；重建時 remove 失敗就不接著 add。"""

    def setUp(self):
        super().setUp()
        self.calls: list = []
        self.runner = fake_mcp_runner(self.lay, self.calls)
        code, log = commands.apply(self.lay, PY, repo=REPO, mode="install", with_web=True, runner=self.runner)
        self.assertEqual(code, 0, NL.join(log))

    def rm_fail(self, args):
        if args[0] == "remove":
            self.calls.append(list(args))
            return 1, "locked"
        return self.runner(args)

    def test_disable_with_failed_remove_keeps_name(self):
        local = web.load_local(self.lay)
        local["disable"] = ["exa"]
        web.save_local(self.lay, local)
        log: list = []
        rec = web.sync_mcp(self.lay, mf.load(self.lay.manifest)["web"], self.rm_fail, log)
        self.assertIn("exa", rec["mcpAdded"])
        self.assertTrue(any(x.startswith("❌") and "exa" in x for x in log))
        local["disable"] = []
        web.save_local(self.lay, local)
        log = []
        web.sync_mcp(self.lay, rec, self.runner, log)
        self.assertFalse(any("使用者自行設定" in x for x in log), "重新啟用時不可被當成使用者自己的")

    def test_rebuild_with_failed_remove_does_not_add(self):
        rec = mf.load(self.lay.manifest)["web"]
        self.calls.clear()
        log: list = []
        rec2 = web.sync_mcp(self.lay, rec, self.rm_fail, log, defer=True)  # defer 變了 → 每個都要重建
        self.assertFalse(any(c[0] in ("add", "add-json") for c in self.calls), "remove 失敗就不可接著 add")
        self.assertEqual(sorted(rec2["mcpAdded"]), sorted(rec["mcpAdded"]))
        self.assertTrue(any(x.startswith("❌") and "重建失敗" in x for x in log))

    def test_web_off_with_failed_remove_keeps_names(self):
        code, log = commands.web_config(self.lay, off=True, runner=self.rm_fail)
        self.assertEqual(code, 1, NL.join(log))
        m = mf.load(self.lay.manifest)
        self.assertFalse(m["web"]["enabled"])
        self.assertTrue(m["web"]["mcpAdded"])
        code, log = commands.web_config(self.lay, off=True, runner=self.runner)
        self.assertEqual(code, 0, NL.join(log))
        self.assertEqual(web.installed_servers(self.lay), {})


BAD_SETTINGS = {"null": b"null", "list": b"[]", "bom": b"\xef\xbb\xbf{}", "badjson": b"{oops"}


def snapshot(home: Path) -> dict:
    return {p.relative_to(home).as_posix(): p.read_bytes() for p in home.rglob("*")
            if p.is_file() and p.name != commands.LOCK_NAME}  # Windows 上被鎖的位元組連讀都會 PermissionError


class IN04_Preflight(Base):
    """IN-04：settings.json／CLAUDE.md 讀不懂時，install／update／uninstall 在任何寫入前就丟帶檔名的 ValueError，什麼都不動。"""

    def check_blocked(self, fn, needle: str):
        before = snapshot(self.tmp)
        with self.assertRaises(ValueError) as cm:
            fn()
        self.assertIn(needle, str(cm.exception))
        self.assertEqual(snapshot(self.tmp), before, "預檢沒過不可寫任何檔（含備份）")
        return str(cm.exception)

    def test_bad_settings_install(self):
        for name, raw in BAD_SETTINGS.items():
            with self.subTest(name):
                shutil.rmtree(self.tmp, ignore_errors=True)
                self.tmp.mkdir()
                self.lay.settings.write_bytes(raw)
                msg = self.check_blocked(lambda: commands.apply(self.lay, PY, repo=REPO, mode="install"), "settings.json")
                if name == "bom":
                    self.assertIn("BOM", msg)

    def test_bad_settings_update_and_uninstall(self):
        self.install()
        for name, raw in BAD_SETTINGS.items():
            with self.subTest(name):
                self.lay.settings.write_bytes(raw)
                self.check_blocked(lambda: commands.apply(self.lay, PY, repo=REPO, mode="update"), "settings.json")
                self.check_blocked(lambda: commands.uninstall(self.lay), "settings.json")

    def test_cp950_claude_md(self):
        self.lay.claude_md.write_bytes("# 我的規則".encode("cp950"))
        self.check_blocked(lambda: commands.apply(self.lay, PY, repo=REPO, mode="install"), "CLAUDE.md")

    def test_missing_end_marker_update_and_uninstall(self):
        self.install()
        t = self.lay.claude_md.read_text(encoding="utf-8").replace("<!-- claude-dev-system:end -->", "")
        self.lay.claude_md.write_text(t, encoding="utf-8")
        self.check_blocked(lambda: commands.apply(self.lay, PY, repo=REPO, mode="update"), "結束標記")
        self.check_blocked(lambda: commands.uninstall(self.lay), "結束標記")

    def test_check_uses_same_rule(self):
        from cds import checks
        for name, raw in BAD_SETTINGS.items():
            self.lay.settings.write_bytes(raw)
            self.assertIsNotNone(checks.settings_error(self.lay.settings), name)
        self.lay.settings.write_text("{}", encoding="utf-8")
        self.assertIsNone(checks.settings_error(self.lay.settings))

    def test_cli_prints_one_line_and_exit_2(self):
        import install
        import contextlib
        import io
        self.lay.settings.write_bytes(b"null")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = install.main(["--claude-home", str(self.tmp), "install"])
        self.assertEqual(code, 2)
        self.assertTrue(out.getvalue().startswith("❌"), out.getvalue())
        self.assertNotIn("Traceback", out.getvalue())


class IN10_TwoBlocks(Base):
    """IN-10：CLAUDE.md 有兩個開始標記時 find_block 丟 ValueError，預檢在寫入前擋下。"""

    def test_two_blocks(self):
        blk = claudemd.make_block("body", "0.1.0")
        with self.assertRaises(ValueError) as cm:
            claudemd.find_block("mine" + NL + blk + NL + blk)
        self.assertIn("手動合併", str(cm.exception))
        self.install()
        self.lay.claude_md.write_text(self.lay.claude_md.read_text(encoding="utf-8") + NL + blk, encoding="utf-8")
        before = snapshot(self.tmp)
        with self.assertRaises(ValueError):
            commands.uninstall(self.lay)
        self.assertEqual(snapshot(self.tmp), before)


class IN07_KeyErrorsHideValues(unittest.TestCase):
    """IN-07：--key／--env／--key-mode 格式錯誤的訊息不可含值。"""

    def test_messages_never_contain_value(self):
        cases = [(web.set_key_arg, "tavily = SECRET-ABC"), (web.set_key_arg, "tavily.x=SECRET-ABC"),
                 (web.set_key_arg, "tavily=SEC" + NL + "RET"), (web.set_key_arg, "SECRETONLY"),
                 (web.set_env_arg, "lower=SECRET-ABC"), (web.set_key_mode_arg, "exa=SECRET-ABC")]
        for fn, kv in cases:
            with self.subTest(kv=kv):
                with self.assertRaises(ValueError) as cm:
                    fn({}, kv)
                msg = str(cm.exception)
                self.assertNotIn("SEC", msg)
        with self.assertRaises(ValueError) as cm:
            web.set_key_arg({}, "tavily.x=SECRET-ABC")
        self.assertIn("tavily.x", str(cm.exception), "名稱部分要顯示，使用者才知道哪裡錯")


class Q_LocalJsonRobust(Base):
    """Q：local.json 手改成 null 不可丟 TypeError；POSIX 上 local.json 權限 0600。"""

    def test_null_values_are_treated_as_empty(self):
        web.local_path(self.lay).parent.mkdir(parents=True, exist_ok=True)
        web.local_path(self.lay).write_text(json.dumps({"enable": None, "disable": None, "keys": None, "env": None}), encoding="utf-8")
        local = web.load_local(self.lay)
        self.assertEqual((local["enable"], local["disable"], local["keys"], local["env"]), ([], [], {}, {}))
        src = {"mcpServers": {"exa": {"url": "https://mcp.exa.ai/mcp", "default": True}}}
        self.assertEqual(set(web.desired_servers(src, local)), {"exa"})
        self.assertEqual(web.desired_env({"env": {"A": 1}}, local), {"A": "1"})

    @unittest.skipIf(os.name == "nt", "Windows 不用 POSIX 權限位元")
    def test_local_json_mode_0600(self):
        web.save_local(self.lay, {"keys": {"exa": "K"}})
        self.assertEqual(os.stat(web.local_path(self.lay)).st_mode & 0o777, 0o600)

    def test_save_local_still_writes_on_windows(self):
        web.save_local(self.lay, {"keys": {"exa": "K"}})
        self.assertEqual(web.load_local(self.lay)["keys"], {"exa": "K"})


HOLDER = (
    "import sys, time" + NL
    + "sys.path.insert(0, sys.argv[1])" + NL
    + "from pathlib import Path" + NL
    + "from cds import fsio" + NL
    + "fd = fsio.acquire_lock(Path(sys.argv[2]))" + NL
    + "print('locked', flush=True)" + NL
    + "time.sleep(60)" + NL
)


class IN06_LockAndAtomicWrite(Base):
    """IN-06：作業系統層級的安裝鎖（另一個程序拿著時回 2；程序被殺後鎖自動釋放）；暫存檔名唯一、replace 遇 PermissionError 重試。"""

    def hold_lock(self):
        lock = self.lay.payload / commands.LOCK_NAME
        p = subprocess.Popen([sys.executable, "-c", HOLDER, str(REPO / "installer"), str(lock)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close()))
        self.assertEqual(p.stdout.readline().strip(), "locked")
        return p

    def test_second_process_gets_exit_2_and_kill_releases(self):
        self.install()
        p = self.hold_lock()
        before = snapshot(self.tmp)
        for call in (lambda: commands.apply(self.lay, PY, repo=REPO, mode="update"),
                     lambda: commands.uninstall(self.lay),
                     lambda: commands.web_config(self.lay, keys=["exa=K"]),
                     lambda: commands.video_config(self.lay, PY, off=True)):
            code, log = call()
            self.assertEqual(code, 2, NL.join(log))
            self.assertEqual(len(log), 1)
            self.assertIn("另一個安裝程序正在執行", log[0])
        self.assertEqual(snapshot(self.tmp), before, "拿不到鎖時什麼都不可寫")
        p.kill()
        p.wait()
        self.install(mode="update")  # 程序被殺 → 系統釋放鎖，不需等逾時
        self.assertNotIn(commands.LOCK_NAME, json.dumps(mf.load(self.lay.manifest)["files"]), "鎖檔不可進 manifest 的 files")

    def test_uninstall_leaves_no_lock_file(self):
        self.install()
        self.assertTrue((self.lay.payload / commands.LOCK_NAME).exists())
        commands.uninstall(self.lay)
        self.assertFalse(self.lay.payload.exists())

    def test_not_installed_leaves_nothing(self):
        code, _ = commands.apply(self.lay, PY, repo=REPO, mode="update")
        self.assertEqual(code, 2)
        self.assertFalse(self.lay.payload.exists(), "沒安裝時拿鎖建的資料夾要清掉")

    def test_atomic_write_unique_tmp_and_retry(self):
        from unittest import mock
        target = self.tmp / "x.json"
        real = os.replace
        seen = []

        def flaky(src, dst):
            seen.append(Path(src).name)
            if len(seen) < 3:
                raise PermissionError(13, "in use")
            return real(src, dst)
        with mock.patch.object(fsio.os, "replace", flaky):
            fsio.atomic_write_bytes(target, b"ok")
        self.assertEqual(target.read_bytes(), b"ok")
        self.assertEqual(len(seen), 3, "PermissionError 要短暫重試")
        self.assertNotEqual(seen[0], "x.json.cds-tmp", "暫存檔名要唯一")
        with mock.patch.object(fsio.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(13, "in use"))):
            with self.assertRaises(PermissionError):
                fsio.atomic_write_bytes(target, b"new")
        self.assertEqual(list(self.tmp.glob("*.cds-tmp")), [], "失敗時暫存檔要刪掉")
        self.assertEqual(target.read_bytes(), b"ok")


class IN05_PathNormalization(unittest.TestCase):
    """IN-05：~/.claude 是 junction（或符號連結）時，預設路徑與 --claude-home 指同一處要算出同一個家目錄與同一個 .claude.json。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="cds-junc-"))
        self.real = self.base / "real"
        self.real.mkdir()
        self.prof = self.base / "prof"
        self.prof.mkdir()
        self.link = self.prof / ".claude"
        if os.name == "nt":
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(self.link), str(self.real)], capture_output=True)
            ok = r.returncode == 0
        else:
            try:
                os.symlink(self.real, self.link)
                ok = True
            except OSError:
                ok = False
        if not ok:
            self.skipTest("建不了 junction／符號連結")

    def tearDown(self):
        try:
            os.rmdir(self.link) if os.name == "nt" else os.unlink(self.link)
        except OSError:
            pass
        shutil.rmtree(self.base, ignore_errors=True)

    def test_default_and_explicit_agree(self):
        from unittest import mock
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(Path, "home", lambda *a: self.prof):
            default = paths.claude_home(None)
            explicit = paths.claude_home(str(self.link))
            self.assertEqual(default, explicit)
            want = self.prof / ".claude.json"
            for home in (default, explicit, self.link):
                self.assertEqual(web.user_config_path(Layout(home)), want, home)
            other = paths.claude_home(str(self.base / "elsewhere"))
            self.assertEqual(web.user_config_path(Layout(other)), other / ".claude.json")


class IN08_HookPythonMissing(Base):
    """IN-08：hook 用的 Python 不存在時 verify 要 ❌。"""

    def test_missing_python_fails_verify(self):
        code, log = commands.apply(self.lay, "C:/no/such/python.exe", repo=REPO, mode="install")
        self.assertEqual(code, 0, NL.join(log))
        code, out = self.verify()
        self.assertEqual(code, 1, NL.join(out))
        self.assertTrue(any(x.startswith("❌") and "hook 用的 Python 不存在" in x for x in out))
        self.install(mode="update")  # 現在的 Python 重跑 update 就好
        code, out = self.verify()
        self.assertEqual(code, 0, NL.join(out))
        self.assertTrue(any(x.startswith("✅") and "hook 用的 Python 存在" in x for x in out))

    def test_name_on_path_is_ok(self):
        from unittest import mock
        name = Path(sys.executable).name
        with mock.patch.object(commands.shutil, "which", lambda n: sys.executable if n == name else None):  # 審查 RV-07：原本 PATH 找不到時變成 ✅ == ✅
            self.assertEqual(commands._python_row(name)[0], "✅")
        self.assertEqual(commands._python_row("no-such-python-xyz")[0], "❌")


class IN09_MixedNewlines(Base):
    """IN-09：CLAUDE.md 混合換行時區塊外位元組不變；雜湊與 0.27.0 前的算法相同。"""

    def test_mixed_roundtrip(self):
        for raw in (b"line1\nline2\r\nline3\n", b"a\r\nb\r\nc\nd", b"x\r\ny\n"):
            with self.subTest(raw=raw):
                shutil.rmtree(self.tmp, ignore_errors=True)
                self.tmp.mkdir()
                self.lay.claude_md.write_bytes(raw)
                self.install()
                self.assertTrue(self.lay.claude_md.read_bytes().startswith(raw), "區塊外的位元組一字不動")
                self.assertEqual(self.verify()[0], 0)
                self.install(mode="update")
                commands.uninstall(self.lay)
                self.assertEqual(self.lay.claude_md.read_bytes(), raw)

    def test_hash_compatible_with_old_algorithm(self):
        blk = claudemd.make_block("body" + NL + "line2", "0.1.0")
        crlf = chr(13) + NL
        t = ("mine" + NL + NL + blk).replace(NL, crlf)
        old_way = claudemd.sha256_bytes(blk.encode("utf-8"))  # 舊版：整檔先轉 LF 再取區塊
        self.assertEqual(claudemd.block_hash(t), old_way)
        self.assertEqual(claudemd.block_hash(t.replace(crlf, NL)), old_way)


class IN11_StaleNewFiles(Base):
    """IN-11：衝突解除後清掉 .new 與 CLAUDE-block.new.md，extraFiles 同步減少。"""

    def test_new_files_cleared_after_conflict_resolved(self):
        self.lay.claude_md.write_text("mine" + NL, encoding="utf-8")
        self.install()
        p = self.lay.payload / "rules" / "core.md"
        orig = p.read_bytes()
        p.write_bytes(orig + b"x")
        md_orig = self.lay.claude_md.read_text(encoding="utf-8")
        self.lay.claude_md.write_text(md_orig.replace("先界定範圍再動手", "先界定範圍再動手（改）"), encoding="utf-8")
        self.install(mode="update")
        nfile = p.with_name("core.md.new")
        bfile = self.lay.payload / "CLAUDE-block.new.md"
        self.assertTrue(nfile.exists() and bfile.exists())
        self.assertEqual(len(mf.load(self.lay.manifest)["extraFiles"]), 2)
        p.write_bytes(orig)
        self.lay.claude_md.write_text(md_orig, encoding="utf-8")
        log = self.install(mode="update")
        self.assertFalse(nfile.exists(), "使用者改回後 .new 要清掉")
        self.assertFalse(bfile.exists(), "區塊改回後 CLAUDE-block.new.md 要清掉")
        self.assertEqual(mf.load(self.lay.manifest)["extraFiles"], [])
        self.assertTrue(any("移除已不需要的" in x for x in log))


class IN12_ManifestDefaults(Base):
    """IN-12：manifest 缺鍵、version 為 null 時不可 KeyError／TypeError。"""

    def test_missing_keys_and_null_version(self):
        self.install()
        m = json.loads(self.lay.manifest.read_text(encoding="utf-8"))
        m["version"] = None
        del m["files"]
        del m["settings"]["createdKeys"]
        m["web"] = None
        self.lay.manifest.write_text(json.dumps(m), encoding="utf-8")
        loaded = mf.load(self.lay.manifest)
        self.assertEqual(loaded["files"], {})
        self.assertEqual(loaded["settings"]["createdKeys"], [])
        self.assertFalse(loaded["web"]["enabled"])
        code, out = commands.status(self.lay, repo=REPO)
        self.assertEqual(code, 0)
        code, out = self.verify()  # 不丟例外即可（files 空、版本不符會 ❌）
        self.install(mode="update")
        self.assertEqual(self.verify()[0], 0)

    def test_unparsable_versions(self):
        self.assertEqual(commands._ver(None), (0, 0, 0))
        self.assertEqual(commands._ver("garbage"), (0, 0, 0))
        self.assertEqual(commands._ver("0.27.0"), (0, 27, 0))


class IN13_VerifyReadOnly(Base):
    """IN-13：verify 不寫任何檔（原本會寫 _verify.pyc 再刪）。"""

    def test_verify_writes_nothing(self):
        from unittest import mock
        self.install()
        before = snapshot(self.tmp)
        import py_compile
        with mock.patch.object(py_compile, "compile", side_effect=AssertionError("verify 不可呼叫 py_compile 寫 .pyc")):
            code, out = self.verify()
        self.assertEqual(code, 0, NL.join(out))
        self.assertTrue(any("usage_guard.py 可編譯" in x for x in out))
        self.assertEqual(snapshot(self.tmp), before)
        (self.lay.payload / "hooks" / "usage_guard.py").write_text("def (:" + NL, encoding="utf-8")
        code, out = self.verify()
        self.assertTrue(any(x.startswith("❌") and "無法編譯" in x for x in out))


class IN14_ProgramText(unittest.TestCase):
    """IN-14：程式內說明不寫死題數（目前 11 題）、結束碼說明涵蓋寫入子命令的 1、--restore-backup 說明符合實際行為。"""

    def test_docstrings(self):
        import install
        from cds import selftest
        for doc in (install.__doc__, selftest.__doc__):
            self.assertNotIn("九題", doc)
        self.assertIn("uninstall 做完但有項目失敗", install.__doc__)
        self.assertIn("另一個安裝程序正在執行", install.__doc__)
        self.assertIn("安裝前沒有 settings.json", install.__doc__)


class IN15_UnreachableBranchDocumented(unittest.TestCase):
    """IN-15：verify 裡平常走不到的 WARN 分支保留行為、補註解說明何時才會走到。"""

    def test_comment_present_and_branch_still_works(self):
        src = (REPO / "installer" / "cds" / "commands.py").read_text(encoding="utf-8")
        self.assertIn("IN-15", src)
        tmp = Path(tempfile.mkdtemp(prefix="cds-test-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        lay = Layout(tmp)
        code, log = commands.apply(lay, PY, repo=REPO, mode="install")
        self.assertEqual(code, 0, NL.join(log))
        m = json.loads(lay.manifest.read_text(encoding="utf-8"))
        rel = "claude-dev-system/rules/core.md"
        m["userEditable"].append(rel)  # 模擬舊版 manifest 的 userEditable 比現在多
        lay.manifest.write_text(json.dumps(m), encoding="utf-8")
        (tmp / rel).write_text("改過", encoding="utf-8")
        code, out = commands.verify(lay, repo=REPO, check_claude=False)
        self.assertTrue(any(x.startswith("⚠️") and "已被使用者修改" in x for x in out), NL.join(out))


if __name__ == "__main__":
    unittest.main()
