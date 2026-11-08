"""gui_model（設定視窗邏輯層）測試：假 CLAUDE_HOME 上讀狀態、算差異、套用、門檻、金鑰測試、匯出匯入。不開視窗。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))

from cds import gui_model as gm, manifest as mf, web  # noqa: E402
from cds.paths import Layout  # noqa: E402
from test_installer import fake_importer, fake_mcp_runner, fake_pip  # noqa: E402

PY = Path(sys.executable).as_posix()
FULL = {"yt_dlp": "2026.10.26", "youtube_transcript_api": "", "faster_whisper": "1.2.1"}


def fake_env(repo, importer=None, ffmpeg=None):
    return {"python": gm.EnvItem(True, "py"), "claude": gm.EnvItem(True, "claude"), "ffmpeg": gm.EnvItem(True, "ff"),
            "pwsh": gm.EnvItem(True, "pwsh 7"), "winget": gm.EnvItem(True, "w"), "git": gm.EnvItem(True, "g"), "node": gm.EnvItem(True, "n"),
            "faster_whisper": gm.EnvItem(True, "fw")}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-gui-"))
        self.lay = Layout(self.tmp)
        self.calls: list = []
        self.pips: list = []
        self.runner = fake_mcp_runner(self.lay, self.calls)
        self.pip = fake_pip(self.pips)
        self.logs: list = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self):
        return gm.read_state(self.lay, repo=REPO, env=fake_env, importer=fake_importer(FULL), ffmpeg=lambda: "ff")

    def apply(self, form, state=None):
        state = state or self.state()
        code = gm.apply_form(self.lay, PY, state, form, self.logs.append, repo=REPO, runner=self.runner, pip=self.pip)
        return code

    def servers(self):
        p = web.user_config_path(self.lay)
        return json.loads(p.read_text(encoding="utf-8")).get("mcpServers", {}) if p.exists() else {}


class ReadAndDiff(Base):
    def test_fresh_home_state_and_install_via_form(self):
        s = self.state()
        self.assertFalse(s["installed"])
        self.assertFalse(s["web"]["enabled"])
        f = gm.form_from_state(s)
        self.assertEqual(gm.diff(s, f)[0].kind, "install", "未安裝時第一個差異是安裝核心")
        f.web_enabled = True
        f.video_enabled = True
        f.keys["cwa"] = "CWA-TEST"
        f.thresholds = {"fiveHour": 95, "sevenDay": 99}
        f.download_dir = "D:/影片"
        kinds = {c.kind for c in gm.diff(s, f)}
        self.assertEqual(kinds, {"install", "web", "video", "keys", "thresholds", "download_dir"})
        self.assertEqual(self.apply(f, s), 0, "\n".join(self.logs))
        s2 = self.state()
        self.assertTrue(s2["installed"] and s2["web"]["enabled"] and s2["video"]["enabled"])
        self.assertTrue(s2["keys"]["cwa"]["present"])
        self.assertEqual(s2["thresholds"], {"fiveHour": 95.0, "sevenDay": 99.0})
        self.assertEqual(s2["video"]["download_dir"], "D:/影片")
        self.assertEqual(set(self.servers()), {"parallel", "exa", "context7", "deepwiki", "mslearn", "firecrawl"})
        self.assertEqual(gm.diff(s2, gm.form_from_state(s2)), [], "套用後重讀狀態，表單應無差異")
        self.assertFalse(any("CWA-TEST" in x for x in self.logs), "紀錄不可含金鑰值")

    def test_toggle_server_key_mode_env_and_all_off(self):
        s = self.state()
        f = gm.form_from_state(s)
        f.web_enabled = True
        self.apply(f, s)
        s = self.state()
        f = gm.form_from_state(s)
        f.servers["exa"] = False
        f.keys["tavily"] = "tvly-x"
        f.servers["tavily"] = True
        f.env["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"] = "800"
        texts = [c.text for c in gm.diff(s, f)]
        self.assertTrue(any("關閉 MCP exa" in t for t in texts) and any("800" in t for t in texts))
        self.assertEqual(self.apply(f, s), 0, "\n".join(self.logs))
        srv = self.servers()
        self.assertNotIn("exa", srv)
        self.assertIn("tavily", srv)
        self.assertIn("tavily-key", srv, "免費優先：金鑰版並存")
        st = json.loads(self.lay.settings.read_text(encoding="utf-8"))
        self.assertEqual(st["env"]["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"], "800")
        s = self.state()
        f = gm.form_from_state(s)
        f.key_modes["tavily"] = "always"
        self.assertTrue(any("一律用金鑰" in c.text for c in gm.diff(s, f)))
        self.apply(f, s)
        self.assertNotIn("tavily-key", self.servers())
        s = self.state()
        f = gm.form_from_state(s)
        f.env["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"] = "600"  # 改回預設 → 覆寫移除
        self.apply(f, s)
        self.assertEqual(json.loads(self.lay.settings.read_text(encoding="utf-8"))["env"]["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"], "600")
        self.assertNotIn("CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION", web.load_local(self.lay).get("env") or {})
        s = self.state()
        off = gm.preset(gm.form_from_state(s), s, False)
        self.apply(off, s)
        s = self.state()
        self.assertFalse(s["web"]["enabled"])
        self.assertEqual(self.servers(), {})
        self.assertTrue(s["keys"]["tavily"]["present"], "關閉不刪金鑰")

    def test_usage_guard_toggle_removes_and_restores_hooks(self):
        s = self.state()
        f = gm.form_from_state(s)
        self.apply(f, s)  # 安裝核心
        st = json.loads(self.lay.settings.read_text(encoding="utf-8"))
        self.assertTrue(st.get("hooks"), "預設有 hook")
        s = self.state()
        f = gm.form_from_state(s)
        f.usage_guard = False
        self.assertTrue(any("關閉用量守門" in c.text for c in gm.diff(s, f)))
        self.assertEqual(self.apply(f, s), 0, "\n".join(self.logs))
        st = json.loads(self.lay.settings.read_text(encoding="utf-8"))
        self.assertFalse(any("claude-dev-system" in json.dumps(v) for v in (st.get("hooks") or {}).values()), "hook 應被移除")
        from cds import commands
        code, out = commands.verify(self.lay, repo=REPO, check_claude=False, importer=fake_importer(FULL), ffmpeg=lambda: "ff")
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any("已由使用者關閉" in x for x in out))
        s = self.state()
        self.assertFalse(s["hooks"]["usage_guard_pref"] or s["hooks"]["usage_guard"])
        f = gm.form_from_state(s)
        f.usage_guard = True
        self.apply(f, s)
        self.assertTrue(self.state()["hooks"]["usage_guard"])

    def test_source_guard_toggle_writes_local(self):
        s = self.state()
        f = gm.form_from_state(s)
        self.apply(f, s)
        s = self.state()
        self.assertTrue(s["hooks"]["source_guard_pref"], "預設開")
        f = gm.form_from_state(s)
        f.source_guard = False
        self.assertTrue(any("關閉查證守門" in c.text for c in gm.diff(s, f)))
        self.assertEqual(self.apply(f, s), 0, "\n".join(self.logs))
        self.assertFalse(self.state()["hooks"]["source_guard_pref"])
        self.assertIn("sourceGuard", json.dumps(gm.export_profile(self.state(), gm.form_from_state(self.state()))).replace("source_guard", "sourceGuard"))
        st = json.loads(self.lay.settings.read_text(encoding="utf-8"))
        self.assertIn("Stop", st["hooks"], "Stop hook 要註冊（開關只在 local.json）")

    def test_system_importer_batches_into_one_process(self):
        calls = []

        class R:
            returncode = 0
            stdout = b"some noise\n" + json.dumps({"faster_whisper": "1.2.1", "yt_dlp": "2026.10.01", "youtube_transcript_api": None}).encode()

        def run(cmd, **kw):
            calls.append(cmd)
            return R()
        imp = gm.system_importer("C:/py/python.exe", run=run)
        self.assertEqual(imp("yt_dlp"), "2026.10.01")
        self.assertEqual(imp("faster_whisper"), "1.2.1")
        self.assertIsNone(imp("youtube_transcript_api"))
        self.assertEqual(len(calls), 1, "三個套件只開一個程序")
        self.assertEqual(set(calls[0][3:]), set(gm.BATCH_MODS))
        imp("other_mod")
        self.assertEqual(len(calls), 2, "清單外的套件另外查")
        self.assertIsNone(gm.system_importer(None)("yt_dlp"))

    def test_pwsh_status_any_drive_and_store(self):
        class R:
            stdout = "7.6.9"
        run = lambda *a, **k: R()  # noqa: E731
        it = gm._pwsh_status(which=lambda n: r"D:\Apps\PowerShell\7\pwsh.exe", run=run, msi_location=lambda: r"D:\Apps\PowerShell\7")
        self.assertTrue(it.ok, "裝在 D 槽的 MSI 版要算 ✅，不可引導重裝")
        self.assertIsNone(it.action)
        it = gm._pwsh_status(which=lambda n: r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\pwsh.exe", run=run, msi_location=lambda: None)
        if __import__("sys").platform == "win32" and not (__import__("pathlib").Path(__import__("os").environ.get("ProgramFiles", "")) / "PowerShell" / "7" / "pwsh.exe").exists():
            self.assertIsNone(it.ok, "Store 版才提示")
            self.assertEqual(it.action, "pwsh7")
        self.assertIn("MSI 1603", gm.install_hint(2316632070, "安裝程式失敗，結束代碼為: 1603"))
        self.assertIsNone(gm.install_hint(5, "x"))

    def test_cancel_means_no_change(self):
        s = self.state()
        f = gm.form_from_state(s)
        f.web_enabled = True
        f.keys["cwa"] = "X"
        # 不呼叫 apply → 什麼都不該存在
        self.assertFalse(self.lay.manifest.exists())
        self.assertFalse(web.local_path(self.lay).exists())

    def test_thresholds_roundtrip_and_legacy_plan(self):
        (self.lay.payload / "config").mkdir(parents=True)
        p = self.lay.payload / "config" / "dispatch-config.json"
        p.write_text(json.dumps({"plan": {"current": "max5x"}, "usageThresholdPct": {"max5x": {"fiveHour": 95, "sevenDay": 99}, "pro": {"fiveHour": 80, "sevenDay": 97}},
                                 "modelTable": {"A": {}}}), encoding="utf-8")
        self.assertEqual(gm.read_thresholds(self.lay), {"fiveHour": 95, "sevenDay": 99})
        gm.write_thresholds(self.lay, 90, 98)
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual((d["usageThresholdPct"]["fiveHour"], d["usageThresholdPct"]["sevenDay"]), (90, 98))
        self.assertNotIn("plan", d)
        self.assertIn("modelTable", d, "其他鍵保留")

    def test_mem_gate_roundtrip_and_range(self):
        """0.16.0 E：重型工作記憶體門檻視窗可改（使用者 2026-11-09「記憶體門檻要用成視窗可更改的」），1～32 GB。"""
        s = self.state()
        f = gm.form_from_state(s)
        self.apply(f, s)
        s = self.state()
        self.assertEqual(s["mem_gb"], 3.0, "預設 3 GB")
        f = gm.form_from_state(s)
        f.mem_gb = 4.5
        self.assertTrue(any("3 GB → 4.5 GB" in c.text for c in gm.diff(s, f)))
        self.apply(f, s)
        self.assertEqual(self.state()["mem_gb"], 4.5)
        d = json.loads((self.lay.payload / "config" / "dispatch-config.json").read_text(encoding="utf-8"))
        self.assertEqual(d["resourceGate"]["minFreeMemGB"], 4.5)
        self.assertEqual(d["resourceGate"]["waitMinutes"], 10, "其他鍵補預設／保留")
        self.assertIn("modelTable", d, "其他鍵保留")
        for bad in (0, 0.5, 33, "x", True, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                gm.valid_mem_gb(bad)
        with self.assertRaises(ValueError):
            gm.write_mem_gate(self.lay, 100)
        base = gm.form_from_state(self.state())
        with self.assertRaises(ValueError):
            gm.import_profile(base, {"claude-dev-system-profile": 1, "mem_gb": 64})
        self.assertEqual(gm.import_profile(base, {"claude-dev-system-profile": 1, "mem_gb": 8}).mem_gb, 8.0)
        self.assertEqual(gm.export_profile(self.state(), base)["mem_gb"], 4.5)

    def test_task_check_roundtrip(self):
        s = self.state()
        f = gm.form_from_state(s)
        self.apply(f, s)
        s = self.state()
        self.assertEqual(s["task_check"], {"enabled": True, "minutes": 15})
        f = gm.form_from_state(s)
        f.task_check = {"enabled": True, "minutes": 5}
        self.assertTrue(any("每 5 分鐘" in c.text for c in gm.diff(s, f)))
        self.apply(f, s)
        self.assertEqual(self.state()["task_check"]["minutes"], 5)
        s = self.state()
        f = gm.form_from_state(s)
        f.task_check["enabled"] = False
        self.assertTrue(any("巡檢 → 關閉" in c.text for c in gm.diff(s, f)))
        self.apply(f, s)
        self.assertFalse(self.state()["task_check"]["enabled"])
        d = json.loads((self.lay.payload / "config" / "dispatch-config.json").read_text(encoding="utf-8"))
        self.assertIn("modelTable", d, "其他鍵保留")

    def test_export_import_profile_has_no_keys(self):
        s = self.state()
        f = gm.form_from_state(s)
        f.keys["cwa"] = "SECRET"
        f.servers["exa"] = False
        data = gm.export_profile(s, f)
        self.assertNotIn("SECRET", json.dumps(data))
        g = gm.import_profile(gm.form_from_state(s), data)
        self.assertFalse(g.servers["exa"])
        self.assertTrue(all(v is None for v in g.keys.values()), "不含金鑰的檔不動金鑰")
        data2 = gm.export_profile(s, f, include_keys=True, current_keys={"moenv": "M1"})
        self.assertEqual(data2["keys"], {"cwa": "SECRET", "moenv": "M1"})
        self.assertIn("_warning", data2)
        g2 = gm.import_profile(gm.form_from_state(s), data2)
        self.assertEqual((g2.keys["cwa"], g2.keys["moenv"]), ("SECRET", "M1"))
        with self.assertRaises(ValueError):
            gm.import_profile(f, {"foo": 1})

    def test_key_account_notes_roundtrip_and_export(self):
        s = self.state()
        f = gm.form_from_state(s)
        f.keys["gemini"] = "G-SECRET"
        f.key_notes["gemini"] = "hj9@gmail.com"
        f.key_notes["cwa"] = "   "  # 空白＝沒變（原本也空）
        texts = [c.text for c in gm.diff(s, f)]
        self.assertTrue(any("Gemini 帳號備註 → hj9@gmail.com" in t for t in texts))
        self.assertFalse(any("中央氣象署 帳號備註" in t for t in texts))
        self.assertEqual(self.apply(f, s), 0, chr(10).join(self.logs))
        s = self.state()
        self.assertEqual(s["keys"]["gemini"]["account"], "hj9@gmail.com")
        self.assertEqual(web.load_local(self.lay)["keyNotes"], {"gemini": "hj9@gmail.com"})
        self.assertEqual(gm.diff(s, gm.form_from_state(s)), [])
        data = gm.export_profile(s, gm.form_from_state(s))
        self.assertEqual(data["key_notes"], {"gemini": "hj9@gmail.com"})
        self.assertNotIn("G-SECRET", json.dumps(data))
        g = gm.import_profile(gm.form_from_state(s), {"claude-dev-system-profile": 1, "key_notes": {"cwa": "work@x"}})
        self.assertEqual(g.key_notes["cwa"], "work@x")
        f = gm.form_from_state(s)
        f.key_notes["gemini"] = ""
        self.assertTrue(any("（清除）" in c.text for c in gm.diff(s, f)))
        self.apply(f, s)
        self.assertEqual(web.load_local(self.lay)["keyNotes"], {})

    def test_usage_read_and_refresh(self):
        self.assertIsNone(gm.read_usage(self.lay)["five"])
        self.assertIn("尚無用量資料", gm.read_usage(self.lay)["text"])
        (self.lay.home / "state").mkdir(parents=True)
        (self.lay.home / "state" / "usage.json").write_text(json.dumps({"five_hour_pct": 12.0, "seven_day_pct": 34.0,
            "five_hour_resets_at": "2026-11-01T03:00:00+00:00", "seven_day_resets_at": "2026-11-07T12:59:59+00:00", "updated_at": "2026-11-01T02:03:51+0800"}), encoding="utf-8")
        u = gm.read_usage(self.lay)
        self.assertEqual((u["five"], u["seven"]), (12.0, 34.0))
        self.assertIn("5 小時 12%", u["text"])
        self.assertIn("7 天 34%", u["text"])
        self.assertIn("2026-11-01 02:03", u["text"])
        self.assertIn("usage", self.state())
        self.assertIn("尚未安裝核心", gm.refresh_usage(self.lay, PY)["text"])
        self.apply(gm.form_from_state(self.state()))
        calls = []

        class R:
            stdout, stderr = "5 小時 12%".encode("utf-8"), b""
        u = gm.refresh_usage(self.lay, PY, run=lambda cmd, **k: (calls.append((cmd, k)), R)[1])
        self.assertTrue(calls[0][0][1].endswith("usage_guard.py") and calls[0][0][2] == "--print")
        self.assertEqual(calls[0][1]["env"]["CLAUDE_CONFIG_DIR"], str(self.lay.home))
        self.assertIn("5 小時 12%", u["text"])

    def test_env_blank_means_default_and_import_validation(self):
        s = self.state()
        f = gm.form_from_state(s)
        f.web_enabled = True
        self.apply(f, s)
        s = self.state()
        f = gm.form_from_state(s)
        f.env["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"] = ""
        self.assertEqual([c for c in gm.diff(s, f) if c.kind == "env"], [], "清空＝預設，不是假變更")
        f.env["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"] = "900"
        self.apply(f, s)
        s = self.state()
        f = gm.form_from_state(s)
        f.env["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"] = "   "
        self.assertTrue(any("900 → 600" in c.text for c in gm.diff(s, f)))
        self.apply(f, s)
        self.assertEqual(json.loads(self.lay.settings.read_text(encoding="utf-8"))["env"]["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"], "600")
        base = gm.form_from_state(self.state())
        for bad in ({"thresholds": {"fiveHour": "x"}}, {"thresholds": {"fiveHour": 500}}, {"task_check": {"minutes": 0}}, {"web_enabled": "yes"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                gm.import_profile(base, {"claude-dev-system-profile": 1, **bad})
        g = gm.import_profile(base, {"claude-dev-system-profile": 1, "servers": {"exa": False, "別台機器才有": True}, "key_modes": {"exa": "bogus", "tavily": "always"}})
        self.assertNotIn("別台機器才有", g.servers)
        self.assertFalse(g.servers["exa"])
        self.assertEqual(g.key_modes.get("tavily"), "always")
        self.assertNotEqual(g.key_modes.get("exa"), "bogus")

    def test_restore_backup_keeps_a_copy_of_current(self):
        self.apply(gm.form_from_state(self.state()))  # 第一次安裝：原本沒有 settings.json，沒東西可備份
        s = self.state()
        f = gm.form_from_state(s)
        f.thresholds = {"fiveHour": 90, "sevenDay": 98}
        self.apply(f, s)  # 第二次才有 settings.json 可備份
        items = gm.list_backups(self.lay)
        self.assertTrue(items)
        before = self.lay.settings.read_text(encoding="utf-8")
        gm.restore_backup(self.lay, items[0][1])
        saved = list(self.lay.backups.glob("*-before-restore.json"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_text(encoding="utf-8"), before)

    def test_mask_hides_url_encoded_key(self):
        local = {"keys": {"k": "ab/c+d"}}
        self.assertEqual(web.mask("x=ab%2Fc%2Bd y=ab/c+d", local), "x=*** y=***")

    def test_older_source_does_not_propose_update_and_still_applies_settings(self):
        s = self.state()
        f = gm.form_from_state(s)
        f.web_enabled = True
        self.apply(f, s)
        m = json.loads(self.lay.manifest.read_text(encoding="utf-8"))
        m["version"] = "99.0.0"  # 模擬：已安裝比來源新（用舊 exe 開已從原始碼更新過的機器）
        self.lay.manifest.write_text(json.dumps(m), encoding="utf-8")
        s = self.state()
        self.assertTrue(gm.source_older(s))
        f = gm.form_from_state(s)
        self.assertEqual([c.kind for c in gm.diff(s, f)], [], "來源較舊不可提「更新」")
        f.keys["cwa"] = "NEWKEY"
        f.thresholds = {"fiveHour": 90, "sevenDay": 98}
        self.logs.clear()
        code = self.apply(f, s)
        self.assertEqual(code, 0, chr(10).join(self.logs))
        self.assertTrue(any("比已安裝的 v99.0.0 舊" in x for x in self.logs))
        self.assertFalse(any("降版" in x for x in self.logs), "不可再出現安裝器的降版拒絕")
        s = self.state()
        self.assertTrue(s["keys"]["cwa"]["present"])
        self.assertEqual(s["thresholds"]["fiveHour"], 90.0)
        self.assertEqual(s["version"], "99.0.0", "已安裝版本不可被降")

    def test_failed_apply_log_has_cross_mark(self):
        from cds import gui_model as g
        logs = []
        state = self.state()
        f = gm.form_from_state(state)
        f.web_enabled = True
        g.apply_form(self.lay, PY, state, f, logs.append, repo=REPO, runner=lambda args: (1, "boom"), pip=self.pip)
        self.assertTrue(any(x.startswith("❌") for x in logs), logs)

    def test_project_auto_roundtrip(self):
        s = self.state()
        self.apply(gm.form_from_state(s), s)
        s = self.state()
        self.assertEqual(s["project_auto"], {"autoInit": True, "autoAudit": True, "autoRefactor": False, "minSourceFiles": 10})
        f = gm.form_from_state(s)
        f.project_auto = {"autoInit": True, "autoAudit": False, "autoRefactor": True, "minSourceFiles": 25}
        texts = [c.text for c in gm.diff(s, f)]
        self.assertTrue(any("舊專案自動盤點=關" in t and "專案門檻（原始碼檔數）=25" in t for t in texts), texts)
        self.assertEqual(self.apply(f, s), 0, chr(10).join(self.logs))
        s = self.state()
        self.assertEqual(s["project_auto"]["autoRefactor"], True)
        self.assertEqual(s["project_auto"]["minSourceFiles"], 25)
        d = json.loads((self.lay.payload / "config" / "dispatch-config.json").read_text(encoding="utf-8"))
        self.assertIn("taskCheck", d, "其他鍵保留")
        data = gm.export_profile(s, gm.form_from_state(s))
        self.assertEqual(data["project_auto"]["minSourceFiles"], 25)

    def test_chrome_default_toggle_writes_claude_json_with_backup(self):
        p = web.user_config_path(self.lay)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"mcpServers": {}, "other": 1}), encoding="utf-8")
        self.assertIs(gm.chrome_default_enabled(self.lay), False, "檔案在、還沒有這個鍵＝還沒開，要能勾（新裝置實測被鎖住）")
        gm.set_chrome_default_enabled(self.lay, True)
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertTrue(d["claudeInChromeDefaultEnabled"] and d["other"] == 1)
        self.assertTrue(list(self.lay.backups.glob("claude-json-*.json")))
        for i in range(12):
            (self.lay.backups / f"claude-json-2020010{i % 10}-00000{i}.json").write_text("{}", encoding="utf-8")
        gm.set_chrome_default_enabled(self.lay, False)
        self.assertLessEqual(len(list(self.lay.backups.glob("claude-json-*.json"))), 10, "~/.claude.json 備份只留 10 份")


class NewDeviceFlow(unittest.TestCase):
    """0.14.2 全新裝置實測三個問題：node 沒按鈕、Chrome 要先 /chrome 才能勾、faster-whisper 第一次失敗。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-newdev-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lay = Layout(self.tmp / "home")
        self.lay.home.mkdir(parents=True)

    def test_chrome_default_states(self):
        p = web.user_config_path(self.lay)
        p.unlink(missing_ok=True)
        self.assertIs(gm.chrome_default_enabled(self.lay), False, "檔案還沒建立也能勾")
        gm.set_chrome_default_enabled(self.lay, True)
        self.assertIs(gm.chrome_default_enabled(self.lay), True)
        p.write_text("{壞掉", encoding="utf-8")
        self.assertIsNone(gm.chrome_default_enabled(self.lay), "壞檔不可寫")

    def test_native_host_key_is_claude_code_not_desktop(self):
        self.assertTrue(gm.NATIVE_HOST_KEY.endswith(chr(92) + "com.anthropic.claude_code_browser_extension"))

    def test_install_without_python_gives_plain_message(self):
        code, msg = gm.install_action("faster_whisper", None)
        self.assertEqual(code, 1)
        self.assertIn("找不到系統的 Python", msg)
        self.assertNotIn("NoneType", msg)

    def test_refresh_path_adds_new_dirs_only(self):
        env = {"PATH": os.pathsep.join(["C:/a", "C:/b"])}
        self.assertEqual(gm.refresh_path(env, lambda: ["C:/b", "", "C:/new", "C:/new"]), ["C:/new"])
        self.assertEqual(env["PATH"], os.pathsep.join(["C:/a", "C:/b", "C:/new"]), "原有順序不動")
        self.assertEqual(gm.refresh_path(env, lambda: ["C:/new"]), [], "第二次沒有新的")

    def test_js_runtime_prefers_deno_and_checks_minimum(self):
        class R:
            def __init__(self, out):
                self.stdout, self.returncode = out, 0

        def run_for(table):
            return lambda cmd, **kw: R(table[cmd[0]])
        both = {"deno": b"deno 2.9.8 (stable)", "node": b"v26.13.0"}
        which_all = lambda n: n
        self.assertEqual(gm.video.js_runtime(which_all, run_for(both)), ("deno", (2, 9, 8)))
        self.assertEqual(gm.video.js_runtime(lambda n: n if n == "node" else None, run_for(both)), ("node", (26, 13, 0)))
        self.assertIsNone(gm.video.js_runtime(lambda n: n if n == "node" else None, run_for({"node": b"v20.1.0"})), "node 低於 22 不算")
        self.assertIsNone(gm.video.js_runtime(lambda n: None, run_for({})))

    def test_env_rows_offer_one_click_install(self):
        """0.15.0：Deno、Node 各一列各有按鈕；Python、git、Claude Code 也是按鈕（使用者 11/4 要全部一鍵安裝）。"""
        class R:
            stdout, returncode = b"", 1
        env = gm.env_status(which=lambda n: None, importer=lambda m: None, ffmpeg=lambda: None, claude_status=lambda r: (False, "x"), run=lambda *a, **k: R())
        for key in ("deno", "node", "git", "claude", "ffmpeg", "faster_whisper"):
            self.assertEqual(env[key].action, key, key)
            self.assertEqual(gm.install_button(key, True)[0], "install", key)
        for key in ("deno", "node", "python", "git", "claude"):
            self.assertIn(key, gm.INSTALL_ACTIONS)
        self.assertIn("OpenJS.NodeJS.LTS", gm.INSTALL_ACTIONS["node"], "Node 用 LTS")
        self.assertIn("Python.Python.3.14", gm.INSTALL_ACTIONS["python"])
        self.assertNotIn("winget", gm.INSTALL_ACTIONS["claude"], "Claude Code 用官方原生安裝（winget 版不會自動更新）")
        self.assertTrue(gm.INSTALL_ACTIONS["claude"][-1].endswith("stable"))
        self.assertEqual(gm.install_button("python", False), ("page", gm.DOWNLOAD_PAGES["python"]), "沒有 winget 退回開下載頁")
        self.assertEqual(gm.install_button("claude", False)[0], "install", "Claude Code 不靠 winget")
        self.assertIsNone(gm.install_button("deno", False), "沒 winget 又沒有下載頁就不放按鈕")
        self.assertIsNone(gm.install_button(None, True))

    def test_runtime_rows_use_config_minimum(self):
        class R:
            def __init__(self, out):
                self.stdout, self.returncode = out, 0
        outs = {"deno": b"deno 2.9.8 (stable)", "node": b"v20.1.0"}
        env = gm.env_status(which=lambda n: n if n in outs else None, importer=lambda m: None, ffmpeg=lambda: None,
                            claude_status=lambda r: (True, "x"), run=lambda cmd, **k: R(outs.get(cmd[0], b"")))
        self.assertTrue(env["deno"].ok)
        self.assertIsNone(env["node"].ok)
        self.assertIn("太舊", env["node"].detail)
        self.assertEqual(env["node"].action, "node")
        self.assertEqual(gm.video.js_min(), {"deno": (2, 3, 0), "node": (22, 0, 0)}, "門檻來自 config/video.json")


