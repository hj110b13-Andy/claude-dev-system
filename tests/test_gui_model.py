"""gui_model（設定視窗邏輯層）測試：假 CLAUDE_HOME 上讀狀態、算差異、套用、門檻、金鑰測試、匯出匯入。不開視窗。"""
from __future__ import annotations

import json
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

    def test_chrome_default_toggle_writes_claude_json_with_backup(self):
        p = web.user_config_path(self.lay)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"mcpServers": {}, "other": 1}), encoding="utf-8")
        self.assertIsNone(gm.chrome_default_enabled(self.lay))
        gm.set_chrome_default_enabled(self.lay, True)
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertTrue(d["claudeInChromeDefaultEnabled"] and d["other"] == 1)
        self.assertTrue(list(self.lay.backups.glob("claude-json-*.json")))


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
        ok, msg = gm.chrome_live_test(run=lambda *a, **k: R(json.dumps({"result": "CHROME_OK", "total_cost_usd": 0.5})))
        self.assertTrue(ok and "0.50" in msg)
        ok, msg = gm.chrome_live_test(run=lambda *a, **k: R(json.dumps({"result": "CHROME_FAIL: 未連線"})))
        self.assertFalse(ok)
        self.assertIn("未連線", msg)


if __name__ == "__main__":
    unittest.main()
