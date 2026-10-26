"""安裝器自我測試：假的 CLAUDE_HOME 上跑 install→verify→update→uninstall，確認使用者設定不被破壞。

執行：python -m unittest discover -s tests -v   （或 python -m pytest tests）
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))

from cds import claudemd, commands, manifest as mf, web  # noqa: E402
from cds.paths import Layout  # noqa: E402

PY = Path(sys.executable).as_posix()

USER_SETTINGS = {
    "permissions": {"allow": ["Bash(git status)", "WebSearch"], "deny": ["Bash(rm -rf /)"]},
    "model": "opus",
    "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
        "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "echo edited"}]}],
    },
    "statusLine": {"type": "command", "command": "python statusline.py", "padding": 0},
    "language": "chinese",
    "effortLevel": "high",
    "enabledPlugins": {"foo@bar": True},
}
USER_MD = "# 我的全域規則\n\n- 規則一\n- 規則二（沒有結尾換行）"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-test-"))
        self.lay = Layout(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_settings(self, obj, raw: str | None = None):
        self.lay.settings.write_text(raw if raw is not None else json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def settings(self):
        return json.loads(self.lay.settings.read_text(encoding="utf-8"))

    def install(self, mode="install", force=False):
        code, log = commands.apply(self.lay, PY, repo=REPO, force=force, mode=mode)
        self.assertEqual(code, 0, "\n".join(log))
        return log

    def verify(self):
        return commands.verify(self.lay, repo=REPO, check_claude=False)


class FullCycle(Base):
    def test_install_verify_update_uninstall_keeps_user_settings(self):
        raw = json.dumps(USER_SETTINGS, ensure_ascii=False, indent=4)  # 故意用不同排版
        self.write_settings(None, raw)
        self.lay.claude_md.write_text(USER_MD, encoding="utf-8")

        self.install()
        s = self.settings()
        for k, v in USER_SETTINGS.items():
            if k != "hooks":
                self.assertEqual(s[k], v, f"使用者鍵 {k} 被改動")
        self.assertEqual(s["hooks"]["Stop"], USER_SETTINGS["hooks"]["Stop"])
        self.assertEqual(s["hooks"]["PostToolUse"][0], USER_SETTINGS["hooks"]["PostToolUse"][0])
        self.assertEqual(len(s["hooks"]["PostToolUse"]), 2)
        self.assertIn("UserPromptSubmit", s["hooks"])
        md = self.lay.claude_md.read_text(encoding="utf-8")
        self.assertTrue(md.startswith(USER_MD), "區塊外內容被改動")

        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertFalse(any(x.startswith("❌") for x in out))

        self.install(mode="update")
        self.assertEqual(len(self.settings()["hooks"]["PostToolUse"]), 2, "update 造成重複 hook")
        self.assertEqual(self.verify()[0], 0)

        commands.uninstall(self.lay)
        self.assertEqual(self.settings(), USER_SETTINGS, "解除後與原檔逐鍵不相等")
        self.assertEqual(self.lay.settings.read_text(encoding="utf-8"), raw, "解除後原排版未還原")
        self.assertEqual(self.lay.claude_md.read_text(encoding="utf-8"), USER_MD)
        self.assertFalse(self.lay.payload.exists())
        self.assertFalse(any((self.lay.skills).glob("cds-*")))

    def test_fresh_home_leaves_nothing(self):
        self.install()
        self.assertEqual(self.verify()[0], 0)
        commands.uninstall(self.lay)
        self.assertFalse(self.lay.settings.exists())
        self.assertFalse(self.lay.claude_md.exists())
        self.assertFalse(self.lay.payload.exists())

    def test_install_twice_requires_update(self):
        self.install()
        code, _ = commands.apply(self.lay, PY, repo=REPO, mode="install")
        self.assertEqual(code, 2)

    def test_user_edits_outside_block_survive_uninstall(self):
        self.lay.claude_md.write_text(USER_MD, encoding="utf-8")
        self.install()
        md = self.lay.claude_md.read_text(encoding="utf-8") + "\n- 安裝後新增的規則\n"
        self.lay.claude_md.write_text(md, encoding="utf-8")
        commands.uninstall(self.lay)
        self.assertEqual(self.lay.claude_md.read_text(encoding="utf-8"), USER_MD + "\n- 安裝後新增的規則\n")

    def test_user_adds_hook_after_install(self):
        self.write_settings(USER_SETTINGS)
        self.install()
        s = self.settings()
        s["hooks"]["UserPromptSubmit"].append({"hooks": [{"type": "command", "command": "echo mine"}]})
        s["theme"] = "dark"
        self.write_settings(s)
        commands.uninstall(self.lay)
        want = copy.deepcopy(USER_SETTINGS)
        want["hooks"]["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command": "echo mine"}]}]
        want["theme"] = "dark"
        self.assertEqual(self.settings(), want)


class Preservation(Base):
    def test_existing_usage_guard_hook_not_duplicated(self):
        s = copy.deepcopy(USER_SETTINGS)
        s["hooks"]["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command": "py -3 C:/x/usage_guard.py"}]}]
        s["hooks"]["PostToolUse"].append({"matcher": "*", "hooks": [{"type": "command", "command": "py -3 C:/x/usage_guard.py"}]})
        raw = json.dumps(s, indent=2)
        self.write_settings(None, raw)
        self.install()
        self.assertEqual(self.lay.settings.read_text(encoding="utf-8"), raw, "已有同功能 hook 時不應寫 settings.json")
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        commands.uninstall(self.lay)
        self.assertEqual(self.lay.settings.read_text(encoding="utf-8"), raw)

    def test_user_modified_block_and_config_preserved_on_update(self):
        self.lay.claude_md.write_text(USER_MD, encoding="utf-8")
        self.install()
        md = self.lay.claude_md.read_text(encoding="utf-8").replace("先界定範圍再動手", "先界定範圍再動手（我改過）")
        self.lay.claude_md.write_text(md, encoding="utf-8")
        cfg = self.lay.payload / "config" / "dispatch-config.json"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace('"fiveHour": 80', '"fiveHour": 81'), encoding="utf-8")
        log = self.install(mode="update")
        self.assertIn("（我改過）", self.lay.claude_md.read_text(encoding="utf-8"))
        self.assertIn('"fiveHour": 81', cfg.read_text(encoding="utf-8"))
        self.assertTrue((self.lay.payload / "CLAUDE-block.new.md").exists())
        self.assertTrue(any("使用者改動" in x for x in log))
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any(x.startswith("⚠️") for x in out))
        commands.uninstall(self.lay)
        self.assertTrue(cfg.exists(), "使用者改過的設定檔不應被刪")
        self.assertEqual(self.lay.claude_md.read_text(encoding="utf-8"), USER_MD)

    def test_force_update_overwrites_user_changes(self):
        self.install()
        cfg = self.lay.payload / "config" / "dispatch-config.json"
        cfg.write_text("{}", encoding="utf-8")
        self.install(mode="update", force=True)
        self.assertIn("usageThresholdPct", cfg.read_text(encoding="utf-8"))

    def test_foreign_skill_dir_not_overwritten(self):
        d = self.lay.skills / "cds-safe-refactor"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("mine", encoding="utf-8")
        self.install()
        self.assertEqual((d / "SKILL.md").read_text(encoding="utf-8"), "mine")
        self.assertEqual(self.verify()[0], 0)
        commands.uninstall(self.lay)
        self.assertEqual((d / "SKILL.md").read_text(encoding="utf-8"), "mine")

    def test_tampered_file_fails_verify(self):
        self.install()
        (self.lay.payload / "rules" / "core.md").write_text("改壞", encoding="utf-8")
        code, out = self.verify()
        self.assertEqual(code, 1)
        self.assertTrue(any(x.startswith("❌") and "core.md" in x for x in out))

    def test_restore_backup(self):
        self.write_settings(USER_SETTINGS)
        self.install()
        commands.uninstall(self.lay, restore_backup=True)
        self.assertEqual(self.settings(), USER_SETTINGS)


class Units(unittest.TestCase):
    def test_block_roundtrip_no_trailing_newline(self):
        block = claudemd.make_block("body", "0.1.0")
        t, sep = claudemd.upsert("abc", block)
        self.assertEqual(claudemd.remove(t, sep), "abc")
        t2, sep2 = claudemd.upsert(t, claudemd.make_block("body2", "0.2.0"))
        self.assertIsNone(sep2)
        self.assertIn("body2", t2)
        self.assertEqual(claudemd.remove(t2, sep), "abc")

    def test_missing_end_marker_raises(self):
        with self.assertRaises(ValueError):
            claudemd.find_block("<!-- claude-dev-system:begin v1 -->\nxx")

    def test_manifest_migration_from_v0(self):
        m = mf.migrate({"version": "0.0.9", "files": {"a": "b"}})
        self.assertEqual(m["schemaVersion"], 2)
        self.assertEqual(m["files"], {"a": "b"})
        self.assertIn("settings", m)
        self.assertEqual(m["web"], {"enabled": False, "mcpAdded": [], "envCreatedKeys": [], "skipped": []})

    def test_manifest_migration_from_v1_keeps_fields(self):
        m = mf.migrate({"schemaVersion": 1, "version": "0.2.1", "files": {"a": "b"}, "skills": ["x"]})
        self.assertEqual(m["schemaVersion"], 2)
        self.assertEqual(m["skills"], ["x"])
        self.assertFalse(m["web"]["enabled"])

    def test_newer_manifest_schema_rejected(self):
        with self.assertRaises(RuntimeError):
            mf.migrate({"schemaVersion": 99})


def fake_mcp_runner(lay: Layout, calls: list):
    """模擬 `claude mcp add／remove --scope user`：寫入 web.user_config_path(lay) 的 mcpServers，行為照 2.1.296 實測。"""
    p = web.user_config_path(lay)

    def run(args: list[str]):
        calls.append(list(args))
        cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        servers = cfg.setdefault("mcpServers", {})
        if args[0] == "add":
            name, url = args[5], args[6]
            if name in servers:
                return 1, f"MCP server {name} already exists in user config"
            entry = {"type": "http", "url": url}
            hdrs, i = {}, 7
            while i < len(args):
                if args[i] == "--header":
                    k, v = args[i + 1].split(": ", 1)
                    hdrs[k] = v
                    i += 2
                else:
                    i += 1
            if hdrs:
                entry["headers"] = hdrs
            servers[name] = entry
        elif args[0] == "remove":
            name = args[3]
            if name not in servers:
                return 1, f'No MCP server named "{name}" in user scope'
            del servers[name]
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0, "ok"
    return run


class WebSources(Base):
    ENV_KEYS = ("CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION", "CLAUDE_CODE_WEB_SEARCH_REFILLS_PER_HOUR")

    def setUp(self):
        super().setUp()
        self.calls: list = []
        self.runner = fake_mcp_runner(self.lay, self.calls)

    def servers(self):
        p = web.user_config_path(self.lay)
        return json.loads(p.read_text(encoding="utf-8")).get("mcpServers", {}) if p.exists() else {}

    def apply(self, mode="install", with_web=None):
        code, log = commands.apply(self.lay, PY, repo=REPO, mode=mode, with_web=with_web, runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        return log

    def test_default_install_touches_no_web(self):
        self.write_settings(USER_SETTINGS)
        self.apply()
        self.assertEqual(self.servers(), {})
        self.assertNotIn("env", self.settings())
        self.assertEqual(self.calls, [])
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any("未啟用" in x for x in out))

    def test_with_web_defaults_env_verify_uninstall(self):
        self.write_settings(USER_SETTINGS)
        self.apply(with_web=True)
        self.assertEqual(set(self.servers()), {"parallel", "exa"}, "預設只開 parallel 與 exa")
        self.assertEqual(self.servers()["parallel"]["url"], "https://search.parallel.ai/mcp")
        env = self.settings()["env"]
        self.assertEqual(env["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"], "600")
        self.assertEqual(env["CLAUDE_CODE_WEB_SEARCH_REFILLS_PER_HOUR"], "300")
        for k, v in USER_SETTINGS.items():
            if k != "hooks":
                self.assertEqual(self.settings()[k], v)
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any("MCP parallel 已註冊" in x for x in out))
        m = mf.load(self.lay.manifest)
        self.assertEqual(m["web"]["mcpAdded"], ["exa", "parallel"])
        self.assertIn("env", m["web"]["envCreatedKeys"])
        commands.uninstall(self.lay, runner=self.runner)
        self.assertEqual(self.servers(), {})
        self.assertEqual(self.settings(), USER_SETTINGS, "解除後 env 應整個移除、其他鍵不變")

    def test_update_keeps_web_enabled_without_re_adding(self):
        self.apply(with_web=True)
        adds = len([c for c in self.calls if c[0] == "add"])
        self.apply(mode="update")
        self.assertTrue(mf.load(self.lay.manifest)["web"]["enabled"])
        self.assertEqual(len([c for c in self.calls if c[0] == "add"]), adds, "update 不應重複註冊")
        self.assertEqual(set(self.servers()), {"parallel", "exa"})

    def test_web_config_enable_tavily_keyless_then_key_then_disable(self):
        self.apply(with_web=True)
        code, log = commands.web_config(self.lay, enable=["tavily"], runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        t = self.servers()["tavily"]
        self.assertEqual(t["url"], "https://mcp.tavily.com/mcp/")
        self.assertEqual(t["headers"], {"X-Tavily-Access-Mode": "keyless"})
        code, log = commands.web_config(self.lay, keys=["tavily=SECRET123"], runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        t = self.servers()["tavily"]
        self.assertIn("tavilyApiKey=SECRET123", t["url"])
        self.assertNotIn("headers", t, "有金鑰時應拿掉 keyless header")
        self.assertFalse(any("SECRET123" in x for x in log), "輸出不可印出金鑰")
        self.assertEqual(json.loads(web.local_path(self.lay).read_text(encoding="utf-8"))["keys"]["tavily"], "SECRET123")
        code, log = commands.web_config(self.lay, disable=["tavily"], runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        self.assertNotIn("tavily", self.servers())
        self.assertEqual(set(self.servers()), {"parallel", "exa"})
        code, log = commands.web_config(self.lay, enable=["nope"], runner=self.runner)
        self.assertEqual(code, 2)

    def test_exa_key_goes_to_header(self):
        self.apply(with_web=True)
        commands.web_config(self.lay, keys=["exa=EXAKEY"], runner=self.runner)
        e = self.servers()["exa"]
        self.assertEqual(e["url"], "https://mcp.exa.ai/mcp")
        self.assertEqual(e["headers"], {"x-api-key": "EXAKEY"})

    def test_user_own_server_and_env_untouched(self):
        p = web.user_config_path(self.lay)
        p.write_text(json.dumps({"oauth": "keep", "mcpServers": {"exa": {"type": "http", "url": "https://my.exa/mcp"}}}), encoding="utf-8")
        s = copy.deepcopy(USER_SETTINGS)
        s["env"] = {"CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION": "50", "MY_VAR": "1"}
        self.write_settings(s)
        log = self.apply(with_web=True)
        self.assertEqual(self.servers()["exa"]["url"], "https://my.exa/mcp", "使用者自己的同名 MCP 不可覆蓋")
        self.assertIn("parallel", self.servers())
        env = self.settings()["env"]
        self.assertEqual(env["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"], "50", "使用者自己設的 env 不可覆蓋")
        self.assertEqual(env["CLAUDE_CODE_WEB_SEARCH_REFILLS_PER_HOUR"], "300")
        self.assertEqual(env["MY_VAR"], "1")
        self.assertTrue(any("exa 已由使用者自行設定" in x for x in log))
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any(x.startswith("⚠️") and "exa" in x for x in out))
        commands.uninstall(self.lay, runner=self.runner)
        self.assertEqual(self.servers(), {"exa": {"type": "http", "url": "https://my.exa/mcp"}})
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["oauth"], "keep")
        self.assertEqual(self.settings()["env"], {"CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION": "50", "MY_VAR": "1"})

    def test_web_off_removes_but_keeps_local_json(self):
        self.apply(with_web=True)
        commands.web_config(self.lay, keys=["cwa=CWA-XYZ"], runner=self.runner)
        code, log = commands.web_config(self.lay, off=True, runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        self.assertEqual(self.servers(), {})
        self.assertNotIn("env", self.settings())
        self.assertFalse(mf.load(self.lay.manifest)["web"]["enabled"])
        self.assertTrue(web.local_path(self.lay).exists())
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        commands.uninstall(self.lay, runner=self.runner)
        self.assertTrue(web.local_path(self.lay).exists(), "uninstall 不可刪使用者金鑰檔")

    def test_env_not_dict_is_skipped_not_overwritten(self):
        s = copy.deepcopy(USER_SETTINGS)
        s["env"] = "oops"
        self.write_settings(s)
        log = self.apply(with_web=True)
        self.assertEqual(self.settings()["env"], "oops", "env 不是物件時不可覆蓋")
        self.assertTrue(any("env 不是物件" in x for x in log))
        self.assertEqual(mf.load(self.lay.manifest)["web"]["envCreatedKeys"], [])
        commands.uninstall(self.lay, runner=self.runner)
        self.assertEqual(self.settings()["env"], "oops")

    def test_same_value_preset_by_user_is_not_claimed(self):
        s = copy.deepcopy(USER_SETTINGS)
        s["env"] = {"CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION": "600"}
        self.write_settings(s)
        self.apply(with_web=True)
        self.assertNotIn("env.CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION", mf.load(self.lay.manifest)["web"]["envCreatedKeys"])
        commands.uninstall(self.lay, runner=self.runner)
        self.assertEqual(self.settings()["env"], {"CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION": "600"}, "使用者預先設的同值不可被 uninstall 刪掉")

    def test_bad_local_json_gives_clean_error(self):
        self.apply(with_web=True)
        web.local_path(self.lay).write_text("{bad", encoding="utf-8")
        code, log = commands.web_config(self.lay, show=True, runner=self.runner)
        self.assertEqual(code, 2)
        self.assertIn("不是合法 JSON", log[0])
        with self.assertRaises(ValueError):
            commands.apply(self.lay, PY, repo=REPO, mode="update", runner=self.runner)
        code, log = commands.uninstall(self.lay, runner=self.runner)  # 偏好檔壞掉不該擋住移除
        self.assertEqual(code, 0, "\n".join(log))
        self.assertEqual(self.servers(), {})

    def test_runner_failure_sets_exit_code_and_masks_key(self):
        def failing(args):
            self.calls.append(list(args))
            return 127, "找不到 claude 指令 " + " ".join(args)
        code, log = commands.apply(self.lay, PY, repo=REPO, mode="install", with_web=True, runner=failing)
        self.assertEqual(code, 1, "\n".join(log))
        self.assertTrue(any(x.startswith("❌") and "parallel" in x for x in log))
        self.assertTrue(log[-1].startswith("❌"))
        self.assertTrue(mf.load(self.lay.manifest)["web"]["enabled"])
        self.assertEqual(mf.load(self.lay.manifest)["web"]["mcpAdded"], [])
        code, log = commands.web_config(self.lay, keys=["tavily=SECRET123"], enable=["tavily"], runner=failing)
        self.assertEqual(code, 1)
        self.assertFalse(any("SECRET123" in x for x in log), "失敗訊息也要遮金鑰")

    def test_show_when_disabled_says_so(self):
        self.apply()
        code, log = commands.web_config(self.lay, show=True, runner=self.runner)
        self.assertEqual(code, 0)
        self.assertTrue(any("目前未啟用" in x for x in log))
        self.assertEqual(self.calls, [])

    def test_tampered_mcp_fails_verify(self):
        self.apply(with_web=True)
        p = web.user_config_path(self.lay)
        cfg = json.loads(p.read_text(encoding="utf-8"))
        del cfg["mcpServers"]["parallel"]
        p.write_text(json.dumps(cfg), encoding="utf-8")
        code, out = self.verify()
        self.assertEqual(code, 1)
        self.assertTrue(any(x.startswith("❌") and "parallel" in x for x in out))
        self.apply(mode="update")  # 重跑會補回
        self.assertEqual(self.verify()[0], 0)


if __name__ == "__main__":
    unittest.main()
