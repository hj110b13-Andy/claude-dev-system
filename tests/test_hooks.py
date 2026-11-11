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

    def test_local_data_counts_as_source(self):
        """0.16.0：Stock-web 11/8～11/9 數字全來自本機回測報告仍被退回 3 次。"""
        q = "這個出場規則回測結果怎麼樣？"
        body = LONG + "年化 12.3%，2025 年回落 8%。"
        for tail in ("（docs/research/exit-2026-11-08.md）", "見 .cache/backtest/run-s1.log", "scripts/backtest/exitStrategy.ts 跑出",
                     "報告 exit-report.md", "（本站資料）", "以上為本機報告數字", "docs\\research\\x.md",
                     "已更新 PROGRESS.md；數字見 docs/backtest/2026-11-09a-confirm-list-result.md"):
            transcript(self.tp, [("user", q), ("assistant", body + tail)])
            self.assertIsNone(self.run_hook(), tail)
        # 反例：沒有本機路徑也沒有標記 → 仍退回；只提到資料夾名稱、網域不算
        # 0.16.2：只順口提到工作文件／設定檔不算出處（使用者 11/9 同意收緊：「改」）
        for tail in ("", "根據新聞報導。", "可參考 docs 資料夾。", "見 example.com 說明。", "版本 3.14 更新。",
                     "已更新 PROGRESS.md。", "規則寫在 CLAUDE.md 與 README.md", "見 docs/progress.md", "改了 package.json",
                     ".claude/skills/x/SKILL.md 已同步"):
            transcript(self.tp, [("user", q), ("assistant", body + tail)])
            out = self.run_hook()
            self.assertIsNotNone(out, tail)

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
        (self.proj / "scripts" / "backtest").mkdir(parents=True)
        es = self.proj / "scripts" / "backtest" / "exitStrategy.ts"
        es.write_text("x;" + chr(10) * 1000, encoding="utf-8")
        (self.proj / "scripts" / "once.ts").write_text("x;" + chr(10) * 900, encoding="utf-8")
        probs = ug.project_health(str(self.proj))
        big = [p for p in probs if "行數上限" in p]
        self.assertEqual(len(big), 1, probs)
        self.assertIn("exitStrategy.ts", big[0], "原因空白不算例外")
        self.assertIn("現在 1000 行", big[0], "報實際行數，不報索引裡的舊數字")
        self.assertNotIn("once.ts", big[0], "有寫原因的例外不提醒")
        self.assertIn("cds-modularize", big[0])
        # 0.16.0：Stock-web exitStrategy.ts 已拆成 26 行，索引沒重跑仍一直報 6588 行
        es.write_text("x;" + chr(10) * 26, encoding="utf-8")
        self.assertFalse(any("行數上限" in p for p in ug.project_health(str(self.proj))), "已不超標不報")
        es.unlink()
        self.assertFalse(any("行數上限" in p for p in ug.project_health(str(self.proj))), "檔案已不在不報")

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
            self.assertNotIn("過時條文", m, "沒寫死 pull --rebase 不提")
            ver.write_text("0.15.0", encoding="utf-8")
            self.assertIsNone(ug.align_msg(str(self.proj), "s5", mark_only=True), "init／audit 那則只記錄")
            self.assertIsNone(ug.align_msg(str(self.proj), "s6"))
            (self.proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"projectAutomation": {"alignOnUpdate": False}}), encoding="utf-8")
            ver.write_text("0.16.0", encoding="utf-8")
            self.assertIsNone(ug.align_msg(str(self.proj), "s7"), "專案可關閉")
        finally:
            ug.SYS_VERSION = saved

    def test_align_points_out_hardcoded_pull_rebase(self):
        """0.16.0：Stock-web CLAUDE.md 寫死「push 前 git pull --rebase」，11/8 rebase 把多個 merge 拆成直線、卡衝突。"""
        ver = self.tmp / "VERSION"
        saved = ug.SYS_VERSION
        ug.SYS_VERSION = str(ver)
        try:
            ver.write_text("0.16.0", encoding="utf-8")
            (self.proj / "CLAUDE.md").write_text("規則" + chr(10) + "- push 前 `git pull --rebase`；" + chr(10), encoding="utf-8")
            sk = self.proj / ".claude" / "skills" / "push-gate"
            sk.mkdir(parents=True)
            (sk / "SKILL.md").write_text("ok" + chr(10) + "git pull --rebase=merges 可以" + chr(10) + "git pull -r origin main" + chr(10), encoding="utf-8")
            m = ug.align_msg(str(self.proj), "s1")
            self.assertIn("CLAUDE.md:2", m)
            self.assertIn(".claude/skills/push-gate/SKILL.md:3", m)
            self.assertNotIn("SKILL.md:2", m, "--rebase=merges 是對的寫法")
            self.assertIn("--no-rebase", m)
        finally:
            ug.SYS_VERSION = saved

    def test_count_newer_skips_gitignored(self):
        import subprocess
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True)
        (self.proj / ".gitignore").write_text("docs/eval/" + chr(10) + "*.log" + chr(10), encoding="utf-8")
        (self.proj / "docs" / "eval").mkdir(parents=True)
        for i in range(30):
            (self.proj / "docs" / "eval" / f"r{i}.json").write_text("{}", encoding="utf-8")
            (self.proj / f"run{i}.log").write_text("x", encoding="utf-8")
        (self.proj / "src.py").write_text("x=1", encoding="utf-8")
        n, _ = ug._count_newer(str(self.proj), 0)
        self.assertEqual(n, 2, "只算 .gitignore 和 src.py，被排除的 60 個檔不算（與 project-scan --check 同一套）")

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

    SHARED_YES = ("git add -A", "cd x && git add -A", "git add . && git commit -m x", "git stash", "foo; git reset --hard HEAD~1",
                  "git add -A; git commit -m x", "echo hi\ngit add -A", "cat <<'EOF'\nx\nEOF\ngit stash")
    SHARED_NO = ("grep -n \"git add -A\" file", "echo 'git add -A'", "git commit -m \"不要用 git add -A\"",
                 "cat > x.py <<'EOF'\nre.search(r'git add (-A|--all|\\.)(\\s|$)', s)\ngit add -A\nEOF\npy -3 x.py",
                 "py -3 - <<EOF\nprint('git stash')\nEOF", "py -3 -c \"print('git stash')\"", "git log --grep=\"git reset --hard\"",
                 "git stash list", "git stash show -p", "git commit -m \"a; git stash\"")

    def test_shared_dir_git_only_when_executed(self):
        """只有真的被 shell 當指令執行才提醒；字樣出現在 grep／echo／commit 訊息／heredoc 內文／-c 字串不算。"""
        for cmd in self.SHARED_YES:
            self.assertTrue(any("共用工作目錄" in x for x in self.r("Bash", sid=cmd, command=cmd)), cmd)
        for cmd in self.SHARED_NO:
            self.assertEqual(self.r("Bash", sid=cmd, command=cmd), [], cmd)
        self.assertTrue(any("共用工作目錄" in x for x in self.r("PowerShell", sid="ps", command="git add -A; git commit -m x")))

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