class KeyTests(unittest.TestCase):
    def test_each_key_kind_uses_expected_endpoint_and_hides_value(self):
        seen = []

        def http(url, headers=None, data=None, timeout=20):
            seen.append((url, headers or {}, data))
            if "cwa.gov.tw" in url:
                return 200, '{"success":"true"}'
            if "moenv" in url:
                return 200, '[{"sitename":"基隆"}]'
            if "openid-connect/token" in url:
                return 200, '{"access_token":"t"}'
            return 200, "{}"
        for name in gm.KEY_INFO:
            ok, msg = gm.test_key(name, "VALUE123", {"tdx_id": "ID", "tdx_secret": "SEC"}, http=http)
            self.assertTrue(ok, f"{name}: {msg}")
            self.assertNotIn("VALUE123", msg)
        self.assertTrue(any("x-goog-api-key" in h for _, h, _ in seen))
        ok, msg = gm.test_key("moenv", "k", http=lambda *a, **k: (200, "該 API KEY 不存在或是已經到期。"))
        self.assertFalse(ok, "環境部錯誤金鑰也回 200，要看內容")
        ok, msg = gm.test_key("exa", "k", http=lambda *a, **k: (402, "no credits"))
        self.assertFalse(ok)
        self.assertIn("額度", msg)
        self.assertEqual(gm.test_key("cwa", "   ")[0], False)

    def test_chrome_live_test_parses_result(self):
        class R:
            def __init__(self, out):
                self.stdout, self.stderr = out.encode(), b""
        ok, msg = gm.chrome_live_test(run=lambda *a, **k: R(json.dumps({"result": "CHROME_OK", "total_cost_usd": 0.5})), which=lambda n: "claude")
        self.assertTrue(ok and "0.50" in msg, msg)
        ok, msg = gm.chrome_live_test(run=lambda *a, **k: R(json.dumps({"result": "CHROME_FAIL: 未連線"})), which=lambda n: "claude")
        self.assertFalse(ok)
        self.assertIn("未連線", msg)


if __name__ == "__main__":
    unittest.main()
