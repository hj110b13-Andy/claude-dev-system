"""hooks/usage_guard.py 的查證守門（Stop）：假逐字稿，不打網路。"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("usage_guard", REPO / "hooks" / "usage_guard.py")
ug = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ug)  # type: ignore[union-attr]


def transcript(path: Path, turns):
    lines = []
    for role, text in turns:
        if role == "user":
            lines.append({"type": "user", "message": {"role": "user", "content": text}})
        elif role == "tool":
            lines.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": text}]}})
        else:
            lines.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")


LONG = "AI 會出現幻覺的原因有三層。" * 12


class SourceGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-hook-"))
        self.tp = self.tmp / "t.jsonl"
        # 不可寫到使用者真實的 ~/.claude/state（0.11.8～0.11.16 的測試把「AI 幻覺的原因是什麼？」寫進了真實 source-guard.log）
        self._saved = (ug.STATE_DIR, ug.PA_STATE)
        ug.STATE_DIR = str(self.tmp / "state")
        ug.PA_STATE = str(self.tmp / "state" / "project-auto.json")

    def tearDown(self):
        ug.STATE_DIR, ug.PA_STATE = self._saved

    def run_hook(self, active=False):
        return ug.source_guard({"hook_event_name": "Stop", "transcript_path": str(self.tp), "stop_hook_active": active})

    def test_blocks_question_with_numbers_and_no_source(self):
        transcript(self.tp, [("user", "AI 幻覺的原因是什麼？"), ("tool", "x"),
                             ("assistant", LONG + "2024 年 Google AI 摘要建議披薩加膠水，OpenAI 2025 年發表論文。")])
        out = self.run_hook()
        self.assertIsNotNone(out)
        self.assertEqual(out["decision"], "block")
        self.assertIn("來源", out["reason"])
        self.assertIsNone(self.run_hook(active=True), "stop_hook_active 不再擋，避免迴圈")

    def test_passes_with_source_or_marker_or_code_or_statement(self):
        transcript(self.tp, [("user", "AI 幻覺的原因是什麼？"), ("assistant", LONG + "2024 年事件。來源：https://www.bbc.com/x（2026-11-02 查）")])
        self.assertIsNone(self.run_hook(), "有來源段放行")
        transcript(self.tp, [("user", "AI 幻覺的原因是什麼？"), ("assistant", LONG + "例如 2024 年。〔不含待查證事實〕")])
        self.assertIsNone(self.run_hook(), "標記放行")
        transcript(self.tp, [("user", "幫我看這段怎麼改？"), ("assistant", LONG + "改了 2024 年的欄位：```py\nx=1\n```")])
        self.assertIsNone(self.run_hook(), "程式碼區塊不擋")
        transcript(self.tp, [("user", "把報告整理成三段"), ("assistant", LONG + "2024 年營收 120 億元。")])
        self.assertIsNone(self.run_hook(), "不是問句不擋")
        transcript(self.tp, [("user", "幾點開門？"), ("assistant", "早上 9 點，來源見官網")])
        self.assertIsNone(self.run_hook(), "短回覆不擋")
        transcript(self.tp, [("user", "AI 幻覺的原因是什麼？"), ("assistant", LONG + "它只是在接著寫最像的字。")])
        self.assertIsNone(self.run_hook(), "沒有數字不擋")

    def test_last_turn_only_and_disabled(self):
        transcript(self.tp, [("user", "台北 101 幾公尺？"), ("assistant", LONG + "508 公尺。"),
                             ("user", "謝謝，再整理一下重點"), ("assistant", LONG + "重點是 508 公尺。")])
        self.assertIsNone(self.run_hook(), "只看最後一輪，最後一句不是問句")
        old = ug.SG_LOCAL
        ug.SG_LOCAL = str(self.tmp / "local.json")
        (self.tmp / "local.json").write_text(json.dumps({"sourceGuard": False}), encoding="utf-8")
        try:
            transcript(self.tp, [("user", "台北 101 幾公尺？"), ("assistant", LONG + "508 公尺。")])
            self.assertIsNone(self.run_hook(), "local.json sourceGuard=false 關閉")
        finally:
            ug.SG_LOCAL = old
        self.assertEqual(ug.sg_judge(None, None), None)


class Health(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-health-"))
        self._saved = (ug.STATE_DIR, ug.PA_STATE, ug.CONFIG)
        ug.STATE_DIR = str(self.tmp / "state")
        ug.PA_STATE = str(self.tmp / "state" / "project-auto.json")
        ug.CONFIG = str(self.tmp / "no-global.json")
        self.proj = self.tmp / "proj"
        (self.proj / ".claude").mkdir(parents=True)
        (self.proj / ".git").mkdir()

    def tearDown(self):
        ug.STATE_DIR, ug.PA_STATE, ug.CONFIG = self._saved

    def test_stale_index_big_docs_and_daily_once(self):
        import os
        import time
        idx = self.proj / ".claude" / "project-scan.json"
        idx.write_text(json.dumps({"version": 2, "problems": []}), encoding="utf-8")
        old = time.time() - 3600
        os.utime(idx, (old, old))
        for i in range(25):
            (self.proj / f"m{i}.py").write_text("x=1", encoding="utf-8")
        (self.proj / "CLAUDE.md").write_text("規則" + chr(10) * 200, encoding="utf-8")
        (self.proj / "PROGRESS.md").write_text("x" + chr(10) * 650, encoding="utf-8")
        probs = ug.project_health(str(self.proj))
        self.assertEqual(len(probs), 3, probs)
        self.assertIn("改過 2", probs[0])
        m = ug.health_msg(str(self.proj))
        self.assertIn("專案健康檢查", m)
        self.assertIsNone(ug.health_msg(str(self.proj)), "同一天只提醒一次")
        self.assertIn("專案健康檢查", ug.health_msg(str(self.proj), force=True), "壓縮後每次都看")
        (self.proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"projectAutomation": {"claudeMdMaxLines": 0, "staleFiles": 0, "progressMaxLines": 0}}), encoding="utf-8")
        self.assertEqual(ug.project_health(str(self.proj)), [], "專案可改門檻或設 0 關閉；剩 KB 檢查，200 行 < 20 KB")

    def test_big_files_from_index_with_exceptions(self):
        idx = self.proj / ".claude" / "project-scan.json"
        idx.write_text(json.dumps({"version": 1, "problems": []}), encoding="utf-8")
        probs = ug.project_health(str(self.proj))
        self.assertTrue(any("舊版掃描" in p for p in probs), probs)
        idx.write_text(json.dumps({"version": 2, "maxLines": 800, "problems": [
            {"kind": "big-file", "file": "scripts/backtest/exitStrategy.ts", "detail": "6588 行 > 800（腳本）"},
            {"kind": "big-file", "file": "scripts/once.ts", "detail": "900 行 > 800（腳本）"},
            {"kind": "cycle", "files": ["a", "b"], "detail": "x"}]}), encoding="utf-8")
        (self.proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"projectAutomation": {"bigFileExceptions": {
            "scripts/once.ts": "一次性回填，不再修改", "scripts/backtest/exitStrategy.ts": " "}}}), encoding="utf-8")
        probs = ug.project_health(str(self.proj))
        big = [p for p in probs if "行數上限" in p]
        self.assertEqual(len(big), 1, probs)
        self.assertIn("exitStrategy.ts", big[0], "原因空白不算例外")
        self.assertNotIn("once.ts", big[0], "有寫原因的例外不提醒")
        self.assertIn("cds-modularize", big[0])

    def test_progress_kb_limit_and_per_session(self):
        # Stock-web 2026-11-03：PROGRESS.md 510 行卻 355 KB，只看行數抓不到
        (self.proj / "PROGRESS.md").write_text(("長" * 900 + chr(10)) * 50, encoding="utf-8")
        probs = ug.project_health(str(self.proj))
        self.assertEqual(len(probs), 1, probs)
        self.assertIn("KB（上限 100 KB）", probs[0])
        self.assertIn("專案健康檢查", ug.health_msg(str(self.proj), session_id="old"))
        self.assertIsNone(ug.health_msg(str(self.proj), session_id="old"), "同一場對話當天只一次")
        self.assertIn("專案健康檢查", ug.health_msg(str(self.proj), session_id="new"), "同一天新開的對話也要收到")

    def test_align_on_minor_version_change(self):
        ver = self.tmp / "VERSION"
        saved = ug.SYS_VERSION
        ug.SYS_VERSION = str(ver)
        try:
            ver.write_text("0.13.0", encoding="utf-8")
            self.assertIsNone(ug.align_msg(str(self.proj), "s1"), "沒有 CLAUDE.md 不對照（交給 init）")
            (self.proj / "CLAUDE.md").write_text("規則", encoding="utf-8")
            m = ug.align_msg(str(self.proj), "s1")
            self.assertIn("全域系統對照", m)
            self.assertIn("還沒對照過", m)
            self.assertIsNone(ug.align_msg(str(self.proj), "s2"), "同一版只一次")
            ver.write_text("0.13.4", encoding="utf-8")
            self.assertIsNone(ug.align_msg(str(self.proj), "s3"), "修訂號不觸發")
            ver.write_text("0.14.0", encoding="utf-8")
            m = ug.align_msg(str(self.proj), "s4")
            self.assertIn("從 0.13.0 更新到 0.14.0", m)
            ver.write_text("0.15.0", encoding="utf-8")
            self.assertIsNone(ug.align_msg(str(self.proj), "s5", mark_only=True), "init／audit 那則只記錄")
            self.assertIsNone(ug.align_msg(str(self.proj), "s6"))
            (self.proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"projectAutomation": {"alignOnUpdate": False}}), encoding="utf-8")
            ver.write_text("0.16.0", encoding="utf-8")
            self.assertIsNone(ug.align_msg(str(self.proj), "s7"), "專案可關閉")
        finally:
            ug.SYS_VERSION = saved

    def test_compact_reinjects_and_suggests_new_session(self):
        msgs = [ug.compact_msg(str(self.proj), "sess-1") for _ in range(3)]
        self.assertTrue(all("壓縮後重新開工" in m for m in msgs))
        self.assertNotIn("建議開新對話", msgs[1])
        self.assertIn("已被壓縮 3 次", msgs[2])
        self.assertIn("壓縮後重新開工", ug.compact_msg(None, None), "沒有 cwd 也給開工清單")


class ToolReminders(unittest.TestCase):
    """0.14.0：使用者「這五項都做」——改安裝副本、背景任務巡檢、波及範圍、共用目錄 git、驗證 skill。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-remind-"))
        self._saved = (ug.HOME, ug.STATE_DIR, ug.PA_STATE, ug.CONFIG)
        ug.HOME = str(self.tmp / "home")
        ug.STATE_DIR = str(self.tmp / "state")
        ug.PA_STATE = str(self.tmp / "state" / "project-auto.json")
        ug.CONFIG = str(self.tmp / "no-global.json")
        self.proj = self.tmp / "proj"
        (self.proj / ".claude").mkdir(parents=True)
        (self.proj / ".git").mkdir()

    def tearDown(self):
        ug.HOME, ug.STATE_DIR, ug.PA_STATE, ug.CONFIG = self._saved

    def r(self, name, sid="s1", **ti):
        return ug.tool_reminders({"tool_name": name, "tool_input": ti, "session_id": sid, "cwd": str(self.proj)})

    def test_installed_copy(self):
        hook = Path(ug.HOME) / "claude-dev-system" / "hooks" / "usage_guard.py"
        m = self.r("Edit", file_path=str(hook))
        self.assertTrue(any("改到安裝副本" in x for x in m), m)
        self.assertEqual(self.r("Edit", file_path=str(hook)), [], "同一場對話同一檔只一次")
        cfg = Path(ug.HOME) / "claude-dev-system" / "config" / "dispatch-config.json"
        self.assertEqual(self.r("Edit", file_path=str(cfg)), [], "設定檔本來就給使用者改")
        sk = Path(ug.HOME) / "skills" / "cds-x"
        sk.mkdir(parents=True)
        self.assertEqual(self.r("Write", file_path=str(sk / "SKILL.md")), [], "不是本工具裝的 skill 不管")
        (sk / ".claude-dev-system").write_text("x", encoding="utf-8")
        self.assertTrue(any("安裝副本" in x for x in self.r("Write", file_path=str(sk / "SKILL.md"))))

    def test_background_task_check(self):
        self.assertEqual(self.r("Bash", command="ls"), [], "前景指令不提醒")
        m = self.r("Bash", command="npm test", run_in_background=True)
        self.assertTrue(any("CronCreate" in x and "15 分鐘" in x for x in m), m)
        self.assertEqual(self.r("Agent", prompt="x"), [], "同一場對話只一次")
        self.assertTrue(self.r("Agent", sid="s2", prompt="x"), "別場對話照提醒")
        (self.proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"taskCheck": {"enabled": False}}), encoding="utf-8")
        self.assertEqual(self.r("Agent", sid="s3", prompt="x"), [], "taskCheck 關掉不提醒")

    def test_background_task_auto_moved_and_each_task(self):
        """0.14.1：逾時自動移到背景也提醒；每個任務各一次（使用者「全域15分鐘的巡查呢？」）"""
        def bash(sid, resp, **ti):
            return ug.tool_reminders({"tool_name": "Bash", "tool_input": {"command": "npm test", **ti}, "tool_response": resp, "session_id": sid, "cwd": str(self.proj)})
        moved = {"stdout": "", "stderr": "", "backgroundTaskId": "abc123", "timedOutAfterMs": 120000}
        self.assertTrue(any("CronCreate" in x for x in bash("t1", moved)), "沒有 run_in_background，只有結果顯示移到背景")
        self.assertEqual(bash("t1", moved), [], "同一任務只一次")
        self.assertTrue(any("CronCreate" in x for x in bash("t1", {"backgroundTaskId": "def456"}, run_in_background=True)), "排程可能已刪：新任務要再提醒")
        self.assertTrue(any("CronCreate" in x for x in bash("t2", "Command was moved to the background (ID: xyz789). Output is being written")), "文字格式也認得")
        self.assertEqual(bash("t3", {"stdout": "ok"}), [], "一般前景指令不提醒")
        self.assertEqual(bash("t3", "ok"), [], "文字結果也不誤判")

    def test_blast_radius_from_index(self):
        (self.proj / ".claude" / "project-scan.json").write_text(json.dumps({"version": 2, "mostDepended": [["src/lib/cache.ts", 72], ["src/a.ts", 2]]}), encoding="utf-8")
        m = self.r("Edit", file_path=str(self.proj / "src" / "lib" / "cache.ts"))
        self.assertTrue(any("cds-blast-radius" in x and "72" in x for x in m), m)
        self.assertEqual(self.r("Edit", file_path=str(self.proj / "src" / "lib" / "cache.ts")), [])
        self.assertEqual(self.r("Edit", file_path=str(self.proj / "src" / "a.ts")), [], "引用 < 3 不提醒")

    def test_shared_dir_git(self):
        for cmd in ("git add -A", "git add .", "git stash", "git reset --hard HEAD", "git clean -fd", "cd x && git add --all && git commit -m y"):
            self.assertTrue(any("共用工作目錄" in x for x in self.r("Bash", sid=cmd, command=cmd)), cmd)
        for cmd in ("git add src/a.ts", "git stash list", "git status", "git add ./src/a.ts", "git commit -- a.py"):
            self.assertEqual(self.r("Bash", sid=cmd, command=cmd), [], cmd)

    def test_main_still_reminds_when_usage_fetch_fails(self):
        import io
        import contextlib
        saved = (ug.fetch, ug.USAGE, ug.BOARD_FILE, sys.stdin)
        ug.fetch = lambda: None  # 離線／憑證過期
        ug.USAGE = str(self.tmp / "state" / "usage.json")
        ug.BOARD_FILE = str(self.tmp / "state" / "board.md")
        sys.stdin = io.StringIO(json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "git add -A"},
                                            "session_id": "m1", "cwd": str(self.proj)}))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                ug.main()
        finally:
            ug.fetch, ug.USAGE, ug.BOARD_FILE, sys.stdin = saved
        self.assertIn("hookSpecificOutput", buf.getvalue(), "讀不到用量也要照常注入其他提醒")

    def test_verify_skill_health(self):
        self.assertFalse(ug._needs_verify_skill(str(self.proj)), "沒有畫面不提醒")
        (self.proj / "package.json").write_text(json.dumps({"scripts": {"dev": "next dev"}}), encoding="utf-8")
        self.assertTrue(any("cds-verify-app" in p for p in ug.project_health(str(self.proj))))
        (self.proj / ".claude" / "skills" / "verify-proj").mkdir(parents=True)
        (self.proj / ".claude" / "skills" / "verify-proj" / "SKILL.md").write_text("x", encoding="utf-8")
        self.assertFalse(ug._needs_verify_skill(str(self.proj)))


if __name__ == "__main__":
    unittest.main()
