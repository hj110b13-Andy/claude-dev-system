"""0.28.0：驗證守門（Stop 跑專案驗證指令）、Stop hook 時限、回覆語言設定（install.py web --language）、精簡來源格式的退回訊息。
全部用暫存資料夾，不碰真實 ~/.claude、不打網路、不呼叫 claude。"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))
spec = importlib.util.spec_from_file_location("usage_guard_v028", REPO / "hooks" / "usage_guard.py")
ug = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ug)  # type: ignore[union-attr]

from cds import commands, settings_ops, web  # noqa: E402
from cds.paths import Layout  # noqa: E402


def isolate_state(tc, tmp):
    """hook 的狀態檔（log）寫到暫存資料夾，不寫進真實 ~/.claude/state。"""
    saved = ug.STATE_DIR
    ug.STATE_DIR = str(tmp / "state")
    tc.addCleanup(setattr, ug, "STATE_DIR", saved)


def write_transcript(path: Path, entries):
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in entries) + "\n", encoding="utf-8")


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_use(name, file_path):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": name, "input": {"file_path": file_path}}]}}


def say(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


class VerifyGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-vg-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        isolate_state(self, self.tmp)
        (self.tmp / ".claude").mkdir()
        self.tr = self.tmp / "t.jsonl"
        self.calls = []

    def cfg(self, obj):
        (self.tmp / ".claude" / "dispatch-config.json").write_text(json.dumps({"verifyGate": obj}), encoding="utf-8")

    def runner(self, code, out="FAILED (failures=1)"):
        def run(cmd, cwd, timeout):
            self.calls.append((cmd, cwd, timeout))
            return code, out
        return run

    def payload(self, **kw):
        return {"cwd": str(self.tmp), "transcript_path": str(self.tr), **kw}

    def test_no_config_never_runs(self):
        write_transcript(self.tr, [user("修一下"), tool_use("Edit", "app/a.py"), say("好了")])
        self.assertIsNone(ug.verify_guard(self.payload(), runner=self.runner(1)))
        self.assertEqual(self.calls, [])

    def test_fail_after_code_edit_blocks_once(self):
        self.cfg({"command": "py -3 -m unittest", "timeoutSec": 30})
        write_transcript(self.tr, [user("修一下"), tool_use("Edit", "app/a.py"), say("好了")])
        out = ug.verify_guard(self.payload(), runner=self.runner(1))
        self.assertEqual(out["decision"], "block")
        self.assertIn("驗證守門", out["reason"])
        self.assertIn("FAILED", out["reason"])
        self.assertEqual(self.calls[0][2], 30)
        self.assertEqual(Path(self.calls[0][1]).resolve(), self.tmp.resolve())  # 在專案根跑
        self.assertIsNone(ug.verify_guard(self.payload(stop_hook_active=True), runner=self.runner(1)))

    def test_pass_does_not_block(self):
        self.cfg({"command": "x"})
        write_transcript(self.tr, [user("修"), tool_use("Write", "src/b.ts"), say("好")])
        self.assertIsNone(ug.verify_guard(self.payload(), runner=self.runner(0)))
        self.assertEqual(self.calls[0][2], ug.VG_DEFAULT_TIMEOUT)

    def test_only_this_turn_and_only_code_files(self):
        self.cfg({"command": "x"})
        write_transcript(self.tr, [user("第一輪"), tool_use("Edit", "app/a.py"), say("好"),
                                   user("第二輪只改文件"), tool_use("Edit", "README.md"), say("好")])
        self.assertIsNone(ug.verify_guard(self.payload(), runner=self.runner(1)))
        self.assertEqual(self.calls, [])

    def test_timeout_capped_and_errors_do_not_block(self):
        self.cfg({"command": "x", "timeoutSec": 9999})
        write_transcript(self.tr, [user("修"), tool_use("Edit", "a.py"), say("好")])

        def boom(cmd, cwd, timeout):
            self.calls.append(timeout)
            raise TimeoutError
        self.assertIsNone(ug.verify_guard(self.payload(), runner=boom))
        self.assertEqual(self.calls, [ug.VG_MAX_TIMEOUT])
        self.assertLess(ug.VG_MAX_TIMEOUT, settings_ops.HOOK_TIMEOUTS["Stop"])

    def test_waiting_agents_skip(self):
        self.cfg({"command": "x"})
        write_transcript(self.tr, [user("修"), tool_use("Edit", "a.py"), say("好")])
        self.assertIsNone(ug.verify_guard(self.payload(background_tasks=[{"type": "subagent"}]), runner=self.runner(1)))

    def test_disabled_flag(self):
        self.cfg({"command": "x", "enabled": False})
        write_transcript(self.tr, [user("修"), tool_use("Edit", "a.py"), say("好")])
        self.assertIsNone(ug.verify_guard(self.payload(), runner=self.runner(1)))


class HookTimeouts(unittest.TestCase):
    def test_stop_gets_longer_timeout_others_default(self):
        s, _ = settings_ops.add_hooks({}, "py -3 x.py # claude-dev-system")
        got = {e: g[0]["hooks"][0]["timeout"] for e, g in s["hooks"].items()}
        self.assertEqual(got["Stop"], 180)
        self.assertEqual(got["UserPromptSubmit"], 15)


class SourceFormatText(unittest.TestCase):
    def test_block_reason_asks_inline_link_not_sections(self):
        tmp = Path(tempfile.mkdtemp(prefix="cds-sg-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        isolate_state(self, tmp)
        tr = tmp / "t.jsonl"
        write_transcript(tr, [user("台北 101 有多高？"), say("台北 101 高 508 公尺，2004 年完工。" * 15)])
        out = ug.source_guard({"transcript_path": str(tr)})
        self.assertIsNotNone(out)
        self.assertIn("行內連結", out["reason"])
        self.assertIn("意思：", out["reason"])
        self.assertNotIn("末尾固定", out["reason"])

    def test_inline_link_passes(self):
        self.assertIsNone(ug.sg_judge("台北 101 有多高？", "台北 101 高 508 公尺（[來源](https://example.com)）。" * 15))


class Language(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-lang-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lay = Layout(self.tmp)
        (self.tmp / "settings.json").write_text(json.dumps({"model": "opus"}), encoding="utf-8")

    def settings(self):
        return json.loads((self.tmp / "settings.json").read_text(encoding="utf-8"))

    def test_set_and_off_keeps_other_keys(self):
        code, _ = commands.set_language(self.lay, "繁體中文")
        self.assertEqual(code, 0)
        self.assertEqual(self.settings(), {"model": "opus", "language": "繁體中文"})
        self.assertEqual(web.load_local(self.lay).get(commands.LANG_LOCAL_KEY), "繁體中文")
        code, _ = commands.set_language(self.lay, "off")
        self.assertEqual(self.settings(), {"model": "opus"})

    def test_off_does_not_touch_user_value(self):
        (self.tmp / "settings.json").write_text(json.dumps({"language": "japanese"}), encoding="utf-8")
        commands.set_language(self.lay, "off")
        self.assertEqual(self.settings(), {"language": "japanese"})

    def test_drop_own_language_only_if_unchanged(self):
        commands.set_language(self.lay, "繁體中文")
        s, rm = commands._drop_own_language(self.lay, {"language": "繁體中文", "x": 1})
        self.assertEqual((s, rm), ({"x": 1}, ["設定 language"]))
        s, rm = commands._drop_own_language(self.lay, {"language": "english"})
        self.assertEqual(rm, [])


rs_spec = importlib.util.spec_from_file_location("rule_stats", REPO / "tools" / "rule-stats.py")
rs = importlib.util.module_from_spec(rs_spec)
rs_spec.loader.exec_module(rs)  # type: ignore[union-attr]


class RuleHits(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-rh-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        isolate_state(self, self.tmp)

    def test_emit_logs_each_tag_and_block(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ug._emit({"decision": "block", "reason": "【驗證守門（hook）】失敗"}, "Stop")
            ug._emit({"hookSpecificOutput": {"additionalContext": "【用量守門（自動）】a\n【殘留程序（hook）】b"}}, "UserPromptSubmit")
            ug._emit({"hookSpecificOutput": {"additionalContext": "沒有標籤"}}, "PostToolUse")
        self.assertEqual(len(buf.getvalue().strip().splitlines()), 3)  # 三則都照常輸出
        lines = (self.tmp / "state" / "rule-hits.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].endswith("\tStop\t【驗證守門（hook）】\tblock"))
        rows = rs.read_hits(self.tmp / "state")
        res = {r["tag"]: r for r in rs.summarize(rows, ["【驗證守門（hook）】", "【磁碟清理（hook）】"])}
        self.assertEqual((res["【驗證守門（hook）】"]["count"], res["【驗證守門（hook）】"]["blocked"]), (1, 1))
        self.assertEqual(res["【磁碟清理（hook）】"]["count"], 0)
        self.assertFalse(res["【殘留程序（hook）】"]["inTable"])

    def test_known_tags_match_workflow_table(self):
        tags = rs.known_tags(REPO / "rules" / "workflow.md")
        for t in ("【驗證守門（hook）】", "【查證守門（hook）】", "【用量守門（自動）】"):
            self.assertIn(t, tags)

    def test_rotation_keeps_both_files_readable(self):
        st = self.tmp / "state"
        st.mkdir()
        (st / "rule-hits.log").write_text("2026-11-01T00:00:00\tStop\t【查證守門（hook）】\tblock\n" + "x" * (ug.RH_MAX_BYTES + 10), encoding="utf-8")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            ug._emit({"decision": "block", "reason": "【查證守門（hook）】"}, "Stop")
        self.assertTrue((st / "rule-hits.log.1").exists())
        self.assertEqual(sum(1 for r in rs.read_hits(st) if r[2] == "【查證守門（hook）】"), 2)


if __name__ == "__main__":
    unittest.main()
