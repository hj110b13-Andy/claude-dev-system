"""2026-11-12 全方位健檢第二階段（fix-gui）的回歸測試：設定視窗、視窗模型、自我更新的 GU-01～GU-12。
每個類別對應稽核報告的一條（類別名帶條目編號）。不開視窗、不連網、不碰真實的 ~/.claude。
視窗層（gui.py 的 tkinter 部分）抽不出純函式的改動，用 ast 檢查原始碼的方式守住（見 GU09、GU12）。"""
from __future__ import annotations

import ast
import itertools
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))
sys.path.insert(0, str(REPO / "tests"))

from cds import appdir, gui_model as gm, web  # noqa: E402
from cds.paths import Layout  # noqa: E402
from test_gui_model import Base  # noqa: E402

BS = chr(92)  # 反斜線：避免在 f-string／heredoc 裡跳脫出問題


def winpath(*parts: str) -> str:
    return BS.join(parts)


class FakeRun:
    """假的 subprocess.run：記下呼叫的參數，回固定的 stdout。"""

    def __init__(self, stdout: bytes, returncode: int = 0):
        self.stdout, self.stderr, self.returncode, self.calls = stdout, b"", returncode, []

    def __call__(self, args, **kw):
        self.calls.append((args, kw))
        return self


# ---------------------------------------------------------------- GU-01
class GU01_FindSystemPython(unittest.TestCase):
    def find(self, out: bytes, exists=lambda p: True, which=None):
        run = FakeRun(out)
        res = gm.find_system_python(which=which or (lambda n: "C:/Windows/py.exe" if n == "py" else None), run=run, exists=exists)
        return res, run

    @unittest.skipUnless(os.name == "nt", "找系統 Python 是 Windows exe 模式才用的功能，路徑寫法也是 Windows 的（CI 在 ubuntu／macos 上失敗才加）")
    def test_path_with_spaces_is_not_truncated(self):
        out = (winpath("C:", "Program Files", "Python314", "python.exe") + chr(10) + "3.14.0" + chr(10)).encode()
        (exe, ver), _ = self.find(out)
        self.assertEqual(exe, "C:/Program Files/Python314/python.exe", "原本被 .split() 截成 C:/Program")
        self.assertEqual(ver, (3, 14, 0))

    def test_user_name_with_space_and_chinese_and_crlf(self):
        p = winpath("C:", "Users", "John Smith 王小明", "AppData", "Local", "Programs", "Python", "Python314", "python.exe")
        (exe, ver), run = self.find((p + chr(13) + chr(10) + "3.14.0" + chr(13) + chr(10)).encode("utf-8"))
        self.assertEqual(exe, Path(p).as_posix())
        self.assertEqual(ver, (3, 14, 0))
        env = run.calls[0][1]["env"]
        self.assertEqual((env["PYTHONIOENCODING"], env["PYTHONUTF8"]), ("utf-8", "1"), "子程序強制 UTF-8，中文路徑不經碼頁 950")

    def test_path_must_exist_and_store_stub_is_skipped(self):
        out = (winpath("C:", "Program Files", "Python314", "python.exe") + chr(10) + "3.14.0" + chr(10)).encode()
        self.assertEqual(self.find(out, exists=lambda p: False)[0], (None, None), "路徑不存在不採用")
        stub = (winpath("C:", "Users", "a", "AppData", "Local", "Microsoft", "WindowsApps", "python.exe") + chr(10) + "3.14.0" + chr(10)).encode()
        self.assertEqual(self.find(stub)[0], (None, None), "商店的假 python.exe 排除（大小寫不拘）")
        low = stub.replace(b"WindowsApps", b"windowsapps")
        self.assertEqual(self.find(low)[0], (None, None))

    def test_bad_output_returns_none(self):
        self.assertEqual(self.find(b"")[0], (None, None))
        self.assertEqual(self.find(b"only-one-line" + chr(10).encode())[0], (None, None))


