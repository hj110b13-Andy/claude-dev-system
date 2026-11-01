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


class McpDescriptionCap(Base):
    def test_env_default_has_description_cap(self):
        src = json.loads((REPO / "config" / "web-sources.json").read_text(encoding="utf-8"))
        self.assertEqual(src["env"]["CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH"], "1024")
        from cds import web as w
        env = w.desired_env(src, {"keys": {}, "enable": [], "disable": [], "env": {}})
        self.assertEqual(env["CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH"], "1024")


class KeyModeFree(Base):
    def test_free_mode_registers_keyless_only(self):
        from cds import web as w
        src = {"mcpServers": {"exa": {"url": "https://mcp.exa.ai/mcp", "default": True, "keyHeader": "x-api-key"}}}
        both = w.desired_servers(src, {"keys": {"exa": "K"}, "enable": [], "disable": [], "env": {}})
        self.assertEqual(set(both), {"exa", "exa-key"})
        free = w.desired_servers(src, {"keys": {"exa": "K"}, "enable": [], "disable": [], "env": {}, "keyMode": {"exa": "free"}})
        self.assertEqual(set(free), {"exa"})
        self.assertNotIn("x-api-key", free["exa"]["headers"], "free 模式不帶金鑰")
        local = {"keys": {}}
        w.set_key_mode_arg(local, "exa=free")
        self.assertEqual(local["keyMode"]["exa"], "free")
        with self.assertRaises(ValueError):
            w.set_key_mode_arg(local, "exa=bogus")