class SessionUpkeep(unittest.TestCase):
    """0.16.0：殘留程序（C）、延後工作（E）、對話暫存（I）。全部節流、只提醒。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-upkeep-"))
        self._saved = (ug.HOME, ug.STATE_DIR, ug.PA_STATE, ug.CONFIG, ug.DEFERRED, dict(ug._TOOL_CACHE))
        ug.HOME = str(self.tmp / "home")
        ug.STATE_DIR = str(self.tmp / "state")
        ug.PA_STATE = str(self.tmp / "state" / "project-auto.json")
        ug.CONFIG = str(self.tmp / "no-global.json")
        ug.DEFERRED = str(self.tmp / "state" / "deferred-jobs.json")
        self.proj = self.tmp / "proj"
        (self.proj / ".claude").mkdir(parents=True)

    def tearDown(self):
        ug.HOME, ug.STATE_DIR, ug.PA_STATE, ug.CONFIG, ug.DEFERRED, cache = self._saved
        ug._TOOL_CACHE.clear()
        ug._TOOL_CACHE.update(cache)

    def test_proc_msg_throttled_once_per_pid(self):
        import types
        calls = []
        groups = [{"pid": 4242, "name": "bash.exe", "minutes": 300, "orphan": False, "children": [{"pid": 5, "name": "tail.exe", "cmd": "tail"}],
                   "cmd": "until [ $(grep -c FULL run-s1.log) -ge 13 ]; do sleep 10; done"}]

        def sl(mins, cwd):
            calls.append(mins)
            return list(groups)
        fake = types.SimpleNamespace(session_leftovers=sl, fmt=lambda g: "PID " + ",".join(str(x["pid"]) for x in g))
        ug._TOOL_CACHE["procs"] = fake
        st = {}
        m = ug.proc_msg(str(self.proj), "s1", st, now=1000.0)
        self.assertIn("殘留程序", m)
        self.assertIn("4242", m)
        self.assertIn("不要自動結束", m)
        self.assertEqual(calls, [60.0], "門檻預設 60 分鐘")
        self.assertIsNone(ug.proc_msg(str(self.proj), "s1", st, now=1000.0 + 60), "10 分鐘內不再查")
        self.assertEqual(len(calls), 1)
        self.assertIsNone(ug.proc_msg(str(self.proj), "s1", st, now=1000.0 + 700), "同一個 PID 只提醒一次")
        self.assertEqual(len(calls), 2)
        groups.append({**groups[0], "pid": 4343})
        self.assertIn("4343", ug.proc_msg(str(self.proj), "s1", st, now=1000.0 + 1400))
        (self.proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"procCheck": {"enabled": False}}), encoding="utf-8")
        self.assertIsNone(ug.proc_msg(str(self.proj), "s2", {}, now=5000.0), "可關閉")

    def test_deferred_hint_and_msg(self):
        import types
        self.assertEqual(ug._deferred_hint(), "", "清單空的不提")
        Path(ug.DEFERRED).parent.mkdir(parents=True, exist_ok=True)
        Path(ug.DEFERRED).write_text(json.dumps({"items": [{"id": 3, "project": "C:/p", "desc": "回測 s1", "rerun": "npm run bt"},
                                                           {"id": 4, "project": "C:/p", "desc": "build"}]}, ensure_ascii=False), encoding="utf-8")
        self.assertIn("延後清單有 2 項", ug._deferred_hint())
        free = [2.0]
        ug._TOOL_CACHE["resgate"] = types.SimpleNamespace(load_cfg=lambda cwd: {"minFreeMemGB": 3.0},
                                                          enough=lambda cfg: (free[0] >= 3.0, free[0], 3.0))
        st = {}
        self.assertIsNone(ug.deferred_msg(str(self.proj), "s1", st, now=10_000.0), "記憶體還不夠不提醒")
        free[0] = 4.0
        m = ug.deferred_msg(str(self.proj), "s1", st, now=10_000.0)
        self.assertIn("#3", m)
        self.assertIn("回測 s1", m)
        self.assertIn("跑一個再查一次", m)
        self.assertIsNone(ug.deferred_msg(str(self.proj), "s1", st, now=10_100.0), "10 分鐘內只一次")
        # 背景任務巡檢提醒也帶延後清單
        r = ug.tool_reminders({"tool_name": "Agent", "tool_input": {"prompt": "x"}, "session_id": "s9", "cwd": str(self.proj)})
        self.assertTrue(any("延後清單有 2 項" in x for x in r), r)

    def test_temp_msg_weekly(self):
        root = self.tmp / "claude"
        (root / "abc" / "s1").mkdir(parents=True)
        (root / "abc" / "s1" / "big.bin").write_bytes(b"x" * 5000)
        (self.proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"cleanup": {"claudeTempWarnGB": 0.000001, "remindDays": 7}}), encoding="utf-8")
        st = {}
        m = ug.temp_msg(str(self.proj), st, now=1_000_000.0, root=str(root))
        self.assertIn("cleanup.py --only temp", m)
        self.assertIn("只提醒", m)
        self.assertIsNone(ug.temp_msg(str(self.proj), st, now=1_000_000.0 + 2 * 86400, root=str(root)), "7 天內不再提醒")
        self.assertIsNotNone(ug.temp_msg(str(self.proj), st, now=1_000_000.0 + 8 * 86400, root=str(root)))
        (self.proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"cleanup": {"claudeTempWarnGB": 1}}), encoding="utf-8")
        self.assertIsNone(ug.temp_msg(str(self.proj), {}, now=1.0, root=str(root)), "沒超過不提醒")
        self.assertTrue((root / "abc" / "s1" / "big.bin").exists(), "只提醒不刪")


class SubagentBrief(unittest.TestCase):
    """0.21.0：agent 開工時補語言、工作目錄與分支、記憶路徑、自我核對清單（使用者：agent「不知道是不遵守還是不會看」）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = (ug.HOME, ug.CONFIG)
        ug.HOME = str(self.tmp / "home")
        ug.CONFIG = str(self.tmp / "home" / "claude-dev-system" / "config" / "dispatch-config.json")
        (self.tmp / "home").mkdir()
        (self.tmp / "home" / "settings.json").write_text(json.dumps({"language": "chinese"}), encoding="utf-8")
        self.proj = self.tmp / "projects" / "slug"
        (self.proj / "memory").mkdir(parents=True)
        (self.proj / "memory" / "MEMORY.md").write_text("- [x](x.md) — y", encoding="utf-8")
        self.cwd = self.tmp / "work"
        self.cwd.mkdir()

    def tearDown(self):
        ug.HOME, ug.CONFIG = self.old

    def payload(self, agent_type="general-purpose"):
        return {"hook_event_name": "SubagentStart", "cwd": str(self.cwd), "agent_type": agent_type,
                "transcript_path": str(self.proj / "s.jsonl")}

    def test_full_brief_has_language_cwd_memory_and_checklist(self):
        msg = ug.subagent_brief(self.payload())
        self.assertIn("chinese", msg)
        self.assertIn(str(self.cwd), msg)
        self.assertIn(str(self.proj / "memory"), msg)
        for key in ("web-quick.md", "resgate.py wait", "git branch --show-current", "背景程序"):
            self.assertIn(key, msg)

    def test_readonly_agents_get_language_only(self):
        msg = ug.subagent_brief(self.payload("Explore"))
        self.assertIn("chinese", msg)
        self.assertNotIn("工作目錄", msg)
        self.assertNotIn("長期記憶", msg)

    def test_no_memory_index_no_memory_line_and_can_disable(self):
        (self.proj / "memory" / "MEMORY.md").unlink()
        self.assertNotIn("長期記憶", ug.subagent_brief(self.payload()))
        (self.cwd / ".claude").mkdir()
        (self.cwd / ".claude" / "dispatch-config.json").write_text(json.dumps({"subagentBrief": {"enabled": False}}), encoding="utf-8")
        self.assertIsNone(ug.subagent_brief(self.payload()))

    def test_installer_registers_subagent_start(self):
        sys.path.insert(0, str(REPO / "installer"))
        try:
            from cds import settings_ops
        finally:
            sys.path.pop(0)
        self.assertIn(("SubagentStart", None), settings_ops.HOOK_SPECS)
        s, rec = settings_ops.add_hooks({}, "py -3 x.py # claude-dev-system")
        self.assertEqual(len(s["hooks"]["SubagentStart"]), 1)