# ---------------------------------------------------------------- GU-02
class GU02_BrokenLocalJson(Base):
    BROKEN = '{"keys": {"cwa": "CWA-REAL-KEY", "gemini": "G-REAL"},}'  # 手改多一個逗號

    def install(self):
        s = self.state()
        self.assertEqual(self.apply(gm.form_from_state(s), s), 0)
        self.logs.clear()

    def break_local(self) -> Path:
        lp = web.local_path(self.lay)
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_bytes(self.BROKEN.encode("utf-8"))
        return lp

    def check_refused(self, mutate):
        self.install()
        lp = self.break_local()
        before = lp.read_bytes()
        s = self.state()
        f = gm.form_from_state(s)
        mutate(f, s)
        code = self.apply(f, s)
        self.assertNotEqual(code, 0, "壞檔時要回非 0")
        self.assertEqual(lp.read_bytes(), before, "壞檔的位元組不可被改（金鑰不可無聲消失）")
        cross = [x for x in self.logs if x.startswith("❌")]
        self.assertTrue(cross, self.logs)
        self.assertIn("local.json", cross[0], "要指出檔名")
        self.assertIn("請修好或刪除", cross[0])
        self.assertNotIn("CWA-REAL-KEY", " ".join(self.logs), "金鑰值不可出現在紀錄")

    def test_usage_guard_toggle_refused(self):
        self.check_refused(lambda f, s: setattr(f, "usage_guard", not s["hooks"]["usage_guard_pref"]))

    def test_source_guard_toggle_refused(self):
        self.check_refused(lambda f, s: setattr(f, "source_guard", not s["hooks"]["source_guard_pref"]))

    def test_key_note_refused(self):
        self.check_refused(lambda f, s: f.key_notes.__setitem__("cwa", "我的帳號"))

    def test_new_key_refused(self):
        self.check_refused(lambda f, s: f.keys.__setitem__("tavily", "tvly-NEW"))

    def test_download_dir_refused(self):
        self.check_refused(lambda f, s: setattr(f, "download_dir", "D:/dl"))

    def test_non_local_changes_still_apply_when_local_is_broken(self):
        """只改門檻（本身不寫 local.json）：門檻照常寫入；壞檔位元組仍不變（已安裝時 commands.web_config 自己也會回 2 並說明，那是既有行為）。"""
        self.install()
        lp = self.break_local()
        before = lp.read_bytes()
        s = self.state()
        f = gm.form_from_state(s)
        f.thresholds = {"fiveHour": 70, "sevenDay": 90}
        self.apply(f, s)
        self.assertEqual(lp.read_bytes(), before)
        self.assertEqual(self.state()["thresholds"], {"fiveHour": 70.0, "sevenDay": 90.0})

    def test_display_read_still_returns_defaults(self):
        """給畫面讀取與 mask 用的 _local 照舊回預設值（不丟例外）。"""
        self.install()
        self.break_local()
        self.assertEqual(gm._local(self.lay)["keys"], {})
        with self.assertRaises(ValueError):
            gm._local_strict(self.lay)
        self.assertFalse(self.state()["keys"]["cwa"]["present"])