class Preservation(Base):
    def test_existing_usage_guard_hook_not_duplicated(self):
        s = copy.deepcopy(USER_SETTINGS)
        s["hooks"]["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command": "py -3 C:/x/usage_guard.py"}]}]
        s["hooks"]["PostToolUse"].append({"matcher": "Bash", "hooks": [{"type": "command", "command": "py -3 C:/x/usage_guard.py"}]})
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
        cfg.write_text(cfg.read_text(encoding="utf-8").replace('"fiveHour": 85', '"fiveHour": 81'), encoding="utf-8")
        log = self.install(mode="update")
        self.assertIn("（我改過）", self.lay.claude_md.read_text(encoding="utf-8"))
        self.assertIn('"fiveHour": 81', cfg.read_text(encoding="utf-8"))
        self.assertTrue((self.lay.payload / "CLAUDE-block.new.md").exists())
        self.assertFalse((cfg.parent / "dispatch-config.json.new").exists(), "可編輯設定檔不該再生 .new（0.9.6）")
        self.assertTrue(any("保留使用者設定" in x for x in log))
        self.assertTrue(any("使用者改動" in x for x in log))
        (cfg.parent / "dispatch-config.json.new").write_text("{}", encoding="utf-8")  # 模擬舊版留下的
        log = self.install(mode="update")
        self.assertFalse((cfg.parent / "dispatch-config.json.new").exists(), "舊版留下的 .new 應被清掉")
        self.assertTrue(any("移除多餘的" in x for x in log))
        d = json.loads(cfg.read_text(encoding="utf-8"))
        d.pop("taskCheck", None)  # 模擬舊版使用者檔缺新版才有的頂層鍵
        cfg.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        log = self.install(mode="update")
        d2 = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertIn("taskCheck", d2, "新版新增的頂層鍵要補進使用者檔")
        self.assertEqual(d2["usageThresholdPct"]["fiveHour"], 81, "使用者改過的值不可動")
        self.assertTrue(any("補上新版新增的 taskCheck" in x for x in log))
        code, out = self.verify()
        self.assertEqual(code, 0)
        self.assertTrue(any(x.startswith("✅") and "dispatch-config.json" in x and "使用者自己的設定值" in x for x in out), "可編輯設定檔在 verify 是 ✅ 不是 ⚠️")
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any(x.startswith("⚠️") for x in out))
        commands.uninstall(self.lay)
        self.assertTrue(cfg.exists(), "使用者改過的設定檔不應被刪")
        self.assertEqual(self.lay.claude_md.read_text(encoding="utf-8"), USER_MD)

    def test_crlf_claude_md_keeps_crlf_and_uninstall_restores_bytes(self):
        raw = USER_MD.replace(chr(10), chr(13) + chr(10)).encode("utf-8")
        self.lay.claude_md.write_bytes(raw)
        self.install()
        b = self.lay.claude_md.read_bytes()
        self.assertTrue(b.startswith(raw), "區塊外的位元組一字不動（含 CRLF）")
        self.assertNotIn(b"\n", b.replace(b"\r\n", b""), "整個檔案都是 CRLF，不能混 LF")
        self.assertEqual(self.verify()[0], 0)
        self.install(mode="update")
        self.assertEqual(self.lay.claude_md.read_bytes()[:len(raw)], raw)
        commands.uninstall(self.lay)
        self.assertEqual(self.lay.claude_md.read_bytes(), raw, "解除安裝後位元組完全還原")

    def test_backups_pruned_to_ten(self):
        self.write_settings(copy.deepcopy(USER_SETTINGS))
        self.install()
        for _ in range(12):
            self.install(mode="update")
        m = json.loads(self.lay.manifest.read_text(encoding="utf-8"))
        self.assertEqual(len(m["backups"]), commands.KEEP_BACKUPS)
        files = list(self.lay.backups.glob("claude-dev-system-*.json"))
        self.assertLessEqual(len(files), commands.KEEP_BACKUPS)

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
        self.assertEqual(m["schemaVersion"], 3)
        self.assertEqual(m["files"], {"a": "b"})
        self.assertIn("settings", m)
        self.assertEqual(m["web"], {"enabled": False, "mcpAdded": [], "envCreatedKeys": [], "skipped": []})
        self.assertEqual(m["video"], {"enabled": False, "packages": [], "python": None})

    def test_manifest_migration_from_v1_keeps_fields(self):
        m = mf.migrate({"schemaVersion": 1, "version": "0.2.1", "files": {"a": "b"}, "skills": ["x"]})
        self.assertEqual(m["schemaVersion"], 3)
        self.assertEqual(m["skills"], ["x"])
        self.assertFalse(m["web"]["enabled"])
        self.assertFalse(m["video"]["enabled"])

    def test_manifest_migration_from_v2_keeps_web(self):
        m = mf.migrate({"schemaVersion": 2, "version": "0.4.9", "files": {}, "web": {"enabled": True, "mcpAdded": ["exa"], "envCreatedKeys": [], "skipped": []}})
        self.assertEqual(m["schemaVersion"], 3)
        self.assertEqual(m["web"]["mcpAdded"], ["exa"])
        self.assertFalse(m["video"]["enabled"])

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
    DEFAULTS = {"parallel", "exa", "context7", "deepwiki", "mslearn", "firecrawl"}  # web-sources.json 的 default:true 項目

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
        self.assertEqual(set(self.servers()), self.DEFAULTS, "預設只開 web-sources.json 標 default 的項目")
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
        self.assertEqual(m["web"]["mcpAdded"], sorted(self.DEFAULTS))
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
        self.assertEqual(set(self.servers()), self.DEFAULTS)

    def test_web_config_enable_tavily_keyless_then_key_then_disable(self):
        self.apply(with_web=True)
        code, log = commands.web_config(self.lay, enable=["tavily"], runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        t = self.servers()["tavily"]
        self.assertEqual(t["url"], "https://mcp.tavily.com/mcp/")
        self.assertEqual(t["headers"], {"X-Tavily-Access-Mode": "keyless"})
        code, log = commands.web_config(self.lay, keys=["tavily=SECRET123"], runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        t = self.servers()["tavily"]  # 免費優先：免金鑰版留著
        self.assertEqual(t["headers"], {"X-Tavily-Access-Mode": "keyless"})
        k = self.servers()["tavily-key"]  # 金鑰版另外註冊
        self.assertIn("tavilyApiKey=SECRET123", k["url"])
        self.assertNotIn("headers", k, "金鑰版應拿掉 keyless header")
        self.assertFalse(any("SECRET123" in x for x in log), "輸出不可印出金鑰")
        code, log = commands.web_config(self.lay, key_mode=["tavily=always"], runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        self.assertNotIn("tavily-key", self.servers(), "always 模式只留金鑰版")
        self.assertIn("tavilyApiKey=SECRET123", self.servers()["tavily"]["url"])
        code, log = commands.web_config(self.lay, key_mode=["tavily=fallback"], runner=self.runner)
        self.assertIn("tavily-key", self.servers())
        self.assertEqual(json.loads(web.local_path(self.lay).read_text(encoding="utf-8"))["keys"]["tavily"], "SECRET123")
        code, log = commands.web_config(self.lay, disable=["tavily"], runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        self.assertNotIn("tavily", self.servers())
        self.assertNotIn("tavily-key", self.servers(), "關掉時金鑰版一起移除")
        self.assertEqual(set(self.servers()), self.DEFAULTS)
        code, log = commands.web_config(self.lay, enable=["nope"], runner=self.runner)
        self.assertEqual(code, 2)

    def test_exa_key_goes_to_header_as_key_variant(self):
        self.apply(with_web=True)
        commands.web_config(self.lay, keys=["exa=EXAKEY"], runner=self.runner)
        self.assertNotIn("headers", self.servers()["exa"], "免金鑰版不帶金鑰")
        e = self.servers()["exa-key"]
        self.assertEqual(e["url"], "https://mcp.exa.ai/mcp")
        self.assertEqual(e["headers"], {"x-api-key": "EXAKEY"})
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any("MCP exa-key 已註冊" in x for x in out))
        commands.web_config(self.lay, keys=["exa="], runner=self.runner)  # 清掉金鑰 → -key 版移除
        self.assertNotIn("exa-key", self.servers())

    def test_parallel_and_firecrawl_keys_use_bearer(self):
        self.apply(with_web=True)
        commands.web_config(self.lay, keys=["parallel=PK", "firecrawl=FK"], runner=self.runner)
        self.assertEqual(self.servers()["parallel-key"]["headers"], {"Authorization": "Bearer PK"})
        self.assertEqual(self.servers()["firecrawl-key"]["headers"], {"Authorization": "Bearer FK"})
        code, log = commands.web_config(self.lay, key_mode=["exa=bogus"], runner=self.runner)
        self.assertEqual(code, 2)

    def test_context7_key_goes_to_bearer_header(self):
        self.write_settings(USER_SETTINGS)
        self.apply(with_web=True)
        code, log = commands.web_config(self.lay, keys=["context7=ctx7sk-abc"], runner=self.runner)
        self.assertEqual(code, 0, "\n".join(log))
        self.assertEqual(self.servers()["context7-key"]["headers"], {"Authorization": "Bearer ctx7sk-abc"})
        self.assertNotIn("headers", self.servers()["context7"])
        self.assertFalse(any("ctx7sk-abc" in x for x in log))
        code, log = commands.web_config(self.lay, keys=["context7="], runner=self.runner)  # 清掉金鑰 → 只剩免金鑰
        self.assertEqual(code, 0, "\n".join(log))
        self.assertNotIn("context7-key", self.servers())

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


def fake_pip(calls: list, fail: bool = False):
    def run(python: str, packages: list[str]):
        calls.append((python, list(packages)))
        return (1, "ERROR: No matching distribution") if fail else (0, "")
    return run


def fake_importer(installed: dict):
    return lambda mod: installed.get(mod)


class VideoSource(Base):
    PACKAGES = ["yt-dlp[default,curl-cffi]", "youtube-transcript-api"]  # config/video.json
    FULL = {"yt_dlp": "2026.10.26", "youtube_transcript_api": "", "faster_whisper": "1.2.1"}

    def setUp(self):
        super().setUp()
        self.pip_calls: list = []

    def apply(self, mode="install", with_video=None, fail=False):
        code, log = commands.apply(self.lay, PY, repo=REPO, mode=mode, with_video=with_video, pip=fake_pip(self.pip_calls, fail),
                                   runner=fake_mcp_runner(self.lay, []))
        return code, log

    def verify(self, installed=None, ffmpeg="/usr/bin/ffmpeg"):
        return commands.verify(self.lay, repo=REPO, check_claude=False, importer=fake_importer(installed if installed is not None else self.FULL),
                               ffmpeg=lambda: ffmpeg)

    def test_default_install_touches_no_video(self):
        code, _ = self.apply()
        self.assertEqual(code, 0)
        self.assertEqual(self.pip_calls, [])
        self.assertFalse(mf.load(self.lay.manifest)["video"]["enabled"])
        code, out = self.verify(installed={})
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any("影片來源：未啟用" in x for x in out))

    def test_with_video_installs_records_and_verifies(self):
        code, log = self.apply(with_video=True)
        self.assertEqual(code, 0, "\n".join(log))
        self.assertEqual(self.pip_calls, [(PY, self.PACKAGES)])
        m = mf.load(self.lay.manifest)
        self.assertEqual(m["video"], {"enabled": True, "packages": self.PACKAGES, "python": PY})
        self.assertTrue((self.lay.payload / "config" / "video.json").exists())
        self.assertTrue((self.lay.payload / "tools" / "video.py").exists())
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any(x.startswith("✅") and "yt-dlp 2026.10.26" in x for x in out))
        self.assertTrue(any(x.startswith("✅") and "faster-whisper 1.2.1" in x for x in out))

    def test_update_keeps_video_enabled(self):
        self.apply(with_video=True)
        code, _ = self.apply(mode="update")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.pip_calls), 2, "update 沿用啟用狀態並重跑 pip（升級）")
        self.assertTrue(mf.load(self.lay.manifest)["video"]["enabled"])

    def test_missing_whisper_is_warning_missing_ytdlp_is_error(self):
        self.apply(with_video=True)
        code, out = self.verify(installed={"yt_dlp": "2026.10.26", "youtube_transcript_api": ""})
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any(x.startswith("⚠️") and "faster-whisper" in x for x in out))
        code, out = self.verify(installed={"youtube_transcript_api": ""})
        self.assertEqual(code, 1)
        self.assertTrue(any(x.startswith("❌") and "yt-dlp" in x for x in out))
        code, out = self.verify(ffmpeg=None)
        self.assertEqual(code, 1)
        self.assertTrue(any(x.startswith("❌") and "ffmpeg" in x for x in out))

    def test_pip_failure_sets_exit_code(self):
        code, log = self.apply(with_video=True, fail=True)
        self.assertEqual(code, 1)
        self.assertTrue(any(x.startswith("❌") and "影片套件安裝失敗" in x for x in log))
        self.assertEqual(mf.load(self.lay.manifest)["video"]["packages"], [])

    def test_video_subcommand_enable_show_off(self):
        self.apply()
        code, log = commands.video_config(self.lay, PY, pip=fake_pip(self.pip_calls), importer=fake_importer(self.FULL), ffmpeg=lambda: "ffmpeg")
        self.assertEqual(code, 0, "\n".join(log))
        self.assertEqual(self.pip_calls, [(PY, self.PACKAGES)])
        self.assertTrue(mf.load(self.lay.manifest)["video"]["enabled"])
        code, log = commands.video_config(self.lay, PY, show=True, importer=fake_importer(self.FULL), ffmpeg=lambda: "ffmpeg")
        self.assertEqual(code, 0)
        self.assertTrue(any("yt-dlp" in x for x in log))
        code, log = commands.video_config(self.lay, PY, off=True, pip=fake_pip(self.pip_calls))
        self.assertEqual(code, 0)
        self.assertFalse(mf.load(self.lay.manifest)["video"]["enabled"])
        self.assertEqual(len(self.pip_calls), 1, "--off 不跑 pip")
        self.assertTrue(any("pip 套件未移除" in x for x in log))

    def test_keys_listed_in_verify(self):
        self.apply(with_video=True)
        web.save_local(self.lay, {"keys": {"youtube": "AIzaX", "gemini": "AQ.Y"}, "enable": [], "disable": [], "env": {}})
        code, out = self.verify()
        self.assertEqual(code, 0, "\n".join(out))
        self.assertTrue(any("影片金鑰：gemini, youtube" in x for x in out))
        self.assertFalse(any("AIzaX" in x or "AQ.Y" in x for x in out), "金鑰值不得出現在輸出")


if __name__ == "__main__":
    unittest.main()