class SubagentReportGuard(unittest.TestCase):
    """0.22.0：agent 交報告（PreToolUse SubagentHandback）時核對，不合格退回一次。"""
    ZH = "已完成稽核，三個模組都改好並通過測試，細節如下。" * 6

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = (ug.HOME, ug.CONFIG, ug.STATE_DIR, ug.SUB_GUARD_STATE)
        ug.HOME = str(self.tmp / "home")
        ug.CONFIG = str(self.tmp / "home" / "nope.json")
        ug.STATE_DIR = str(self.tmp / "state")
        ug.SUB_GUARD_STATE = str(self.tmp / "state" / "subagent-guard.json")
        (self.tmp / "home").mkdir()
        (self.tmp / "home" / "settings.json").write_text(json.dumps({"language": "chinese"}), encoding="utf-8")
        self.proj = self.tmp / "projects" / "slug"
        self.mem = self.proj / "memory"
        (self.proj / "sess" / "subagents").mkdir(parents=True)
        self.cwd = self.tmp / "work"
        self.cwd.mkdir()

    def tearDown(self):
        ug.HOME, ug.CONFIG, ug.STATE_DIR, ug.SUB_GUARD_STATE = self.old

    def agent(self, aid, prompt, uses):
        rows = [{"type": "user", "message": {"role": "user", "content": prompt}}]
        for name, inp in uses:
            rows.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": inp}]}})
        (self.proj / "sess" / "subagents" / f"agent-{aid}.jsonl").write_text(
            chr(10).join(json.dumps(r, ensure_ascii=False) for r in rows) + chr(10), encoding="utf-8")

    def call(self, aid, report, agent_type="general-purpose"):
        return ug.subagent_report_guard({"hook_event_name": "PreToolUse", "tool_name": "SubagentHandback", "tool_input": {"message": report},
                                         "agent_id": aid, "agent_type": agent_type, "session_id": "sess", "cwd": str(self.cwd),
                                         "transcript_path": str(self.proj / "sess.jsonl")})

    def reason(self, out):
        return out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_clean_report_passes(self):
        self.agent("a1", "整理文件", [("Read", {"file_path": "x.md"})])
        self.assertIsNone(self.call("a1", self.ZH))

    def test_english_report_blocked_once_then_allowed(self):
        self.agent("a2", "do it", [])
        out = self.call("a2", "All three modules were refactored and every test passes; details follow below. " * 4)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("語言", self.reason(out))
        self.assertIsNone(self.call("a2", "Still English but the second attempt must go through. " * 4), "同一個 agent 只擋一次")

    def test_numbers_without_any_source_blocked_and_path_passes(self):
        self.agent("a3", "跑回測", [])
        rep = self.ZH + "年化報酬 35.0%、最大回檔 37.2%、勝率 61%。"
        self.assertIn("出處", self.reason(self.call("a3", rep)))
        self.agent("a4", "跑回測", [])
        self.assertIsNone(self.call("a4", rep + "出處 docs/backtest/2026-11-10-result.md 第 12 行。"))

    def test_web_without_web_quick_blocked(self):
        self.agent("a5", "查文件", [("mcp__exa__web_search_exa", {"query": "x"})])
        self.assertIn("web-quick.md", self.reason(self.call("a5", self.ZH)))
        self.agent("a6", "查文件", [("Read", {"file_path": "C:/u/.claude/claude-dev-system/rules/web-quick.md"}), ("WebSearch", {"query": "x"})])
        self.assertIsNone(self.call("a6", self.ZH))

    def test_memory_bodies_unread_blocked_unless_read_or_declared(self):
        self.mem.mkdir()
        (self.mem / "MEMORY.md").write_text("- [a](a.md) — b", encoding="utf-8")
        self.agent("a7", "改程式", [("Read", {"file_path": str(self.mem / "MEMORY.md")})])
        self.assertIn("長期記憶", self.reason(self.call("a7", self.ZH)))
        self.agent("a8", "改程式", [("Read", {"file_path": str(self.mem / "a.md")})])
        self.assertIsNone(self.call("a8", self.ZH))
        self.agent("a9", "改程式", [])
        self.assertIsNone(self.call("a9", self.ZH + "記憶索引已看，無相關。"))

    def test_commit_without_branch_in_prompt_blocked(self):
        self.agent("b1", "改完 commit", [("Bash", {"command": "git add a.py && git commit -m x -- a.py"})])
        self.assertIn("分支", self.reason(self.call("b1", self.ZH)))
        self.agent("b2", "改完 commit 到分支 main", [("Bash", {"command": "git commit -m x -- a.py"})])
        self.assertIsNone(self.call("b2", self.ZH))

    def test_skips_readonly_agents_missing_transcript_and_disabled(self):
        self.assertIsNone(self.call("c1", "All English report from the explore agent, long enough to trip the check. " * 3, "Explore"))
        self.assertIsNone(self.call("c2", self.ZH), "讀不到紀錄只查報告本身，中文報告放行")
        (self.cwd / ".claude").mkdir()
        (self.cwd / ".claude" / "dispatch-config.json").write_text(json.dumps({"subagentBrief": {"guard": False}}), encoding="utf-8")
        self.assertIsNone(self.call("c3", "English only report that would otherwise be blocked by the guard for sure. " * 3))
        self.assertIn("交報告", ug.subagent_brief({"cwd": str(self.tmp), "agent_type": "general-purpose"}))
        self.assertNotIn("不合格退回一次", ug.subagent_brief({"cwd": str(self.cwd), "agent_type": "general-purpose"}))

    def stop(self, aid, last, agent_type="general-purpose", active=False, meta=True):
        tp = self.proj / "sess" / "subagents" / f"agent-{aid}.jsonl"
        if meta and tp.exists():
            Path(str(tp)[:-6] + ".meta.json").write_text("{}", encoding="utf-8")
        return ug.subagent_stop_guard({"hook_event_name": "SubagentStop", "stop_hook_active": active, "agent_id": aid, "agent_type": agent_type,
                                       "session_id": "sess", "cwd": str(self.cwd), "transcript_path": str(self.proj / "sess.jsonl"),
                                       "agent_transcript_path": str(tp), "last_assistant_message": last})

    def test_stop_fallback_blocks_plain_text_report_once(self):
        en = "All three modules were refactored and every test passes; details follow below. " * 4
        self.agent("d1", "do it", [("Read", {"file_path": "x.md"})])
        out = self.stop("d1", en)
        self.assertEqual(out["decision"], "block")
        self.assertIn("最後一則訊息", out["reason"])
        self.assertIsNone(self.stop("d1", en), "同一個 agent 只擋一次")

    def test_stop_fallback_skips_handback_internal_forks_and_active(self):
        en = "All three modules were refactored and every test passes; details follow below. " * 4
        self.agent("d2", "do it", [("SubagentHandback", {"message": "x"})])
        self.assertIsNone(self.stop("d2", en), "已經用 SubagentHandback 交過，在那裡核對")
        self.agent("d3", "do it", [])
        self.assertIsNone(self.stop("d3", en, agent_type=""), "內部分支 agent_type 是空字串")
        self.assertIsNone(self.stop("d3", en, active=True))
        self.agent("d4", "do it", [])
        self.assertIsNone(self.stop("d4", en, meta=False), "沒有 .meta.json 的不是真的派出的 agent")
        self.assertIsNone(self.stop("d5", en), "紀錄檔不存在")

    def test_installer_registers_pretooluse_on_handback(self):
        sys.path.insert(0, str(REPO / "installer"))
        try:
            from cds import settings_ops
        finally:
            sys.path.pop(0)
        self.assertIn(("PreToolUse", "SubagentHandback"), settings_ops.HOOK_SPECS)
        s, _ = settings_ops.add_hooks({}, "py -3 x.py # claude-dev-system")
        self.assertEqual(s["hooks"]["PreToolUse"][0]["matcher"], "SubagentHandback")
        self.assertIn(("SubagentStop", None), settings_ops.HOOK_SPECS)