# ---------------------------------------------------------------- GU-05
class GU05_NumericValidation(Base):
    def cfg_bytes(self) -> bytes:
        return (self.lay.payload / "config" / "dispatch-config.json").read_bytes()

    def test_valid_threshold_table(self):
        for ok in (1, 1.0, 85, "85", " 97.5 ", 100):
            self.assertTrue(1 <= gm.valid_threshold(ok) <= 100, ok)
        for bad in (0, -5, 100.01, 101, float("nan"), float("inf"), "abc", "", None, True, "nan", [1]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                gm.valid_threshold(bad)

    def test_other_numeric_fields(self):
        self.assertEqual(gm.valid_task_minutes("7"), 7)
        for bad in (0, -1, 1.5, "x", None, float("nan"), True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                gm.valid_task_minutes(bad)
        self.assertEqual(gm.valid_pa_int("minSourceFiles", "10"), 10)
        self.assertEqual(gm.valid_pa_int("staleFiles", 0), 0, "其餘數字 0＝不檢查")
        for k, bad in (("minSourceFiles", 0), ("staleFiles", -1), ("claudeMdMaxLines", "x"), ("progressMaxKB", 2.5), ("claudeMdMaxKB", None)):
            with self.assertRaises(ValueError, msg=f"{k}={bad!r}"):
                gm.valid_pa_int(k, bad)

    def test_apply_rejects_bad_thresholds_and_leaves_file_untouched(self):
        s = self.state()
        self.assertEqual(self.apply(gm.form_from_state(s), s), 0)
        for bad in (0.0, -5.0, float("nan"), "abc", 150):
            s = self.state()
            f = gm.form_from_state(s)
            f.thresholds = {"fiveHour": bad, "sevenDay": 97}
            before = self.cfg_bytes()
            self.logs.clear()
            code = self.apply(f, s)
            self.assertEqual(code, 2, repr(bad))
            self.assertTrue(any(x.startswith("❌") and "5 小時用量門檻" in x for x in self.logs), (bad, self.logs))
            self.assertEqual(self.cfg_bytes(), before, "不合法值不可寫入")
        json.loads(self.cfg_bytes().decode("utf-8"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))  # 嚴格 JSON：沒有 NaN

    def test_apply_rejects_bad_numbers_in_other_fields(self):
        s = self.state()
        self.assertEqual(self.apply(gm.form_from_state(s), s), 0)
        for mut in (lambda f: f.task_check.update(minutes=0), lambda f: f.task_check.update(minutes="x"), lambda f: setattr(f, "mem_gb", 99),
                    lambda f: setattr(f, "mem_gb", float("nan")), lambda f: f.project_auto.update(minSourceFiles=0), lambda f: f.project_auto.update(staleFiles="x")):
            s = self.state()
            f = gm.form_from_state(s)
            mut(f)
            before = self.cfg_bytes()
            self.logs.clear()
            self.assertEqual(self.apply(f, s), 2)
            self.assertEqual(self.cfg_bytes(), before)

    def test_write_functions_validate_themselves(self):
        (self.lay.payload / "config").mkdir(parents=True)
        for call in (lambda: gm.write_thresholds(self.lay, float("nan"), 97), lambda: gm.write_thresholds(self.lay, 0, 97), lambda: gm.write_thresholds(self.lay, 85, 101),
                     lambda: gm.write_task_check(self.lay, True, 0), lambda: gm.write_project_auto(self.lay, {"minSourceFiles": 0})):
            with self.assertRaises(ValueError):
                call()
        self.assertFalse((self.lay.payload / "config" / "dispatch-config.json").exists(), "驗證失敗不留半個檔")

    def test_untouched_legacy_value_does_not_block_unrelated_apply(self):
        """使用者手改進設定檔的舊值（門檻 0.5）沒被這次動到：不相關的變更照常套用；要把門檻改成 0.5 才拒絕。"""
        s = self.state()
        self.assertEqual(self.apply(gm.form_from_state(s), s), 0)
        p = self.lay.payload / "config" / "dispatch-config.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["usageThresholdPct"]["fiveHour"] = 0.5
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        s = self.state()
        self.assertEqual(s["thresholds"]["fiveHour"], 0.5)
        f = gm.form_from_state(s)
        f.task_check = {"enabled": True, "minutes": 9}
        self.assertEqual(self.apply(f, s), 0, self.logs)
        self.assertEqual(self.state()["task_check"]["minutes"], 9)
        self.assertEqual(self.state()["thresholds"]["fiveHour"], 0.5, "沒動的值照舊")
        s = self.state()
        f = gm.form_from_state(s)
        f.thresholds["fiveHour"] = 0.7
        self.assertEqual(self.apply(f, s), 2, "要寫的新值才檢查")

    def test_valid_values_still_apply(self):
        s = self.state()
        self.assertEqual(self.apply(gm.form_from_state(s), s), 0)
        s = self.state()
        f = gm.form_from_state(s)
        f.thresholds = {"fiveHour": 90.0, "sevenDay": 99.0}
        f.task_check = {"enabled": True, "minutes": 7}
        f.mem_gb = 4.0
        self.assertEqual(self.apply(f, s), 0, self.logs)
        s = self.state()
        self.assertEqual((s["thresholds"], s["task_check"]["minutes"], s["mem_gb"]), ({"fiveHour": 90.0, "sevenDay": 99.0}, 7, 4.0))

    def test_gui_collect_uses_shared_validators_and_never_reverts_silently(self):
        """視窗層讀碼守門：_collect 的數值欄位只走 gm.valid_*，沒有「except ValueError 就退回舊值」的無聲分支；按鈕動作先過 _safe_collect。"""
        src = (REPO / "installer" / "gui.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
        meth = {n.name: n for n in app.body if isinstance(n, ast.FunctionDef)}
        seg = ast.get_source_segment(src, meth["_collect"])
        for need in ("gm.valid_threshold(", "gm.valid_task_minutes(", "gm.valid_mem_gb(", "gm.valid_pa_int("):
            self.assertIn(need, seg)
        for n in ast.walk(meth["_collect"]):
            if isinstance(n, ast.ExceptHandler):
                self.fail(f"_collect 第 {n.lineno} 行還有 except：不可無聲退回舊值")
        for name in ("do_apply", "do_export", "do_import", "set_preset"):
            self.assertIn("_safe_collect(", ast.get_source_segment(src, meth[name]), name)

    def test_import_uses_the_same_threshold_rule(self):
        base = gm.form_from_state(self.state())
        for bad in (0, -5, "abc", float("nan"), 101, True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                gm.import_profile(base, {"claude-dev-system-profile": 1, "thresholds": {"fiveHour": bad}})
        g = gm.import_profile(base, {"claude-dev-system-profile": 1, "thresholds": {"fiveHour": 60, "sevenDay": 80}})
        self.assertEqual(g.thresholds, {"fiveHour": 60.0, "sevenDay": 80.0})


# ---------------------------------------------------------------- GU-06
class GU06_CloseAfterApply(unittest.TestCase):
    def test_decision_table(self):
        T = gm.should_close_after_apply
        self.assertTrue(T(True, 0), "成功才關")
        self.assertFalse(T(True, 1), "套用失敗（有 ❌）不關窗")
        self.assertFalse(T(True, 2), "用法錯誤／表單有誤不關窗")
        self.assertFalse(T(True, None), "套用根本沒跑（提早 return 或例外）不關窗")
        self.assertFalse(T(False, 0), "沒要求就不關")
        self.assertFalse(T(False, None))

    def test_gui_resets_flag_on_every_path(self):
        """視窗層讀碼守門：do_apply 不再有會殘留的旗標；done 訊息處理一律先清旗標再決定要不要關（見 gui.py）。"""
        src = (REPO / "installer" / "gui.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
        meth = {n.name: n for n in app.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("close_after", [a.arg for a in meth["do_apply"].args.args], "do_apply 改成參數傳遞，不用跨呼叫的旗標")
        self.assertIn("should_close_after_apply", ast.get_source_segment(src, meth["_pump"]), "關窗判斷走 gm.should_close_after_apply")
        # on_close 不可再直接設 self._close_after_apply = True（旗標只在套用工作真的啟動後才設）
        for node in ast.walk(meth["on_close"]):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "_close_after_apply" for t in node.targets):
                self.fail("on_close 不可直接設旗標")


# ---------------------------------------------------------------- GU-07
class GU07_KeepUserKeys(Base):
    def cfg(self) -> dict:
        return json.loads((self.lay.payload / "config" / "dispatch-config.json").read_text(encoding="utf-8"))

    def test_task_check_and_thresholds_keep_other_keys(self):
        s = self.state()
        self.assertEqual(self.apply(gm.form_from_state(s), s), 0)
        p = self.lay.payload / "config" / "dispatch-config.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["taskCheck"]["myNote"] = "使用者手改"
        d["usageThresholdPct"]["myNote"] = "使用者手改"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        s = self.state()
        f = gm.form_from_state(s)
        f.task_check = {"enabled": True, "minutes": 7}
        f.thresholds = {"fiveHour": 80.0, "sevenDay": 97.0}
        self.assertEqual(self.apply(f, s), 0, self.logs)
        d = self.cfg()
        self.assertEqual(d["taskCheck"]["myNote"], "使用者手改", "段內自加的鍵要保留")
        self.assertEqual((d["taskCheck"]["enabled"], d["taskCheck"]["minutes"]), (True, 7))
        self.assertEqual(d["usageThresholdPct"]["myNote"], "使用者手改")
        self.assertEqual((d["usageThresholdPct"]["fiveHour"], d["usageThresholdPct"]["sevenDay"]), (80.0, 97.0))
        self.assertIn("modelTable", d, "檔內其他段也保留")

    def test_threshold_legacy_plan_entries_still_flattened(self):
        (self.lay.payload / "config").mkdir(parents=True)
        p = self.lay.payload / "config" / "dispatch-config.json"
        p.write_text(json.dumps({"plan": {"current": "max5x"}, "usageThresholdPct": {"$說明": "x", "max5x": {"fiveHour": 95, "sevenDay": 99}, "keep": 1}}), encoding="utf-8")
        gm.write_thresholds(self.lay, 90, 98)
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertNotIn("plan", d)
        self.assertNotIn("max5x", d["usageThresholdPct"], "舊 plan 的子物件扁平化時拿掉")
        self.assertEqual(d["usageThresholdPct"]["keep"], 1)

    def test_description_is_added_when_missing_and_kept_when_present(self):
        (self.lay.payload / "config").mkdir(parents=True)
        p = self.lay.payload / "config" / "dispatch-config.json"
        p.write_text(json.dumps({"taskCheck": {"$說明": "自訂說明", "x": 1}}), encoding="utf-8")
        gm.write_task_check(self.lay, False, 9)
        t = json.loads(p.read_text(encoding="utf-8"))["taskCheck"]
        self.assertEqual((t["$說明"], t["x"], t["enabled"], t["minutes"]), ("自訂說明", 1, False, 9))
        p.write_text("{}", encoding="utf-8")
        gm.write_task_check(self.lay, True, 3)
        self.assertIn("$說明", json.loads(p.read_text(encoding="utf-8"))["taskCheck"])


# ---------------------------------------------------------------- GU-08
class GU08_ImportTypeChecks(Base):
    def imp(self, **extra):
        return gm.import_profile(gm.form_from_state(self.state()), {"claude-dev-system-profile": 1, **extra})

    def test_bad_types_reject_whole_profile_and_name_the_field(self):
        cases = [
            ({"project_auto": {"minSourceFiles": "abc"}}, "minSourceFiles"),
            ({"project_auto": {"minSourceFiles": 0}}, "minSourceFiles"),
            ({"project_auto": {"autoInit": "yes"}}, "autoInit"),
            ({"project_auto": "x"}, "project_auto"),
            ({"chrome_default_enabled": "yes"}, "chrome_default_enabled"),
            ({"task_check": {"enabled": "no"}}, "task_check.enabled"),
            ({"task_check": {"minutes": "abc"}}, "task_check.minutes"),
            ({"task_check": {"minutes": 0}}, "task_check.minutes"),
            ({"sub_brief": {"guard": "no"}}, "sub_brief.guard"),
            ({"servers": {"exa": "no"}}, "servers.exa"),
            ({"env": {"X": ["a"]}}, "env.X"),
            ({"thresholds": [1, 2]}, "thresholds"),
            ({"key_modes": 3}, "key_modes"),
        ]
        for extra, field in cases:
            with self.assertRaises(ValueError, msg=str(extra)) as cm:
                self.imp(**extra)
            self.assertIn(field, str(cm.exception), extra)

    def test_whole_profile_is_rejected_atomically(self):
        base = gm.form_from_state(self.state())
        before = (dict(base.project_auto), dict(base.task_check), base.usage_guard)
        with self.assertRaises(ValueError):
            gm.import_profile(base, {"claude-dev-system-profile": 1, "usage_guard": not base.usage_guard, "project_auto": {"minSourceFiles": "abc"}})
        self.assertEqual((base.project_auto, base.task_check, base.usage_guard), before, "傳入的表單不被改動")

    def test_good_profile_roundtrips(self):
        g = self.imp(project_auto={"minSourceFiles": 12, "autoRefactor": True}, task_check={"enabled": False, "minutes": 30}, chrome_default_enabled=None,
                     sub_brief={"guard": False}, servers={"exa": False}, env={"CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION": 300})
        self.assertEqual((g.project_auto["minSourceFiles"], g.project_auto["autoRefactor"]), (12, True))
        self.assertEqual(g.task_check, {"enabled": False, "minutes": 30})
        self.assertIsInstance(g.task_check["minutes"], int)
        self.assertFalse(g.sub_brief["guard"])
        self.assertFalse(g.servers["exa"])
        self.assertTrue(self.imp(chrome_default_enabled=True).chrome_default_enabled)

    def test_apply_after_import_never_raises_on_int(self):
        """repro (g)：匯入後視窗做的 int(minSourceFiles) 不會再丟例外。"""
        g = self.imp(project_auto={"minSourceFiles": "15"})
        self.assertEqual(int(g.project_auto["minSourceFiles"]), 15)
        self.assertIsInstance(g.project_auto["minSourceFiles"], int)


# ---------------------------------------------------------------- GU-12（gui_model 部分）
class GU12_SmallFixes(unittest.TestCase):
    def test_pwsh_condition_simplification_is_equivalent(self):
        """gui_model._pwsh_status 的條件拿掉 `(bool(reg) and not store)`：逐一比對所有布林組合，結果相同。"""
        for win, msi, reg, store in itertools.product((True, False), repeat=4):
            old = (not win) or msi or (reg and not store) or (not store)
            new = (not win) or msi or (not store)
            self.assertEqual(bool(old), bool(new), (win, msi, reg, store))

    def test_relaunch_command_carries_claude_home(self):
        cmd = gm.relaunch_command(winpath("C:", "app", "x.exe"), Path("D:/my claude home"))
        self.assertEqual(cmd[0], winpath("C:", "app", "x.exe"))
        self.assertIn("--after-update", cmd)
        i = cmd.index("--claude-home")
        self.assertEqual(cmd[i + 1], str(Path("D:/my claude home")))

    def test_gui_relaunch_uses_the_helper_and_single_time_import(self):
        src = (REPO / "installer" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("gm.relaunch_command(", src, "重開要帶 --claude-home（用 gm.relaunch_command）")
        self.assertNotIn('[sys.executable, "--after-update"]', src)
        tree = ast.parse(src)
        names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        self.assertEqual(names.count("time"), 1, "gui.py 的 import time 不重複")


# ---------------------------------------------------------------- M
class M_DecodeOutput(unittest.TestCase):
    def test_utf8_cp950_and_garbage_never_raise(self):
        zh = "結束代碼為: 1603"
        self.assertEqual(gm.decode_output(zh.encode("utf-8")), zh)
        self.assertEqual(gm.decode_output(zh.encode("cp950"), fallback="cp950"), zh, "碼頁 950 的在地化訊息不會變亂碼")
        self.assertIsInstance(gm.decode_output(bytes(range(256))), str)
        self.assertIsInstance(gm.decode_output(b"\xff\xfe\xfa", fallback="no-such-codec"), str)
        self.assertEqual(gm.decode_output(None), "")

    def test_install_action_hint_found_for_cp950_output(self):
        out = ("安裝失敗，結束代碼為: 1603").encode("cp950")
        orig = gm.decode_output
        gm.decode_output = lambda b, fallback=None: orig(b, fallback="cp950")
        try:
            code, text = gm.install_action("ffmpeg", "py", run=FakeRun(out, 1603))
        finally:
            gm.decode_output = orig
        self.assertEqual(code, 1603)
        self.assertIn("結束代碼為: 1603", text)
        self.assertIsNotNone(gm.install_hint(code, text))

    def test_all_subprocess_decodes_in_gui_layer_use_replace(self):
        """讀碼：gui.py／gui_model.py／appdir.py 內對子程序輸出的 .decode( 都帶 replace 或走 decode_output（不丟 UnicodeDecodeError）。"""
        for rel in ("installer/gui.py", "installer/cds/gui_model.py"):
            tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "decode":
                    self.assertEqual(len(n.args), 2, f"{rel}:{n.lineno} decode 要帶 errors 參數")


# ---------------------------------------------------------------- GU-09
class GU09_NoTkAccessInWorkerThreads(unittest.TestCase):
    def test_worker_functions_do_not_touch_tk_variables_or_widgets(self):
        """gui.py 讀碼守門：App 方法裡的巢狀函式（job／work，在工作執行緒跑）不可對 tk 變數 .get()／.set()、不可 .config()／.configure()／文字框 insert／delete。
        tk 變數與元件只能在主執行緒碰；要用的值先在主執行緒讀出來再傳進去，結果一律走 queue（self.q.put／self._log）。"""
        import re
        src = (REPO / "installer" / "gui.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        bad = []
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for m in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
                for inner in (n for n in ast.walk(m) if isinstance(n, ast.FunctionDef) and n is not m and n.name in ("job", "work")):
                    for c in ast.walk(inner):
                        if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)):
                            continue
                        recv = ast.get_source_segment(src, c.func.value) or ""
                        if c.func.attr in ("config", "configure", "insert", "delete") or (c.func.attr in ("get", "set") and re.search(r"var|entry|combo", recv, re.I)):
                            bad.append(f"{m.name}.{inner.name} 第 {c.lineno} 行：{recv}.{c.func.attr}()")
        self.assertEqual(bad, [], "工作執行緒不可直接碰 tk（原本 do_test_key 的 job 讀 note_vars[n].get()）")

    def test_scan_would_catch_the_original_pattern(self):
        """守門本身要有效：把原本的寫法丟進同一個掃描規則，必須被抓到。"""
        import re
        code = "class A:" + chr(10) + "    def m(self):" + chr(10) + "        def job():" + chr(10) + "            return self.note_vars[n].get()" + chr(10)
        tree = ast.parse(code)
        hits = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "get"
                and re.search(r"var", ast.get_source_segment(code, c.func.value), re.I)]
        self.assertEqual(len(hits), 1)


# ---------------------------------------------------------------- GU-03
class GU03_VersionCompare(unittest.TestCase):
    def exe_http(self, tag, size=1):
        body = json.dumps({"tag_name": tag, "assets": [{"name": appdir.EXE_NAME, "browser_download_url": "https://x/e", "size": size}]}).encode()
        return lambda u, t=20: body

    def test_invalid_versions_do_not_raise_and_report_error(self):
        tmp = Path(tempfile.mkdtemp(prefix="cds-ver-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        lay = Layout(tmp / "h")
        for remote in (b"latest", b"vtest", b"<html>x</html>", b"", b"v"):
            r = appdir.check_update(lay, REPO, http=lambda u, t=20, rr=remote: rr)
            self.assertFalse(r["newer"], remote)
            self.assertTrue(r["error"], remote)
        for tag in ("latest", "vtest", "", "abc"):
            r = appdir.check_exe_update("0.26.1", http=self.exe_http(tag))
            self.assertFalse(r["newer"], tag)
            self.assertTrue(r["error"], tag)
        r = appdir.check_exe_update("abc", http=self.exe_http("v0.27.0"))  # 內建版本壞掉
        self.assertEqual((r["newer"], bool(r["error"])), (False, True))
        for raw in (b"[]", b"null", b"3"):  # Release 回的 JSON 不是物件
            r = appdir.check_exe_update("0.26.1", http=lambda u, t=20, rr=raw: rr)
            self.assertFalse(r["newer"])
            self.assertTrue(r["error"])

    def test_missing_bundled_version_uses_parseable_default(self):
        self.assertIsNotNone(appdir.parse_ver(appdir.NO_VERSION), "讀不到版本時的預設值要解析得出來（原本的 '0' 是 None）")
        r = appdir.check_exe_update(None, http=self.exe_http("v0.27.0"))
        self.assertEqual((r["newer"], r["error"]), (True, None))
        r = appdir.check_exe_update("", http=self.exe_http("v0.0.0"))
        self.assertEqual((r["newer"], r["error"]), (False, None))

    def test_numeric_comparison_still_correct(self):
        self.assertEqual(appdir.is_newer("0.10.0", "0.9.0"), (True, None), "不是字串比較")
        self.assertEqual(appdir.is_newer("0.9.0", "0.10.0"), (False, None))
        self.assertEqual(appdir.is_newer("1.2.0", "1.2.0"), (False, None))
        self.assertEqual(appdir.is_newer("v1.2.1", "1.2.0"), (True, None))
        self.assertEqual(appdir.is_newer("1.2", "1.1.9"), (True, None))
        self.assertEqual(appdir.is_newer(None, "1.0.0")[0], False)
        self.assertTrue(appdir.is_newer("x", "1.0.0")[1])
        self.assertTrue(appdir.is_newer("1.0.0", None)[1])
        tmp = Path(tempfile.mkdtemp(prefix="cds-ver-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        bundled = tmp / "b"
        (bundled / "config").mkdir(parents=True)
        (bundled / "config" / "VERSION").write_text("0.9.0" + chr(10), encoding="utf-8")
        r = appdir.check_update(Layout(tmp / "h"), bundled, http=lambda u, t=20: b"0.10.0")
        self.assertEqual((r["newer"], r["error"]), (True, None))
        self.assertTrue(appdir.check_exe_update("0.9.0", http=self.exe_http("v0.10.0"))["newer"])

    def test_effective_repo_ignores_unparseable_app_version(self):
        tmp = Path(tempfile.mkdtemp(prefix="cds-ver-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        lay = Layout(tmp / "h")
        bundled = tmp / "b"
        (bundled / "config").mkdir(parents=True)
        (bundled / "config" / "VERSION").write_text("1.0.0", encoding="utf-8")
        a = appdir.app_dir(lay)
        for rel, txt in (("config/VERSION", "garbage"), ("rules/core.md", "x"), ("installer/install.py", "x")):
            (a / rel).parent.mkdir(parents=True, exist_ok=True)
            (a / rel).write_text(txt, encoding="utf-8")
        self.assertEqual(appdir.effective_repo(lay, bundled), bundled, "app/ 的版本字串壞掉就用內建，不丟 TypeError")


# ---------------------------------------------------------------- GU-10
class GU10_UpdatePlan(unittest.TestCase):
    def test_plan_table(self):
        P = appdir.update_plan
        self.assertEqual(P({"newer": True}, None), "rules")
        self.assertEqual(P({"newer": True}, {"newer": True}), "rules", "規則有新版時，更新流程自己會接著處理 exe")
        self.assertEqual(P({"newer": False}, {"newer": True}), "exe_only", "規則最新但 exe 舊：不可顯示『已是最新』")
        self.assertEqual(P({"newer": False}, {"newer": False}), "none")
        self.assertEqual(P({"newer": False}, None), "none", "原始碼模式或查不到 exe")

    def test_gui_both_entry_points_share_the_plan(self):
        src = (REPO / "installer" / "gui.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
        meth = {n.name: ast.get_source_segment(src, n) for n in app.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("appdir.update_plan(", meth["_check_updates"])
        self.assertIn("self._check_updates(", meth["_auto_check_update"])
        self.assertIn("self._check_updates(", meth["do_check_update"])
        self.assertNotIn("check_update(self.lay", meth["_auto_check_update"], "自動檢查不自己另寫一份流程")
        self.assertNotIn("check_update(self.lay", meth["do_check_update"])


# ---------------------------------------------------------------- GU-11
class GU11_CleanupOldExe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-old-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.exe = self.tmp / "app.exe"
        self.exe.write_bytes(b"MZ")
        self.olds = [self.tmp / "app.old.exe", self.tmp / ("app.old" + str(int(time.time())) + ".exe")]
        for o in self.olds:
            o.write_bytes(b"MZ-old")
        (self.tmp / "other.old.exe").write_bytes(b"x")

    def test_finds_only_own_old_files_and_deletes_them(self):
        self.assertEqual(appdir.old_exe_files(self.exe), sorted(self.olds))
        sleeps = []
        self.assertEqual(appdir.cleanup_old_exe(self.exe, tries=3, wait=0, sleep=sleeps.append), 2)
        self.assertEqual(appdir.old_exe_files(self.exe), [])
        self.assertTrue(self.exe.exists() and (self.tmp / "other.old.exe").exists(), "別人的檔案與正在跑的 exe 不動")
        self.assertEqual(sleeps, [], "一輪就刪完不用等")

    def test_locked_file_is_retried_then_deleted(self):
        real = Path.unlink
        state = {"n": 0}

        def flaky(self_, *a, **k):
            if self_.name == "app.old.exe" and state["n"] < 2:
                state["n"] += 1
                raise PermissionError("locked")
            return real(self_, *a, **k)
        sleeps = []
        from unittest import mock
        with mock.patch.object(Path, "unlink", flaky):
            n = appdir.cleanup_old_exe(self.exe, tries=5, wait=0.5, sleep=sleeps.append)
        self.assertEqual(n, 2)
        self.assertEqual(sleeps, [0.5, 0.5], "被鎖兩輪、各等一次")

    def test_always_locked_gives_up_after_tries(self):
        from unittest import mock
        sleeps = []
        with mock.patch.object(Path, "unlink", side_effect=PermissionError("locked")):
            self.assertEqual(appdir.cleanup_old_exe(self.exe, tries=4, wait=1, sleep=sleeps.append), 0)
        self.assertEqual(len(sleeps), 3)

    def test_gui_uses_the_shared_helpers(self):
        src = (REPO / "installer" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("appdir.old_exe_files(", src)
        self.assertIn("appdir.delete_old_exes(", src)
        self.assertNotIn(".glob(exe.stem", src, "視窗不再自己另寫一份 glob")


# ---------------------------------------------------------------- L
class L_ExeSwapAndSha(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-swap-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_parse_sha256(self):
        good = "a" * 64
        self.assertEqual(appdir.parse_sha256((good + "  x.exe").encode()), good)
        self.assertEqual(appdir.parse_sha256(("A" * 64).encode()), good, "大寫也行")
        self.assertEqual(appdir.parse_sha256(b"\xef\xbb\xbf" + good.encode()), good, "有 BOM 也行")
        for bad in (b"", b"   ", b"deadbeef  x", b"z" * 64, ("a" * 63).encode(), ("a" * 65).encode(), b"<html>404</html>"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                appdir.parse_sha256(bad)

    def test_download_exe_rejects_empty_or_malformed_sha_file(self):
        exe_bytes = b"MZ" + bytes(1_200_000)
        exe = self.tmp / "cds.exe"
        exe.write_bytes(b"MZ-old")
        info = {"tag": "9.9.9", "url": "https://x/exe", "size": len(exe_bytes), "sha_url": "https://x/sha"}
        for sha_body in (b"", b"  ", b"not-a-hash  cds.exe"):
            http = lambda u, t=20, b=sha_body: exe_bytes if u == "https://x/exe" else b  # noqa: E731
            with self.assertRaises(ValueError, msg=repr(sha_body)):
                appdir.download_exe(info, exe, lambda s: None, http=http)
            self.assertFalse((self.tmp / "cds.new.exe").exists(), "驗證沒過不留下載檔")

    def test_swap_restore_failure_reports_where_the_old_exe_is(self):
        exe, new = self.tmp / "cds.exe", self.tmp / "cds.new.exe"
        exe.write_bytes(b"MZ-old")
        new.write_bytes(b"MZ-new")
        real = Path.rename
        calls = []

        def rename(self_, target):
            calls.append((self_.name, Path(target).name))
            if len(calls) == 1:
                return real(self_, target)  # exe → .old.exe 成功
            raise PermissionError("locked")  # 新的改名失敗，連還原也失敗
        from unittest import mock
        with mock.patch.object(Path, "rename", rename):
            with self.assertRaises(OSError) as cm:
                appdir.swap_exe(exe, new)
        msg = str(cm.exception)
        self.assertIn("cds.old.exe", msg, "要說出原本的 exe 現在叫什麼")
        self.assertIn("改回 cds.exe", msg)
        self.assertEqual((self.tmp / "cds.old.exe").read_bytes(), b"MZ-old", "原本的程式內容沒丟")
        self.assertFalse(exe.exists())

    def test_swap_failure_with_successful_restore_keeps_exe(self):
        exe = self.tmp / "b.exe"
        exe.write_bytes(b"MZ-b")
        with self.assertRaises(FileNotFoundError):
            appdir.swap_exe(exe, self.tmp / "nope.new.exe")
        self.assertEqual(exe.read_bytes(), b"MZ-b")
        self.assertFalse((self.tmp / "b.old.exe").exists())

    def test_old_unlink_failure_picks_another_name(self):
        exe, new = self.tmp / "c.exe", self.tmp / "c.new.exe"
        exe.write_bytes(b"MZ-1")
        new.write_bytes(b"MZ-2")
        (self.tmp / "c.old.exe").write_bytes(b"locked-old")
        from unittest import mock
        with mock.patch.object(Path, "unlink", side_effect=PermissionError("locked")):
            old = appdir.swap_exe(exe, new)
        self.assertNotEqual(old.name, "c.old.exe")
        self.assertEqual(exe.read_bytes(), b"MZ-2")


if __name__ == "__main__":
    unittest.main()
