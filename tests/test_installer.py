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

from cds import claudemd, commands, manifest as mf  # noqa: E402
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
        cfg.write_text(cfg.read_text(encoding="utf-8").replace('"fiveHourLimit": 80', '"fiveHourLimit": 95'), encoding="utf-8")
        log = self.install(mode="update")
        self.assertIn("（我改過）", self.lay.claude_md.read_text(encoding="utf-8"))
        self.assertIn('"fiveHourLimit": 95', cfg.read_text(encoding="utf-8"))
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
        self.assertIn("fiveHourLimit", cfg.read_text(encoding="utf-8"))

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
        self.assertEqual(m["schemaVersion"], 1)
        self.assertEqual(m["files"], {"a": "b"})
        self.assertIn("settings", m)

    def test_newer_manifest_schema_rejected(self):
        with self.assertRaises(RuntimeError):
            mf.migrate({"schemaVersion": 99})


if __name__ == "__main__":
    unittest.main()