class RecoGuard(unittest.TestCase):
    """0.19.0：建議沒標已查證／未查證要退回；「不含待查證事實」不能蓋過研究結論。"""
    LONG = "說明" * 120

    def test_reco_needs_verification_labels(self):
        self.assertIsNotNone(ug.sg_reco_judge(self.LONG + "我的建議：改用時間序列動能、市況切換模型。"))
        self.assertIsNone(ug.sg_reco_judge(self.LONG + "我的建議：改用時間序列動能（已查證：MOP 2012）、市況切換模型（未查證）。"))
        self.assertIsNone(ug.sg_reco_judge(self.LONG + "已推送部署，測試全過。"))
        self.assertIsNone(ug.sg_reco_judge(self.LONG + "我的建議```code```"), "程式工作不擋")

    def test_skip_mark_not_for_research_claims(self):
        q = "這樣有用嗎？"
        self.assertIsNotNone(ug.sg_judge(q, self.LONG + "研究顯示年化多 2.5%。〔不含待查證事實〕"))
        self.assertIsNotNone(ug.sg_judge(q, self.LONG + "2008 年跌了 32%。〔不含待查證事實〕"))
        self.assertIsNone(ug.sg_judge(q, self.LONG + "我算的：多 2.5%。〔不含待查證事實〕"))
        self.assertIsNone(ug.sg_judge(q, self.LONG + "研究顯示多 2.5%。來源：https://x.y"))
