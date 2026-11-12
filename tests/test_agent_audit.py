"""tools/agent-audit.py：假的對話紀錄（造法同 test_hooks.SubagentReportGuard.agent）。"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("agent_audit", ROOT / "tools" / "agent-audit.py")
aa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aa)

ZH = "已完成稽核，三個模組都改好並通過測試，細節如下。" * 6
EN = "All three modules were refactored and every test passes; details follow below. " * 4
DENY = "PreToolUse:SubagentHandback hook error: 【報告守門（hook）】這份報告還不能交，有 1 項不合格：1. x"


def use(name, **inp):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": inp}]}}


def text(t):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}}


def deny():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": DENY, "is_error": True}]}}


BRIEF = {"type": "attachment", "attachment": {"type": "hook_additional_context", "content": ["【派工補充（hook）】你是被派出的 agent。"]}}


class AgentAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = (aa.PROJECTS, aa.GUARD_LOG)
        aa.PROJECTS = str(self.tmp / "projects")
        aa.GUARD_LOG = str(self.tmp / "source-guard.log")
        self.work = self.tmp / "My Proj"
        self.work.mkdir()
        self.pdir = Path(aa.PROJECTS) / aa.slug_of(str(self.work))
        self.sub = self.pdir / "sess1" / "subagents"
        self.sub.mkdir(parents=True)

    def tearDown(self):
        aa.PROJECTS, aa.GUARD_LOG = self.old

    def agent(self, aid, rows, model="sonnet"):
        rows = [{"type": "user", "message": {"role": "user", "content": "派工"}}] + rows
        (self.sub / f"agent-{aid}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        (self.sub / f"agent-{aid}.meta.json").write_text(
            json.dumps({"agentType": "general-purpose", "description": "d-" + aid, "model": model, "effort": "medium"}), encoding="utf-8")

    def run_cli(self, *args):
        buf = io.StringIO()
        old = os.getcwd()
        import sys
        argv = sys.argv
        sys.argv = ["agent-audit.py", str(self.work), *args]
        try:
            with contextlib.redirect_stdout(buf):
                rc = aa.main()
        finally:
            sys.argv = argv
            os.chdir(old)
        return rc, buf.getvalue()

    def build(self):
        self.agent("a1", [BRIEF, use("Read", file_path="C:/x/memory/foo.md"),
                          use("mcp__exa__web_search_exa", query="q"), use("SubagentHandback", message=ZH)], "opus")
        self.agent("a2", [use("Read", file_path="C:/u/rules/web-quick.md"), use("WebSearch", query="q"),
                          use("PowerShell", command="git add -A"), use("PowerShell", command="git commit -m x"),
                          text("running tests ok " * 5), use("SubagentHandback", message=ZH + "分支 master")])
        self.agent("a3", [use("WebFetch", url="u"), use("Bash", command="py -3 -m unittest discover -s tests"),
                          use("Bash", command="git stash"), use("SubagentHandback", message=EN)])
        self.agent("a4", [use("Bash", command="py -3 resgate.py wait"), use("Bash", command="npm run build"),
                          use("SubagentHandback", message="第一次"), deny(), use("SubagentHandback", message=ZH)])
        self.agent("a5", [use("SubagentHandback", message="第一次"), deny()])
        # 壞行與空檔
        with open(self.sub / "agent-a5.jsonl", "a", encoding="utf-8") as f:
            f.write("{壞掉的行\n\n")
        (self.tmp / "source-guard.log").write_text(
            "2026-11-11T09:29:34 block-agent a5 1 項：x\n2026-11-11T09:30:00 block-agent zzz 1 項：y\n", encoding="utf-8")

    def summary(self):
        rc, out = self.run_cli("--json")
        self.assertEqual(rc, 0)
        return json.loads(out)

    def test_heavy_only_when_executed(self):
        # 0.25.1：讀 backtest 資料夾裡的檔不是重型工作；真的執行才算，且與閘門寫在同一個指令也算
        import importlib.util
        spec = importlib.util.spec_from_file_location("agent_audit_mod", Path(__file__).resolve().parents[1] / "tools" / "agent-audit.py")
        aa = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aa)
        ug = aa.load_guard()
        for cmd in ("ls scripts/backtest/ | grep cool", "cat scripts/backtest/a.ts | head -200", 'grep -n "x" docs/backtest/r.md',
                    "cd repo && sed -n 1,80p scripts/backtest/signal.ts", 'git commit -m "跑完 backtest" -- a.md'):
            self.assertFalse(aa.is_heavy(cmd, ug), cmd)
        for cmd in ("cd repo && npx tsx scripts/backtest/run.ts", "npm run build", "CI=1 npx.cmd vitest run a.test.ts",
                    "py -3 -m unittest discover -s tests", 'py -3 resgate.py run --desc "x" -- npx.cmd vitest run'):
            self.assertTrue(aa.is_heavy(cmd, ug), cmd)

    def test_denominators(self):
        self.build()
        s = self.summary()["summary"]
        self.assertEqual(s["agents"], 5)
        self.assertEqual(s["models"], {"opus": 1, "sonnet": 4})
        self.assertEqual(s["brief"], [1, 5])
        self.assertEqual(s["memory_read"], [1, 5])
        self.assertEqual(s["web"], [3, 5])  # a1 a2 a3
        self.assertEqual(s["web_quick_first"], [1, 3])  # 母數是有上網者
        self.assertEqual(s["commit"], [1, 5])
        self.assertEqual(s["commit_branch_in_report"], [1, 1])
        self.assertEqual(s["heavy"], [2, 5])  # a3、a4；a4 的 resgate 本身不算重型
        self.assertEqual(s["heavy_with_gate"], [1, 2])
        self.assertEqual(s["git_add_all"], [1, 5])
        self.assertEqual(s["stash_or_reset"], [1, 5])
        self.assertEqual(s["final_in_user_language"][1], 5)
        self.assertEqual(s["final_in_user_language"][0], 4)  # a3 英文
        self.assertEqual(s["mid_text_english"], [1, 1])  # a2 的英文中途文字

    def test_denied_detection_and_resubmit(self):
        self.build()
        s = self.summary()["summary"]
        self.assertEqual(s["denied_transcript"], [2, 5])  # a4 a5
        self.assertEqual(s["denied_log"], [1, 5])  # a5；zzz 不在這批
        self.assertEqual(s["denied_union"], [2, 5])
        self.assertEqual(s["resubmitted_after_deny"], [1, 2])  # a4 補交、a5 沒有

    def test_detail_event_order(self):
        self.build()
        rc, out = self.run_cli("--detail")
        self.assertEqual(rc, 0)
        a4 = out[out.index("== a4"):out.index("== a5")]
        order = [a4.index("resgate"), a4.index("重型工作"), a4.index("交報告"), a4.rindex("交報告")]
        self.assertEqual(order, sorted(order))
        self.assertIn("交報告", a4[order[2] + 3:])
        self.assertLess(out.index("讀 web-quick"), out.index("git add -A"))
        self.assertLess(out.index("git add -A"), out.index("git commit"))

    def _row(self, aid):
        return next(r for r in self.summary()["agents"] if r["id"] == aid)

    def test_gate_needs_real_resgate_execution_before_heavy(self):
        # TB-13：原本指令裡出現 resgate 字樣（grep、cat）就算有過閘門
        self.agent("g1", [use("Bash", command="grep -n resgate README.md"), use("Bash", command="npm test"), use("SubagentHandback", message=ZH)])
        self.agent("g2", [use("Bash", command='py -3 "C:/u/.claude/claude-dev-system/tools/resgate.py" run --desc t -- npm test'), use("SubagentHandback", message=ZH)])
        self.agent("g3", [use("Bash", command="cd x && py -3 resgate.py wait --desc t"), use("Bash", command="npm run build"), use("SubagentHandback", message=ZH)])
        self.agent("g4", [use("Bash", command="npm run build"), use("Bash", command="py -3 resgate.py wait"), use("SubagentHandback", message=ZH)])
        self.agent("g5", [use("Bash", command='echo "py -3 resgate.py run" && npm test'), use("SubagentHandback", message=ZH)])
        for aid, heavy, gate in (("g1", True, False), ("g2", True, True), ("g3", True, True), ("g4", True, False), ("g5", True, False)):
            r = self._row(aid)
            self.assertEqual((r["heavy"], r["gate"]), (heavy, gate), aid)
        ev = {r["id"]: r["events"] for r in self.summary()["agents"]}  # JSON 的 events 是壓縮過的文字清單
        self.assertNotIn("resgate", ev["g1"], "grep resgate 不是閘門事件")
        self.assertIn("resgate", ev["g2"])

    def test_web_quick_must_be_read_before_first_web_tool(self):
        # TB-13：原本先上網、後讀 web-quick 也判成「上網前先讀」
        self.agent("w1", [use("WebSearch", query="q"), use("Read", file_path="C:/x/rules/web-quick.md"), use("SubagentHandback", message=ZH)])
        self.agent("w2", [use("Read", file_path="C:/x/rules/web-quick.md"), use("WebSearch", query="q"), use("SubagentHandback", message=ZH)])
        self.agent("w3", [use("Bash", command="cat ~/.claude/claude-dev-system/rules/web-quick.md"), use("WebFetch", url="u"), use("SubagentHandback", message=ZH)])
        self.agent("w4", [use("Read", file_path="C:/x/rules/web-quick.md"), use("SubagentHandback", message=ZH)])
        self.assertEqual([self._row(a)["web_quick"] for a in ("w1", "w2", "w3", "w4")], [False, True, True, False])
        s = self.summary()["summary"]
        self.assertEqual((s["web"], s["web_quick_first"]), ([3, 4], [2, 3]))

    def test_truncated_last_line_does_not_lose_web_and_memory(self):
        # TB-14 在稽核這一側的影響：紀錄最後一行寫到一半（agent 還在跑），_sub_scan 以嚴格 UTF-8 讀會整個回 None
        self.agent("t1", [use("Read", file_path="C:/p/memory/foo.md"), use("WebSearch", query="q"), use("SubagentHandback", message=ZH)])
        with open(self.sub / "agent-t1.jsonl", "ab") as f:
            f.write('{"type":"assistant","x":"中'.encode("utf-8")[:-1])
        r = self._row("t1")
        self.assertTrue(r["web"])
        self.assertTrue(r["mem"])

    def test_model_family_unified(self):
        # TB-15：meta 寫 haiku、對話紀錄寫 claude-haiku-5-5 原本被拆成兩類
        self.agent("m1", [use("SubagentHandback", message=ZH)], "haiku")
        rows = [{"type": "user", "message": {"role": "user", "content": "派工"}},
                {"type": "assistant", "message": {"role": "assistant", "model": "claude-haiku-5-5", "content": [
                    {"type": "tool_use", "name": "SubagentHandback", "input": {"message": ZH}}]}}]
        (self.sub / "agent-m2.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        self.assertEqual(self.summary()["summary"]["models"], {"haiku": 2})
        self.assertEqual(self._row("m2")["model_id"], "claude-haiku-5-5")
        self.assertEqual([aa.model_family(x) for x in ("claude-sonnet-4-5-20250929", "opus", "claude-3-5-haiku-20241022", None, "gpt-x")],
                         ["sonnet", "opus", "haiku", "?", "gpt"])

    def test_since_selects_sessions_by_mtime(self):
        self.build()
        old_t = 946684800  # 2000-01-01
        for f in self.sub.glob("agent-*"):
            os.utime(f, (old_t, old_t))
        rc, out = self.run_cli("--since", "2020-01-01")
        self.assertEqual(rc, 0)
        self.assertIn("沒有符合條件", out)
        rc, out = self.run_cli("--since", "1999-12-31")
        self.assertIn("agent 總數：5", out)
        rc, out = self.run_cli("--since", "2026/11/11")
        self.assertEqual(rc, 2)
        self.assertIn("YYYY-MM-DD", out)

    def test_title_uses_guard_constant_not_hardcoded(self):
        import inspect
        self.assertNotIn("0.3", inspect.getsource(aa.print_summary))
        self.build()
        rc, out = self.run_cli()
        self.assertIn(f"中文比例≥{aa.load_guard().SUB_LANG_MIN_RATIO}", out)

    def test_no_project_and_no_agents(self):
        import sys
        argv = sys.argv
        sys.argv = ["agent-audit.py", str(self.tmp / "不存在的專案")]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = aa.main()
        finally:
            sys.argv = argv
        self.assertEqual(rc, 0)
        self.assertIn("找不到", buf.getvalue())
        rc, out = self.run_cli()  # 專案存在但沒有任何 agent 紀錄
        self.assertEqual(rc, 0)
        self.assertIn("沒有符合條件的 agent", out)

    def test_bad_lines_do_not_fail(self):
        self.agent("b1", [use("SubagentHandback", message=ZH)])
        with open(self.sub / "agent-b1.jsonl", "a", encoding="utf-8") as f:
            f.write("not json\n[1,2]\n")
        (self.sub / "agent-b2.jsonl").write_text("", encoding="utf-8")  # 空檔、沒有 meta
        s = self.summary()["summary"]
        self.assertEqual(s["agents"], 2)

    def test_session_selection(self):
        self.build()
        rc, out = self.run_cli("--session", "nope")
        self.assertIn("沒有符合條件", out)
        rc, out = self.run_cli("--session", "sess")
        self.assertIn("agent 總數：5", out)


if __name__ == "__main__":
    unittest.main()
